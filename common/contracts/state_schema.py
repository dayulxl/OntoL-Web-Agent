"""
状态基类契约
-----------
GraphStateBase —— 所有业务域 State 必须包含的基础字段。

业务域可以在 State 中追加自己的专用字段，但必须保证
这 7 个基础字段存在，以便框架（编排层、路由、checkpoint）
能正确读写通用状态信息。
"""
from typing import Optional, TypedDict


class GraphStateBase(TypedDict, total=False):
    """
    图状态基础字段。

    所有业务域 State TypedDict 必须包含这些字段。
    各字段的读写规则见 orchestrator/ORCHESTRATOR.md。

    Attributes:
        messages: 对话消息列表（兼容 LangGraph Message 格式）。
        input: 原始输入数据——只读！节点不得修改。
        current_step: 当前执行步骤名称。
        next_node: 驱动条件路由的目标节点名。
        data: 业务数据——各节点读写此字段传递中间结果。
        metadata: 元数据 {trace_id, user_id, workflow_name}。
        error: 错误信息（非 None 表示执行异常）。
    """
    messages: list
    input: dict
    current_step: str
    next_node: str
    data: dict
    metadata: dict
    error: Optional[str]
