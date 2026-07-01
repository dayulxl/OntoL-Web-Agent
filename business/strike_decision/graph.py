"""
打击决策工作流
------------
业务流程: START → collect_evidence → assess_risk → make_decision
            → [execute_strike / monitor_target / log_dismiss] → END
"""
from typing import Literal

from langgraph.graph import StateGraph, START, END

from orchestrator.graphs.base import BaseWorkflowGraph
from business.strike_decision.state import StrikeDecisionState
from business.strike_decision.nodes import (
    collect_evidence,
    assess_risk,
    make_decision,
    execute_strike,
    monitor_target,
    log_dismiss,
)


class StrikeDecisionGraph(BaseWorkflowGraph):
    """
    打击决策工作流图。

    流程: START → collect → assess → decide → [strike / monitor / dismiss] → END
    """

    graph_name = "strike_decision"

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(StrikeDecisionState)

        workflow.add_node("collect_evidence", collect_evidence)
        workflow.add_node("assess_risk", assess_risk)
        workflow.add_node("make_decision", make_decision)
        workflow.add_node("execute_strike", execute_strike)
        workflow.add_node("monitor_target", monitor_target)
        workflow.add_node("log_dismiss", log_dismiss)

        workflow.add_edge(START, "collect_evidence")
        workflow.add_edge("collect_evidence", "assess_risk")
        workflow.add_edge("assess_risk", "make_decision")
        workflow.add_conditional_edges(
            "make_decision",
            _route_after_decision,
            {
                "strike": "execute_strike",
                "monitor": "monitor_target",
                "dismiss": "log_dismiss",
            },
        )
        workflow.add_edge("execute_strike", END)
        workflow.add_edge("monitor_target", END)
        workflow.add_edge("log_dismiss", END)

        return workflow


def _route_after_decision(
    state: StrikeDecisionState,
) -> Literal["strike", "monitor", "dismiss"]:
    """根据决策结果路由到不同分支。"""
    decision = state.get("decision", "dismiss")
    if decision == "strike":
        return "strike"
    elif decision == "monitor":
        return "monitor"
    else:
        return "dismiss"
