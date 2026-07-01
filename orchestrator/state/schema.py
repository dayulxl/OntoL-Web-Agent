"""
状态 Schema 定义
---------------
使用 TypedDict 定义图运行时的状态结构，供所有工作流复用。

继承 GraphStateBase 保证与契约层一致。
"""
from common.contracts.state_schema import GraphStateBase


class GraphState(GraphStateBase, total=False):
    """
    LangGraph 图状态 — 编排层内部使用的状态类型。

    继承 GraphStateBase 的全部基础字段。
    各业务域应继承 GraphStateBase 定义自己的 State，
    并追加域专用字段。
    """
    pass
