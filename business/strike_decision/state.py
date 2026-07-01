"""
打击决策域 State Schema
-----------------------
打击决策工作流的 TypedDict 状态定义。

继承 GraphStateBase 获取框架要求的基础字段，
追加打击决策域专用字段。
"""
from typing import Optional

from common.contracts.state_schema import GraphStateBase


class StrikeDecisionState(GraphStateBase, total=False):
    """打击决策图状态。

    继承字段 (来自 GraphStateBase):
        messages: 对话消息列表（兼容 LangGraph 消息格式）。
        input: 原始输入数据。
        current_step: 当前执行步骤名称。
        next_node: 下一个要执行的节点（用于动态路由）。
        data: 业务数据（各节点读写此字段传递中间结果）。
        metadata: 元数据（含 trace_id、user_id 等）。
        error: 错误信息。

    域专用字段:
        target_profile: 目标画像。
        collected_evidence: 采集到的证据列表。
        risk_assessment: 风险评估结果。
        decision: 决策结论 (strike / monitor / dismiss)。
        decision_rationale: 决策理由。
        alert_sent: 是否已发送告警。
    """
    # --- 域专用字段 ---
    target_profile: dict
    collected_evidence: list
    risk_assessment: Optional[dict]
    decision: Optional[str]
    decision_rationale: Optional[str]
    alert_sent: bool
