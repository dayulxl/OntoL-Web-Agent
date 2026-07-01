"""
条件路由器
--------
根据状态中的 next_node 字段动态决定图的下一步，支持 LLM 驱动的智能路由。
"""
from typing import Optional

from orchestrator.state.schema import GraphState


class ConditionalRouter:
    """
    动态条件路由器。

    支持两种路由策略：
    1. 基于规则的确定性路由（依据 state 中的 next_node 字段）
    2. LLM 驱动的智能路由（调用模型决定下一步）
    """

    @staticmethod
    def rule_based(state: GraphState) -> str:
        """
        基于规则的路由。

        直接读取 state["next_node"] 作为下一步目标。
        若未设置则返回 END。
        """
        next_node = state.get("next_node")
        if next_node:
            return next_node
        return "__end__"

    @staticmethod
    async def llm_based(state: GraphState, available_nodes: list[str]) -> str:
        """
        LLM 驱动的智能路由。

        将当前状态和可用节点列表发送给 LLM，由 LLM 决定最佳下一步。
        """
        # TODO: 调用 LLM 进行路由决策
        # prompt = f"Given state: {state['data']}, available next steps: {available_nodes}, choose one."
        # response = await llm.invoke(prompt)
        # return response.strip()
        return available_nodes[0] if available_nodes else "__end__"

    @staticmethod
    async def multi_criteria(
        state: GraphState,
        criteria: dict,
    ) -> str:
        """
        多条件路由。

        根据多个条件组合判断下一步去向。
        criteria 格式: {"node_name": lambda state: bool, ...}
        """
        for node_name, predicate in criteria.items():
            if predicate(state):
                return node_name
        return "__end__"
