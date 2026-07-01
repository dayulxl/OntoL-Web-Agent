"""
航路规划域 State Schema
-----------------------
航路规划工作流的 TypedDict 状态定义。

继承 GraphStateBase 获取框架要求的基础字段，
追加航路规划域专用字段。
"""
from typing import Optional

from common.contracts.state_schema import GraphStateBase


class RoutePlanningState(GraphStateBase, total=False):
    """航路规划图状态。

    继承字段 (来自 GraphStateBase):
        messages: 对话消息列表（兼容 LangGraph 消息格式）。
        input: 原始输入数据。
        current_step: 当前执行步骤名称。
        next_node: 下一个要执行的节点（用于动态路由）。
        data: 业务数据（各节点读写此字段传递中间结果）。
        metadata: 元数据（含 trace_id、user_id 等）。
        error: 错误信息。

    域专用字段:
        route_type: 路线类型（sea / air / land）。
        waypoints: 途径点列表。
        optimization_criteria: 优化标准（distance / time / cost）。
        generated_route: 生成的路线结果。
        route_alternatives: 备选路线列表。
    """
    # --- 域专用字段 ---
    route_type: str
    waypoints: list
    optimization_criteria: str
    generated_route: Optional[dict]
    route_alternatives: Optional[list]
