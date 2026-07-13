"""
推理引擎主循环
-------------
图推理机 — 直接在 Memgraph 图上执行规则推理。

四个步骤：
  Step 1 — 复制所有推理关联对象（初始节点 + RDFS 祖先链 + 推理下游链）
  Step 2 — 创建副本节点之间的对应关系（原边 → 副本边）
  Step 3 — 继承属性（owl2:subClassOf 语义：祖先属性为基底，逐层覆盖，子节点扩展）
  Step 4 — 逐节点推理 + 叙述输出（precondition → effect → cost/duration/priority）

每步通过 SSE yield 实时推送日志和结果。
"""

import asyncio  # 异步迭代器支持（SSE 流式推送）
from dataclasses import dataclass, field  # 引擎和事件的轻量数据结构
from typing import AsyncIterator, Optional

from common.utils.logger import get_logger
# ── 图操作层（直接操作 Memgraph 节点/边）──
from business.reasoning.graph_ops import (
    get_node,                    # 按 ID 查单个节点
    get_relationships,           # 查节点的所有出边/入边
    clone_node,                  # 复制节点并注入 cope_version 属性
    clone_edge,                  # 在副本节点间复制边
    merge_inherited_props,       # 合并祖先属性到子节点（RDFS 语义）
    update_node_props,           # 更新节点属性
    get_outgoing_by_rel_type,    # 按关系类型查出边
    get_outgoing_inference_edges,# 查所有 actionType=inference 的出边
)
from business.transformation.owl2_converter import climb_subclass_chain  # 爬 OWL2 祖先链
from business.reasoning.rules import (
    Rule,                # 规则定义数据类
    RuleRegistry,        # 规则注册表（管理所有推理规则）
    RuleVerdict,         # 规则判定结果枚举（PASS / BLOCK / SKIP）
    ValidationLevel,     # 校验级别枚举（Strong 强阻断 / Weak 弱提醒）
    check_precondition,  # 前置条件校验函数
    classify_effect,     # 效果分类函数（判断走哪个推理引擎）
    propagate_confidence,# 置信度传播函数
    parse_swrl_effect,   # SWRL 语义解析
    parse_rule_direction,# 规则方向解析（前链/后链）
)

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════
# 推理事件 — SSE 流式推送的基本单元
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ReasoningEvent:
    """SSE 流式推送的推理事件。

    每执行一个操作（克隆节点、检查前置条件、输出日志等），
    引擎都会生成一个 ReasoningEvent 并通过异步生成器 yield 出去。
    上游（reasoning_routes.py）负责将其序列化为 SSE 格式。
    """
    step: int        # 当前步骤编号（1=克隆, 2=建关系, 3=属性继承, 4=逐节点推理）
    event: str       # 事件类型："step_start" | "log" | "step_end" | "done" | "error"
    message: str     # 人类可读的中文日志消息（展示在推理控制台）
    data: dict = field(default_factory=dict)  # 附加结构化数据（节点 ID、计数等）


