"""
推理引擎主循环
-------------
图推理机 — 直接在 Memgraph 图上执行规则推理。

四个步骤：
  Step 1 — 复制所有推理关联对象（种子节点 + RDFS 祖先链 + 推理下游链）
  Step 2 — 创建副本节点之间的对应关系（原边 → 副本边）
  Step 3 — 继承属性（owl2:subClassOf 语义：祖先属性为基底，逐层覆盖，子节点扩展）
  Step 4 — 逐节点推理 + 叙述输出（precondition → effect → cost/duration/priority）

每步通过 SSE yield 实时推送日志和结果。
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from common.utils.logger import get_logger
from business.reasoning.graph_ops import (
    get_node,
    get_relationships,
    clone_node,
    clone_edge,
    merge_inherited_props,
    update_node_props,
    get_outgoing_by_rel_type,
)
from business.transformation.owl2_converter import climb_subclass_chain
from business.reasoning.rules import (
    Rule,
    RuleRegistry,
    RuleVerdict,
    ValidationLevel,
    check_precondition,
    classify_effect,
    propagate_confidence,
    parse_swrl_effect,
    parse_rule_direction,
)

logger = get_logger(__name__)


# ---- 推理事件 ----

@dataclass
class ReasoningEvent:
    """SSE 流式推送的推理事件。"""
    step: int        # 步骤 1-4
    event: str       # "step_start" | "log" | "step_end" | "done" | "error"
    message: str
    data: dict = field(default_factory=dict)


# ---- 推理引擎 ----

@dataclass
class ReasoningEngine:
    """图推理机引擎。

    使用方式:
        engine = ReasoningEngine(registry)
        async for event in engine.run(seed_node_id=3, cope_version="v1"):
            yield f"data: {json.dumps(event)}\n\n"
    """

    registry: RuleRegistry
    confidence_threshold: float = 0.5

    # 运行时状态
    cm: dict[int, tuple[dict, int]] = field(default_factory=dict)   # 原生ID → (原节点, 副本ID)
    cope_version: str = ""
    ancestors: list[dict] = field(default_factory=list)
    reasoning_log: list[str] = field(default_factory=list)

    async def _emit(self, event: ReasoningEvent) -> ReasoningEvent:
        self.reasoning_log.append(event.message)
        return event

    # ================================================================
    # 主入口
    # ================================================================

    async def run(
        self,
        seed_node_id: int,
        cope_version: str = "",
        rules: Optional[list[str]] = None,
    ) -> AsyncIterator[ReasoningEvent]:
        """
        执行完整推理流程 (Step 1-4)。

        Args:
            seed_node_id: 种子节点原生 ID。
            cope_version: 副本版本号（空则自动生成 UUID）。
            rules: 启用的规则名称列表（None = 全部启用）。
        """
        self.cm.clear()
        self.ancestors.clear()
        self.reasoning_log.clear()
        self.cope_version = cope_version or uuid.uuid4().hex[:8]

        # 设置规则启用状态
        if rules:
            for r in self.registry.rules.values():
                r.enabled = r.name in rules

        yield await self._emit(ReasoningEvent(
            step=0, event="step_start",
            message=f"═══ 推理开始 | 种子节点 ID={seed_node_id} | 副本版本={self.cope_version}",
            data={"seed_node_id": seed_node_id, "cope_version": self.cope_version},
        ))

        try:
            # Step 1
            yield await self._emit(ReasoningEvent(step=1, event="step_start", message="═══ Step 1: 复制推理关联对象"))
            async for event in self._step1_clone(seed_node_id):
                yield event
            yield await self._emit(ReasoningEvent(step=1, event="step_end", message=f"Step 1 完成 — 克隆 {len(self.cm)} 个节点"))

            # Step 2
            yield await self._emit(ReasoningEvent(step=2, event="step_start", message="═══ Step 2: 创建副本节点之间的对应关系"))
            edge_count = await self._step2_relink()
            yield await self._emit(ReasoningEvent(step=2, event="step_end", message=f"Step 2 完成 — 创建 {edge_count} 条关系"))

            # Step 3
            yield await self._emit(ReasoningEvent(step=3, event="step_start", message="═══ Step 3: 继承属性 (owl2:subClassOf 语义)"))
            merged_count = await self._step3_inherit()
            yield await self._emit(ReasoningEvent(step=3, event="step_end", message=f"Step 3 完成 — 属性继承应用于 {merged_count} 个节点"))

            # Step 4
            yield await self._emit(ReasoningEvent(step=4, event="step_start", message="═══ Step 4: 逐节点推理"))
            async for event in self._step4_reason(seed_node_id):
                yield event

        except Exception as e:
            logger.error("reasoning_engine_error", extra={"error": str(e)})
            yield await self._emit(ReasoningEvent(step=0, event="error", message=f"推理异常: {e}"))
            raise

        yield await self._emit(ReasoningEvent(step=0, event="done", message="═══ 推理完成",
            data={"clone_count": len(self.cm), "cope_version": self.cope_version}))

    # ================================================================
    # Step 1 — 复制所有推理关联对象
    # ================================================================

    async def _step1_clone(self, seed_node_id: int) -> None:
        """复制种子节点 + RDFS 祖先链 + 推理下游链。"""
        seed_node = await get_node(seed_node_id)
        if seed_node is None:
            raise ValueError(f"Seed node {seed_node_id} not found")

        yield await self._emit(ReasoningEvent(step=1, event="log",
            message=f"  种子节点: {seed_node['props'].get('code', seed_node_id)} (原生ID={seed_node_id})"))

        # 1a. 爬 OWL2 祖先链（owl2:subClassOf 语义）
        self.ancestors = await climb_subclass_chain(seed_node_id)
        yield await self._emit(ReasoningEvent(
            step=1, event="log",
            message=f"  owl2:subClassOf 祖先链: {len(self.ancestors)} 层 ({[a['props'].get('code','?') for a in self.ancestors]})",
            data={"ancestor_count": len(self.ancestors)},
        ))

        # 1b. 爬推理下游链 (actionType="inference")
        downstream = []
        visited_ds = set()
        await self._walk_inference_chain(seed_node_id, downstream, visited_ds)
        yield await self._emit(ReasoningEvent(
            step=1, event="log",
            message=f"  actionType=inference 下游链: {len(downstream)} 个节点",
            data={"downstream_count": len(downstream)},
        ))

        # 1c. 克隆 — 祖先从顶层开始 → 种子 → 下游
        for ancestor in reversed(self.ancestors):  # reversed: 顶层先克隆
            new_id = await clone_node(ancestor["id"], self.cope_version, self.cm)
            yield await self._emit(ReasoningEvent(step=1, event="log",
                message=f"  克隆祖先: {ancestor['props'].get('code','?')} (原={ancestor['id']} → 副={new_id})"))

        seed_copy_id = await clone_node(seed_node_id, self.cope_version, self.cm)
        yield await self._emit(ReasoningEvent(step=1, event="log",
            message=f"  克隆种子: {seed_node['props'].get('code','?')} (原={seed_node_id} → 副={seed_copy_id})"))

        for ds in downstream:
            ds_copy_id = await clone_node(ds["id"], self.cope_version, self.cm)
            yield await self._emit(ReasoningEvent(step=1, event="log",
                message=f"  克隆下游: {ds['props'].get('code','?')} (原={ds['id']} → 副={ds_copy_id})"))

    # ================================================================
    # Step 2 — 创建副本节点之间的对应关系
    # ================================================================

    async def _step2_relink(self) -> int:
        """把所有原节点之间的边，按原始方向复制到副本节点之间。"""
        edge_count = 0
        for orig_id, (orig_node, copy_id) in self.cm.items():
            rels = await get_relationships(orig_id, direction="out")
            for r in rels:
                target_orig = r["target_id"]
                if target_orig in self.cm:
                    target_copy = self.cm[target_orig][1]
                    await clone_edge(copy_id, target_copy, r["rel_type"], r["rel_props"])
                    edge_count += 1
        return edge_count

    # ================================================================
    # Step 3 — 继承属性
    # ================================================================

    async def _step3_inherit(self) -> int:
        """RDFS 语义生效——子类继承父类属性。"""
        merged_count = 0
        for orig_id, (orig_node, copy_id) in self.cm.items():
            merged = merge_inherited_props(self.ancestors, orig_node)
            if merged != orig_node.get("props", {}):
                await update_node_props(copy_id, merged)
                merged_count += 1
        return merged_count

    # ================================================================
    # Step 4 — 逐节点推理 + 叙述输出
    # ================================================================

    async def _walk_inference_chain(self, node_id: int, result: list, visited: set) -> None:
        """沿 actionType=inference 递归下探（BFS 顺序）。"""
        if node_id in visited:
            return
        visited.add(node_id)
        records = await get_outgoing_by_rel_type(node_id, "inference")
        for r in records:
            ds = {"id": r["id"], "labels": r["labels"], "props": r["props"]}
            result.append(ds)
            await self._walk_inference_chain(r["id"], result, visited)

    async def _step4_reason(self, seed_node_id: int) -> None:
        """按推理队列顺序逐节点执行。"""
        # 构建推理队列：种子 → 下游1 → 下游2 → ...
        queue = [seed_node_id]
        downstream_step4 = []
        visited_s4 = set()
        await self._walk_inference_chain(seed_node_id, downstream_step4, visited_s4)
        queue.extend(d["id"] for d in downstream_step4)

        confidence = 1.0
        step_num = 0

        for orig_id in queue:
            if orig_id not in self.cm:
                continue
            step_num += 1
            node_tuple = self.cm[orig_id]
            if node_tuple is None:
                continue
            orig_node, copy_id = node_tuple
            props = orig_node.get("props", {})
            code = props.get("code", str(orig_id))

            yield await self._emit(ReasoningEvent(
                step=4, event="log",
                message=f"【第{step_num}步】{code} 原ID={orig_id} 副ID={copy_id}"))
            yield await self._emit(ReasoningEvent(
                step=4, event="log",
                message=f"  → 继承 {len(self.ancestors)} 个父类型属性"))

            # ---- 置信度传播 ----
            confidence, blocked = propagate_confidence(confidence, props, self.confidence_threshold)
            if blocked:
                yield await self._emit(ReasoningEvent(
                    step=4, event="log",
                    message=f"  ⛔ 置信度 {confidence:.2f} 低于阈值 {self.confidence_threshold}，阻断"))
                break

            # ---- 前置条件 ----
            precond_verdict = check_precondition(props, "hasPrecondition")
            precond_raw = props.get("hasPrecondition", "(无)")
            if precond_verdict == RuleVerdict.PASS:
                yield await self._emit(ReasoningEvent(step=4, event="log", message=f"  hasPrecondition: {precond_raw} ✅ 通过"))
            elif precond_verdict == RuleVerdict.BLOCK:
                yield await self._emit(ReasoningEvent(step=4, event="log", message=f"  hasPrecondition: {precond_raw} ❌ 阻断"))
                # 强校验则停止，弱校验继续
                for rule in self.registry.get_enabled():
                    if rule.validation_level == ValidationLevel.STRONG:
                        continue  # 不继续下游
                continue
            else:
                yield await self._emit(ReasoningEvent(step=4, event="log", message=f"  hasPrecondition: (无) → 跳过"))

            # ---- 效果 ----
            effect_val = props.get("hasEffect", "")
            if effect_val:
                effect_type = classify_effect(str(effect_val))
                yield await self._emit(ReasoningEvent(step=4, event="log",
                    message=f"  hasEffect: {effect_val} → {effect_type} 引擎"))
                if effect_type == "swrl":
                    parsed = parse_swrl_effect(str(effect_val))
                    yield await self._emit(ReasoningEvent(step=4, event="log",
                        message=f"  ✅ 触发成功: {parsed}"))
                elif effect_type == "rule":
                    direction = parse_rule_direction(str(effect_val))
                    yield await self._emit(ReasoningEvent(step=4, event="log",
                        message=f"  推理方向: {direction}"))

            # ---- 成本/时长/优先级 ----
            cost = props.get("hasCost")
            duration = props.get("hasDuration")
            priority = props.get("hasPriority")
            if cost is not None:
                yield await self._emit(ReasoningEvent(step=4, event="log", message=f"  hasCost: {cost}"))
            if duration is not None:
                yield await self._emit(ReasoningEvent(step=4, event="log", message=f"  hasDuration: {duration}s"))
            if priority is not None:
                yield await self._emit(ReasoningEvent(step=4, event="log", message=f"  hasPriority: {priority}（等级{priority}，10级最高）"))

            # ---- 组合执行 ----
            composed = props.get("composedOf", "")
            if composed:
                parts = [p.strip() for p in str(composed).split(";") if p.strip()]
                yield await self._emit(ReasoningEvent(step=4, event="log",
                    message=f"  composedOf: {parts}（递归执行）"))

            # ---- 推理跳转 ----
            rels = await get_relationships(orig_id, direction="out")
            inference_targets = [
                r for r in rels
                if r["rel_props"].get("actionType") == "inference"
            ]
            for tgt in inference_targets:
                tgt_code = tgt["target_props"].get("code", str(tgt["target_id"]))
                yield await self._emit(ReasoningEvent(step=4, event="log",
                    message=f"  → 【{effect_val}】→ 下游节点 {tgt_code}"))
