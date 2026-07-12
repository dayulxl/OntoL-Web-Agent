"""
图推理机业务域 — 公共 API
------------------------

内部系统可直接 import 调用，无需走 HTTP：

    from business.reasoning import ReasoningEngine, RuleRegistry, run_reasoning

    # 流式
    engine = ReasoningEngine(RuleRegistry.with_defaults())
    async for event in engine.run(seed_node_id=123):
        print(event.message)

    # 同步收集结果
    result = await run_reasoning(seed_node_id=123)
    print(result["log"], result["edges_built"])
"""

from business.reasoning.engine import ReasoningEngine, ReasoningEvent
from business.reasoning.rules import Rule, RuleRegistry, RuleVerdict, ValidationLevel
from business.reasoning.rules import (
    check_precondition, classify_effect, propagate_confidence,
    parse_swrl_effect, parse_rule_direction, DEFAULT_RULE,
)


async def run_reasoning(
    seed_node_id: int,
    cope_version: str = "",
    confidence_threshold: float = 0.5,
    rules: list[str] | None = None,
) -> dict:
    """
    图推理 — 同步收集式内部 API。

    供 AI Agent、工作流节点、orchestrator 等内部模块直接调用，
    无需经过 HTTP + SSE。

    参数:
        seed_node_id: 起点节点原生 ID
        cope_version: 副本版本号（空则自动生成）
        confidence_threshold: 置信度阈值 (0.01~1.0)
        rules: 启用的规则名称列表

    返回:
        {
            "cope_version": "v1",
            "clone_count": 5,
            "edges_built": 8,
            "merged_count": 3,
            "log": ["Step 1...", "Step 2...", ...],
            "error": str | None  (非 None 表示推理异常),
        }
    """
    eng = ReasoningEngine(
        registry=RuleRegistry.with_defaults(),
        confidence_threshold=confidence_threshold,
    )
    result = {
        "cope_version": "",
        "clone_count": 0,
        "edges_built": 0,
        "merged_count": 0,
        "log": [],
        "error": None,
    }
    try:
        async for event in eng.run(
            seed_node_id=seed_node_id,
            cope_version=cope_version,
            rules=rules,
        ):
            result["log"].append(event.message)
            if event.event == "step_end":
                if event.step == 1:
                    result["clone_count"] = len(eng.cm)
                elif event.step == 2:
                    result["edges_built"] = event.data.get("edge_count", 0)
                elif event.step == 3:
                    result["merged_count"] = event.data.get("merged_count", 0)
            elif event.event == "done":
                result["cope_version"] = eng.cope_version
                result["clone_count"] = len(eng.cm)
            elif event.event == "error":
                result["error"] = event.message
    except Exception as e:
        result["error"] = str(e)
    return result


async def run_reasoning_on_nodes(
    node_ids: list[int],
    confidence_threshold: float = 0.5,
    rules: list[str] | None = None,
) -> list[dict]:
    """
    批量推理 — 对多个节点依次执行推理。

    返回: [run_reasoning 结果, ...]
    """
    results = []
    for nid in node_ids:
        r = await run_reasoning(
            seed_node_id=nid,
            confidence_threshold=confidence_threshold,
            rules=rules,
        )
        results.append(r)
    return results