# ═══════════════════════════════════════════════════════════════════
# 推理引擎 — 核心类，管理整个推理生命周期
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ReasoningEngine:
    """图推理机引擎。

    负责四步推理流程：
      Step 1 — 复制初始节点 + 祖先链 + 推理下游链到副本空间
      Step 2 — 在副本节点间重建原图的边关系
      Step 3 — 按 RDFS 语义逐层继承父类属性到子类副本
      Step 4 — 逐节点读取属性 + 沿 inference 边读边属性，执行推理叙述

    使用方式:
        engine = ReasoningEngine(registry)
        async for event in engine.run(seed_node_id=3, cope_version="v1"):
            yield f"data: {json.dumps(event)}\n\n"
    """

    # ── 配置 ──
    registry: RuleRegistry              # 规则注册表，包含所有已注册的推理规则
    confidence_threshold: float = 0.5   # 置信度阈值：低于此值则阻断推理链

    # ── 运行时状态（每次 run() 调用时重置）──
    cm: dict[int, tuple[dict, int]] = field(default_factory=dict)
    # ↑ 克隆映射表：{原生节点ID: (原生节点属性dict, 副本节点ID)}
    # 是整个推理流程的核心数据结构，Step 1 填充，Step 2-4 消费

    cope_version: str = ""
    # ↑ 副本版本号，会注入到所有副本节点的属性中，用于区分不同推理批次

    ancestors: list[dict] = field(default_factory=list)
    # ↑ 初始节点的 OWL2 祖先链（从近到远排列）

    reasoning_log: list[str] = field(default_factory=list)
    # ↑ 内存中的日志缓存（用于 debug 和回溯）

    async def _emit(self, event: ReasoningEvent) -> ReasoningEvent:
        """发射一个推理事件：写入内存日志 → 返回事件供上游 SSE 推送。"""
        self.reasoning_log.append(event.message)
        return event

    # ================================================================
    # 主入口 — run()
    # ================================================================
    # 推理的唯一对外入口。接收初始节点 ID 和可选配置，
    # 顺序执行 Step 1-4，每一步通过异步生成器 yield ReasoningEvent。

    async def run(
        self,
        seed_node_id: int,             # 推理起点：初始节点的原生 ID（Memgraph 中的 int64）
        cope_version: str = "",        # 副本版本号，空字符串则自动生成 8 位 UUID
        rules: Optional[list[str]] = None,  # 启用的规则名称列表；None 表示全部启用
    ) -> AsyncIterator[ReasoningEvent]:
        """
        执行完整推理流程 (Step 1-4)，返回异步迭代器供 SSE 流式消费。

        Args:
            seed_node_id: 初始节点原生 ID（Memgraph int64）。
            cope_version: 副本版本号（空则自动生成 UUID）。
            rules: 启用的规则名称列表（None = 全部启用）。
        """
        # ── 副本 ID 必填校验 ──
        if not cope_version:
            yield await self._emit(ReasoningEvent(
                step=0, event="error",
                message="副本ID（cope_version）不能为空，请指定有效的副本版本号",
            ))
            return

        # ── 重置运行时状态：每次 run() 调用都是全新的推理会话 ──
        self.cm.clear()           # 清空克隆映射表
        self.ancestors.clear()    # 清空祖先链
        self.reasoning_log.clear()# 清空内存日志
        self.cope_version = cope_version  # 设置副本版本号

        # ── 设置规则启用状态：为每个规则打上 enabled 标记 ──
        if rules:
            for r in self.registry.rules.values():
                r.enabled = r.name in rules  # 名单内的启用，名单外的禁用

        # ── 推理开始事件（step=0 表示全局事件）──
        yield await self._emit(ReasoningEvent(
            step=0, event="step_start",
            message=f"═══ 推理开始 | 初始节点 ID={seed_node_id} | 副本版本={self.cope_version}",
            data={"seed_node_id": seed_node_id, "cope_version": self.cope_version},
        ))

        try:
            # ── Step 1: 复制所有推理关联对象 ──
            yield await self._emit(ReasoningEvent(step=1, event="step_start", message="═══ Step 1: 复制推理关联对象"))
            async for event in self._step1_clone(seed_node_id):
                yield event
            yield await self._emit(ReasoningEvent(step=1, event="step_end", message=f"Step 1 完成 — 克隆 {len(self.cm)} 个节点"))

            # ── Step 2: 在副本节点间重建边关系 ──
            yield await self._emit(ReasoningEvent(step=2, event="step_start", message="═══ Step 2: 创建副本节点之间的对应关系"))
            edge_count = await self._step2_relink()
            yield await self._emit(ReasoningEvent(step=2, event="step_end", message=f"Step 2 完成 — 创建 {edge_count} 条关系"))

            # ── Step 3: 按 RDFS 语义继承属性 ──
            yield await self._emit(ReasoningEvent(step=3, event="step_start", message="═══ Step 3: 继承属性 (owl2:subClassOf 语义)"))
            merged_count = await self._step3_inherit()
            yield await self._emit(ReasoningEvent(step=3, event="step_end", message=f"Step 3 完成 — 属性继承应用于 {merged_count} 个节点"))

            # ── Step 4: 逐节点推理 —— 核心业务逻辑 ──
            yield await self._emit(ReasoningEvent(step=4, event="step_start", message="═══ Step 4: 逐节点推理"))
            async for event in self._step4_reason(seed_node_id):
                yield event

        except Exception as e:
            # ── 异常不吞掉：记录日志后重新抛出，让上游感知错误 ──
            logger.error("reasoning_engine_error", extra={"error": str(e)})
            yield await self._emit(ReasoningEvent(step=0, event="error", message=f"推理异常: {e}"))
            raise

        # ── 推理完成：汇总统计信息 ──
        yield await self._emit(ReasoningEvent(step=0, event="done", message="═══ 推理完成",
            data={"clone_count": len(self.cm), "cope_version": self.cope_version}))

    # ================================================================
    # Step 1 — 复制所有推理关联对象
    # ================================================================
    # 做三件事：
    #   1a. 沿 owl2:subClassOf 向上爬祖先链（父类→祖父→...→顶层）
    #   1b. 沿 actionType=inference 边向下爬推理下游链
    #   1c. 将所有收集到的节点克隆到副本空间，填充 self.cm 映射表
    # 克隆顺序很重要：祖先从顶层开始（reversed），然后是种子，最后是下游

    async def _step1_clone(self, seed_node_id: int) -> None:
        """复制初始节点 + RDFS 祖先链 + 推理下游链。

        所有克隆节点都会被注入 cope_version 属性，
        并记录到 self.cm 映射表中供后续步骤使用。
        """
        # ── 获取初始节点，不存在则直接抛异常 ──
        seed_node = await get_node(seed_node_id)
        if seed_node is None:
            raise ValueError(f"Seed node {seed_node_id} not found")

        yield await self._emit(ReasoningEvent(step=1, event="log",
            message=f"  初始节点: {seed_node['props'].get('code', seed_node_id)} (原生ID={seed_node_id})"))

        # ── 1a. 爬 OWL2 祖先链（owl2:subClassOf 语义）──
        # climb_subclass_chain 从初始节点出发，沿 subClassOf 边逐层上溯
        # 返回的列表从近到远：[父, 祖父, 曾祖父, ...]
        self.ancestors = await climb_subclass_chain(seed_node_id)
        yield await self._emit(ReasoningEvent(
            step=1, event="log",
            message=f"  owl2:subClassOf 祖先链: {len(self.ancestors)} 层 ({[a['props'].get('code','?') for a in self.ancestors]})",
            data={"ancestor_count": len(self.ancestors)},
        ))

        # ── 1b. 爬推理下游链 (actionType="inference") ──
        # 沿 actionType=inference 的边递归 BFS，收集所有下游节点
        downstream = []
        visited_ds = set()  # 防环：已访问节点集合
        await self._walk_inference_chain(seed_node_id, downstream, visited_ds)
        yield await self._emit(ReasoningEvent(
            step=1, event="log",
            message=f"  actionType=inference 下游链: {len(downstream)} 个节点",
            data={"downstream_count": len(downstream)},
        ))

        # ── 1c. 克隆三组节点到副本空间 ──
        # 克隆顺序：祖先（顶层先）→ 种子 → 下游
        # reversed: 祖先列表是 [父, 祖父, ...]，需要顶层先克隆，确保继承链方向正确

        for ancestor in reversed(self.ancestors):  # reversed: 顶层祖先先克隆
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
    # 遍历 self.cm 中所有已克隆的原生节点，对于每个原生节点的每条出边：
    # 如果目标节点也在 cm 中（已被克隆），则在两个副本节点之间创建同类型边。
    # 这保证了副本空间中的拓扑结构与原图一致。

    async def _step2_relink(self) -> int:
        """把所有原节点之间的边，按原始方向和类型复制到副本节点之间。

        Returns:
            int: 创建的副本边总数。
        """
        edge_count = 0
        # 遍历克隆映射表：{原生ID: (原生节点属性, 副本ID)}
        for orig_id, (orig_node, copy_id) in self.cm.items():
            # 查原生节点的所有出边
            rels = await get_relationships(orig_id, direction="out")
            for r in rels:
                target_orig = r["target_id"]  # 边的目标原生 ID
                if target_orig in self.cm:     # 目标节点也被克隆了
                    target_copy = self.cm[target_orig][1]  # 取目标的副本 ID
                    await clone_edge(copy_id, target_copy, r["rel_type"], r["rel_props"])
                    edge_count += 1
        return edge_count

    # ================================================================
    # Step 3 — 继承属性（RDFS 语义）
    # ================================================================
    # RDFS subClassOf 的核心语义：子类继承父类的所有属性。
    # 但子类可以覆盖父类的同名字段（子类优先）。
    # merge_inherited_props 实现了这个合并逻辑：
    #   祖先属性为基底 → 逐层被子类属性覆盖 → 子类扩展字段保留

    async def _step3_inherit(self) -> int:
        """RDFS 语义生效——遍历所有克隆节点，合并祖先属性到子节点副本。

        Returns:
            int: 属性发生变化的节点数量。
        """
        merged_count = 0
        for orig_id, (orig_node, copy_id) in self.cm.items():
            # 以祖先属性为底，用当前节点属性逐层覆盖
            merged = merge_inherited_props(self.ancestors, orig_node)
            if merged != orig_node.get("props", {}):
                # 属性有变化 → 写回副本节点
                await update_node_props(copy_id, merged)
                merged_count += 1
        return merged_count

    # ================================================================
    # Step 4 — 逐节点推理 + 叙述输出
    # ================================================================

    async def _walk_inference_chain(self, node_id: int, result: list, visited: set) -> None:
        """沿 actionType=inference 边递归下探，收集所有推理下游节点。

        使用 DFS 方式遍历图，visited 集合防止环路导致无限递归。
        结果按发现顺序追加到 result 列表中。
        """
        # ── 防环：已访问过的节点直接跳过 ──
        if node_id in visited:
            return
        visited.add(node_id)

        # ── 查当前节点的所有 actionType=inference 出边 ──
        records = await get_outgoing_inference_edges(node_id)
        for r in records:
            # 构建下游节点的轻量表示（只保留 id / labels / props）
            ds = {"id": r["id"], "labels": r["labels"], "props": r["props"]}
            result.append(ds)
            # 递归下探：从下游节点继续沿 inference 边走
            await self._walk_inference_chain(r["id"], result, visited)

    # ================================================================
    # Step 4 — 逐节点推理（节点属性 → 推理边属性）
    # ================================================================

    async def _step4_reason(self, seed_node_id: int) -> None:
        """遍历推理队列，逐节点读属性 + 沿 inference 边读边属性，完整叙述。

        推理执行顺序：
          ① hasPrecondition（前置条件）→ 阻断则跳过整个节点
          ② hasEffect（效果）→ 分类后走对应推理引擎
          ③ hasCost / hasDuration / hasPriority（消耗/时长/优先级）
          ④ composedOf（组合节点递归）
          ⑤ 沿 actionType=inference 边读取边属性，判断 Strong 阻断

        所有步骤均遵循"宽容执行"原则：有就执行，没有就跳过。
        """
        # ── 构建推理队列：种子 + 所有推理下游节点 ──
        queue = [seed_node_id]                      # 从初始节点开始
        ds = []                                      # 下游节点收集器
        await self._walk_inference_chain(seed_node_id, ds, set())
        queue.extend(d["id"] for d in ds)           # 种子 → 下游顺序排列

        # ── 置信度沿推理链累积乘法传播，初始 = 1.0（100%）──
        confidence = 1.0
        step_num = 0   # 输出用的步骤计数器
        seen = set()    # 防重：已处理过的节点 ID 集合

        # ── 遍历推理队列，逐节点处理 ──
        for orig_id in queue:
            # 跳过未被克隆的节点（不在 cm 中）或已处理过的节点
            if orig_id not in self.cm or orig_id in seen:
                continue
            step_num += 1
            seen.add(orig_id)
            orig_node, copy_id = self.cm[orig_id]   # 从 cm 取出原生节点和对应的副本 ID
            props = orig_node.get("props", {}) or {}
            code = props.get("code", str(orig_id))   # 优先用 code 字段，没有则用 ID

            yield await self._emit(ReasoningEvent(step=4, event="log",
                message=f"【第{step_num}步】{code} 原ID={orig_id} 副ID={copy_id}"))
            yield await self._emit(ReasoningEvent(step=4, event="log",
                message=f"  → 继承 {len(self.ancestors)} 个父类型属性"))

            # ── 置信度传播（有就乘，没有就维持）──
            node_conf = props.get("confidence")
            if node_conf is not None:
                try:
                    confidence *= float(node_conf)
                except (ValueError, TypeError):
                    pass
            if confidence < self.confidence_threshold:
                yield await self._emit(ReasoningEvent(step=4, event="log",
                    message=f"  ⛔ 置信度 {confidence:.2f} 低于阈值，阻断"))
                break

            # ═══════════════════════════════════════════════════════
            # ① 触发前约束 hasPrecondition — 最先执行，false 时整个节点停止
            # ═══════════════════════════════════════════════════════
            pre = props.get("hasPrecondition")
            precondition_passed = True
            if pre is not None and str(pre).strip():
                verdict = check_precondition(props, "hasPrecondition")
                if verdict == RuleVerdict.BLOCK:
                    precondition_passed = False
                    yield await self._emit(ReasoningEvent(step=4, event="log",
                        message=f"  hasPrecondition: {str(pre)[:80]} ❌ 阻断 → 本节点所有函数停止"))
                    continue  # 直接跳到下一个节点

            # ═══════════════════════════════════════════════════════
            # ② 效果 hasEffect — precondition 通过才执行
            # ═══════════════════════════════════════════════════════
            eff = props.get("hasEffect")
            if eff and str(eff).strip():
                yield await self._emit(ReasoningEvent(step=4, event="log",
                    message=f"  hasEffect: {str(eff)[:100]} → {classify_effect(str(eff))} 引擎"))

            # ═══════════════════════════════════════════════════════
            # ③ 消耗 hasCost — precondition 通过才执行，最多一个执行语言
            # ═══════════════════════════════════════════════════════
            cost_raw = props.get("hasCost")
            if cost_raw is not None and str(cost_raw).strip():
                cost_str = str(cost_raw).strip()
                yield await self._emit(ReasoningEvent(step=4, event="log",
                    message=f"  hasCost: {cost_str[:200]}"))

            # ── 其他可选字段：有就输出 ──
            for k, label in [("hasDuration", "hasDuration(s)"), ("hasPriority", "hasPriority(等级,10级最高)")]:
                v = props.get(k)
                if v is not None:
                    yield await self._emit(ReasoningEvent(step=4, event="log", message=f"  {label}: {v}"))

            # ── ④ composedOf（组合/嵌套节点）── 有则列出子节点，提示递归执行
            comp = props.get("composedOf")
            if comp:
                parts = [p.strip() for p in str(comp).split(";") if p.strip()]
                yield await self._emit(ReasoningEvent(step=4, event="log",
                    message=f"  composedOf: {parts}（递归执行）"))

            # ═══════════════════════════════════════════════════
            # 沿 actionType=inference 边走 → 读边上标准属性
            # ═══════════════════════════════════════════════════
            rels = await get_relationships(orig_id, direction="out")
            for r in rels:
                eprops = r.get("rel_props", {}) or {}
                etype = r.get("rel_type", "")

                # 判断是否为推理边：边类型含 "inference" OR actionType 属性 = "inference"
                is_inf = "inference" in str(etype).lower() or str(eprops.get("actionType", "")).lower() == "inference"
                if not is_inf:
                    continue

                tgt_code = r["target_props"].get("code", str(r["target_id"]))
                yield await self._emit(ReasoningEvent(step=4, event="log",
                    message=f"  → actionType=inference → 下游: {tgt_code}"))

                # 9 个标准边属性 — 有就输出并判断，没有就跳过（宽容执行）
                for ek, elabel, eicon in [
                    ("required",        "required(阻断控制)",    "🛑"),
                    ("validationType",  "validationType(规则级别)", "⚖️"),
                    ("ruleId",          "ruleId(规则锚点)",      "📎"),
                    ("func",            "func(执行指令)",        "⚙️"),
                    ("id",              "id(数据锚点)",          "📍"),
                    ("msg",             "msg(作用说明)",         "📝"),
                    ("synonym",         "synonym(同义词)",       "🔄"),
                    ("queryVariant",    "queryVariant(错意词)",   "🔍"),
                ]:
                    ev = eprops.get(ek)
                    if ev is not None and str(ev).strip():
                        yield await self._emit(ReasoningEvent(step=4, event="log",
                            message=f"    {eicon} {elabel}: {ev}"))

                # required=true + validationType=Strong → 阻断
                req = eprops.get("required")
                vtype = str(eprops.get("validationType", "")).strip()
                if str(req).lower() in ("true", "1") and vtype == "Strong":
                    yield await self._emit(ReasoningEvent(step=4, event="log",
                        message=f"    🛑 Strong 强校验阻断"))
