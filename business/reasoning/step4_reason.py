"""
Step 4 — 逐节点推理 + 叙述输出
------------------------------
遍历推理队列，逐节点读取属性 + 沿 inference 边读取边属性，完整叙述。

推理执行顺序：
  ① precondition（前置条件）→ 阻断则跳过整个节点
  ② effect（效果）→ 分类后走对应推理引擎
  ③ cost / duration / priority（消耗/时长/优先级）
  ④ 沿 actionType=inference 边读取边属性，判断 Strong 阻断

所有步骤遵循"宽容执行"原则：属性存在则处理，缺失则跳过。
"""

from typing import AsyncIterator

from business.reasoning.engine import ReasoningEvent
from business.reasoning.graph_ops import get_relationships, walk_inference_chain
from business.reasoning.rules import (
    RuleVerdict,
    check_precondition,
    classify_effect,
)


async def step4_reason(
    seed_node_id: int,
    cm: dict[int, tuple[dict, int]],
    ancestors: list[dict],
    confidence_threshold: float,
) -> AsyncIterator[ReasoningEvent]:
    """遍历推理队列，逐节点读属性 + 沿 inference 边读边属性，输出推理叙述。

    推理队列构建：种子 + 所有 actionType=inference 下游节点
    置信度沿链累积乘法传播，低于阈值时整条链阻断。

    Args:
        seed_node_id: 初始节点原生 ID
        cm: 克隆映射表 {原生ID: (原生节点dict, 副本ID)}
        ancestors: 祖先链列表
        confidence_threshold: 置信度阈值（0.01~1.0），低于此值阻断

    Yields:
        ReasoningEvent: 每个推理步骤对应一条或多条 log 事件
    """
    # ── 构建推理队列：种子 + 下游 ──
    queue: list[int] = [seed_node_id]
    ds: list[dict] = []
    await walk_inference_chain(seed_node_id, ds, set())
    queue.extend(d["id"] for d in ds)

    # ── 置信度沿推理链累积乘法传播 ──
    confidence = 1.0
    step_num = 0
    seen: set[int] = set()

    for orig_id in queue:
        if orig_id not in cm or orig_id in seen:
            continue
        step_num += 1
        seen.add(orig_id)
        orig_node, copy_id = cm[orig_id]
        props = orig_node.get("props", {}) or {}
        code = props.get("code", str(orig_id))

        yield ReasoningEvent(step=4, event="log",
            message=f"【第{step_num}步】{code} 原ID={orig_id} 副ID={copy_id}")
        yield ReasoningEvent(step=4, event="log",
            message=f"  → 继承 {len(ancestors)} 个父类型属性")

        # ── 置信度传播 ──
        node_conf = props.get("confidence")
        if node_conf is not None:
            try:
                confidence *= float(node_conf)
            except (ValueError, TypeError):
                pass
        if confidence < confidence_threshold:
            yield ReasoningEvent(step=4, event="log",
                message=f"  ⛔ 置信度 {confidence:.2f} 低于阈值，阻断")
            break

        # ═══════════════════════════════════════════════
        # ① precondition 前置条件 — 最先执行
        # ═══════════════════════════════════════════════
        pre = props.get("precondition")
        if pre is not None and str(pre).strip():
            verdict = check_precondition(props, "precondition")
            if verdict == RuleVerdict.BLOCK:
                yield ReasoningEvent(step=4, event="log",
                    message=f"  precondition: {str(pre)[:80]} ❌ 阻断 → 本节点所有函数停止")
                continue

        # ═══════════════════════════════════════════════
        # ② effect 效果
        # ═══════════════════════════════════════════════
        eff = props.get("effect")
        if eff and str(eff).strip():
            yield ReasoningEvent(step=4, event="log",
                message=f"  effect: {str(eff)[:100]} → {classify_effect(str(eff))} 引擎")

        # ═══════════════════════════════════════════════
        # ③ cost 消耗
        # ═══════════════════════════════════════════════
        cost_raw = props.get("cost")
        if cost_raw is not None and str(cost_raw).strip():
            cost_str = str(cost_raw).strip()
            yield ReasoningEvent(step=4, event="log",
                message=f"  cost: {cost_str[:200]}")

        # ── 可选字段：duration / priority ──
        for k, label in [("duration", "duration(s)"), ("priority", "priority(等级,10级最高)")]:
            v = props.get(k)
            if v is not None:
                yield ReasoningEvent(step=4, event="log", message=f"  {label}: {v}")

        # ── 组合节点 ──
        comp = props.get("is_composed_of")
        if comp:
            parts = [p.strip() for p in str(comp).split(";") if p.strip()]
            yield ReasoningEvent(step=4, event="log",
                message=f"  composedOf: {parts}（递归执行）")

        # ═══════════════════════════════════════════════
        # 沿 actionType=inference 边 → 边属性
        # ═══════════════════════════════════════════════
        rels = await get_relationships(orig_id, direction="out")
        for r in rels:
            eprops = r.get("rel_props", {}) or {}
            etype = r.get("rel_type", "")

            # 判断推理边
            is_inf = "inference" in str(etype).lower() or \
                     str(eprops.get("actionType", "")).lower() == "inference"
            if not is_inf:
                continue

            tgt_code = r["target_props"].get("code", str(r["target_id"]))
            yield ReasoningEvent(step=4, event="log",
                message=f"  → actionType=inference → 下游: {tgt_code}")

            # 8 个标准边属性 — 有则输出（宽容执行）
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
                    yield ReasoningEvent(step=4, event="log",
                        message=f"    {eicon} {elabel}: {ev}")

            # required=true + validationType=Strong → 阻断
            req = eprops.get("required")
            vtype = str(eprops.get("validationType", "")).strip()
            if str(req).lower() in ("true", "1") and vtype == "Strong":
                yield ReasoningEvent(step=4, event="log",
                    message=f"    🛑 Strong 强校验阻断")
