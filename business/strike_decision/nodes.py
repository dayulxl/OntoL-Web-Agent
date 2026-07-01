"""
打击决策 — 图节点实现
-------------------
每个节点函数接收域 State 并返回状态更新字典。
"""
from business.strike_decision.state import StrikeDecisionState


async def collect_evidence(state: StrikeDecisionState) -> dict:
    """采集目标相关证据数据。"""
    request_data = state["input"]
    # TODO: 从多方数据源采集目标行为、关联关系等信息
    return {"data": {**state["data"], "collected_at": "2026-01-01T00:00:00Z"}}


async def assess_risk(state: StrikeDecisionState) -> dict:
    """风险评估（调用模型或规则引擎）。"""
    # TODO: 调用风险评估模型
    risk_level = "medium"
    risk_score = 0.45
    return {
        "data": {**state["data"], "risk_level": risk_level, "risk_score": risk_score},
        "risk_assessment": {"level": risk_level, "score": risk_score},
    }


async def make_decision(state: StrikeDecisionState) -> dict:
    """根据风险评估做出打击 / 监控 / 放行决策。"""
    assessment = state.get("risk_assessment", {})
    score = assessment.get("score", 0)
    if score > 0.8:
        decision = "strike"
    elif score > 0.5:
        decision = "monitor"
    else:
        decision = "dismiss"
    return {
        "data": {**state["data"], "decision": decision},
        "decision": decision,
    }


async def execute_strike(state: StrikeDecisionState) -> dict:
    """执行打击操作。"""
    # TODO: 触发打击流程（通知执行系统、记录日志等）
    return {"data": {**state["data"], "strike_executed": True}, "alert_sent": True}


async def monitor_target(state: StrikeDecisionState) -> dict:
    """将目标加入监控列表。"""
    # TODO: 添加到持续监控队列
    return {"data": {**state["data"], "monitoring_active": True}}


async def log_dismiss(state: StrikeDecisionState) -> dict:
    """记录放行决策 + 审计日志。"""
    return {"data": {**state["data"], "dismissed": True, "logged": True}}
