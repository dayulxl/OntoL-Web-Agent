"""
推理引擎编排器
-------------
图推理机主循环 — 协调四个推理步骤，管理运行时状态。

四步流水线：
  Step 1 (step1_clone.py)   — 复制推理关联对象（种子+祖先+下游）
  Step 2 (step2_relink.py)  — 在副本节点间重建边关系
  Step 3 (step3_inherit.py) — 按 RDFS 语义继承父类属性
  Step 4 (step4_reason.py)  — 逐节点推理 + 叙述输出

每步通过 SSE yield 实时推送日志和结果。
"""

from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from common.utils.logger import get_logger
from business.reasoning.rules import RuleRegistry

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


# ── 四步推理模块（在 ReasoningEvent 之后导入，避免循环引用）──
from business.reasoning.step1_clone import step1_clone       # noqa: E402
from business.reasoning.step2_relink import step2_relink     # noqa: E402
from business.reasoning.step3_inherit import step3_inherit   # noqa: E402
from business.reasoning.step4_reason import step4_reason     # noqa: E402


# ═══════════════════════════════════════════════════════════════════
# 推理引擎 — 核心编排器
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ReasoningEngine:
    """图推理机引擎 — 薄编排层，协调四个推理步骤。

    本身不包含推理逻辑，只负责：
      1. 管理运行时共享状态（cm / ancestors / reasoning_log）
      2. 按序调用 step1 → step2 → step3 → step4
      3. 通过 SSE 事件流推送每步的日志和结果

    使用方式:
        engine = ReasoningEngine(registry)
        async for event in engine.run(seed_node_id=3, copy_version="v1"):
            yield f"data: {json.dumps(event)}\n\n"
    """

    # ── 配置 ──
    registry: RuleRegistry              # 规则注册表，包含所有已注册的推理规则
    confidence_threshold: float = 0.5   # 置信度阈值：低于此值则阻断推理链

    # ── 运行时共享状态（每次 run() 调用时重置）──
    cm: dict[int, tuple[dict, int]] = field(default_factory=dict)
    # ↑ 克隆映射表：{原生节点ID: (原生节点属性dict, 副本节点ID)}
    # Step 1 填充，Step 2-4 消费

    copy_version: str = ""
    # ↑ 副本版本号，注入到所有副本节点的属性中

    ancestors: list[dict] = field(default_factory=list)
    # ↑ 初始节点的 OWL2 祖先链（从近到远排列）

    reasoning_log: list[str] = field(default_factory=list)
    # ↑ 内存中的日志缓存（用于 debug 和回溯）

    async def _emit(self, event: ReasoningEvent) -> ReasoningEvent:
        """记录事件到内存日志，原样返回供上游 SSE 推送。"""
        self.reasoning_log.append(event.message)
        return event

    # ================================================================
    # 主入口 — run()
    # ================================================================

    async def run(
        self,
        seed_node_id: int,
        copy_version: str = "",
        rules: Optional[list[str]] = None,
    ) -> AsyncIterator[ReasoningEvent]:
        """执行完整推理流程 (Step 1-4)，返回异步迭代器供 SSE 流式消费。

        Args:
            seed_node_id: 初始节点原生 ID（Memgraph int64）
            copy_version: 副本版本号（空则自动生成）
            rules: 启用的规则名称列表（None = 全部启用）
        """
        # ── 副本 ID 必填校验 ──
        if not copy_version:
            yield await self._emit(ReasoningEvent(
                step=0, event="error",
                message="副本ID（copy_version）不能为空，请指定有效的副本版本号",
            ))
            return

        # ── 重置运行时状态 ──
        self.cm.clear()
        self.ancestors.clear()
        self.reasoning_log.clear()
        self.copy_version = copy_version

        # ── 设置规则启用状态 ──
        if rules:
            for r in self.registry.rules.values():
                r.enabled = r.name in rules

        # ── 推理开始 ──
        yield await self._emit(ReasoningEvent(
            step=0, event="step_start",
            message=f"═══ 推理开始 | 初始节点 ID={seed_node_id} | 副本版本={self.copy_version}",
            data={"seed_node_id": seed_node_id, "copy_version": self.copy_version},
        ))

        try:
            # ═══════════════════════════════════════════════
            # Step 1: 复制推理关联对象
            # ═══════════════════════════════════════════════
            yield await self._emit(ReasoningEvent(
                step=1, event="step_start",
                message="═══ Step 1: 复制推理关联对象"))
            async for event in step1_clone(seed_node_id, copy_version, self.cm, self.ancestors):
                yield await self._emit(event)
            yield await self._emit(ReasoningEvent(
                step=1, event="step_end",
                message=f"Step 1 完成 — 克隆 {len(self.cm)} 个节点"))

            # ═══════════════════════════════════════════════
            # Step 2: 创建副本节点之间的对应关系
            # ═══════════════════════════════════════════════
            yield await self._emit(ReasoningEvent(
                step=2, event="step_start",
                message="═══ Step 2: 创建副本节点之间的对应关系"))
            edge_count = await step2_relink(self.cm)
            yield await self._emit(ReasoningEvent(
                step=2, event="step_end",
                message=f"Step 2 完成 — 创建 {edge_count} 条关系",
                data={"edge_count": edge_count}))

            # ═══════════════════════════════════════════════
            # Step 3: 继承属性（RDFS 语义）
            # ═══════════════════════════════════════════════
            yield await self._emit(ReasoningEvent(
                step=3, event="step_start",
                message="═══ Step 3: 继承属性 (owl2:subClassOf 语义)"))
            merged_count = await step3_inherit(self.cm, self.ancestors)
            yield await self._emit(ReasoningEvent(
                step=3, event="step_end",
                message=f"Step 3 完成 — 属性继承应用于 {merged_count} 个节点",
                data={"merged_count": merged_count}))

            # ═══════════════════════════════════════════════
            # Step 4: 逐节点推理
            # ═══════════════════════════════════════════════
            yield await self._emit(ReasoningEvent(
                step=4, event="step_start",
                message="═══ Step 4: 逐节点推理"))
            async for event in step4_reason(
                seed_node_id, self.cm, self.ancestors, self.confidence_threshold
            ):
                yield await self._emit(event)

        except Exception as e:
            logger.error("reasoning_engine_error", extra={"error": str(e)})
            yield await self._emit(ReasoningEvent(
                step=0, event="error", message=f"推理异常: {e}"))
            raise

        # ── 推理完成 ──
        yield await self._emit(ReasoningEvent(
            step=0, event="done", message="═══ 推理完成",
            data={"clone_count": len(self.cm), "copy_version": self.copy_version}))
