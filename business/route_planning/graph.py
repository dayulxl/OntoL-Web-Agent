"""
航路规划工作流
------------
业务流程: START → classify_intent → fetch_waypoints → generate_route
            → evaluate_alternatives → log_result → END
"""
from langgraph.graph import StateGraph, START, END

from orchestrator.graphs.base import BaseWorkflowGraph
from business.route_planning.state import RoutePlanningState
from business.route_planning.nodes import (
    classify_intent,
    fetch_waypoints,
    generate_route,
    evaluate_alternatives,
    log_result,
)


class RoutePlanningGraph(BaseWorkflowGraph):
    """
    航路规划工作流图。

    流程: START → classify → fetch → generate → evaluate → log → END
    """

    graph_name = "route_planning"

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(RoutePlanningState)

        workflow.add_node("classify_intent", classify_intent)
        workflow.add_node("fetch_waypoints", fetch_waypoints)
        workflow.add_node("generate_route", generate_route)
        workflow.add_node("evaluate_alternatives", evaluate_alternatives)
        workflow.add_node("log_result", log_result)

        workflow.add_edge(START, "classify_intent")
        workflow.add_edge("classify_intent", "fetch_waypoints")
        workflow.add_edge("fetch_waypoints", "generate_route")
        workflow.add_edge("generate_route", "evaluate_alternatives")
        workflow.add_edge("evaluate_alternatives", "log_result")
        workflow.add_edge("log_result", END)

        return workflow
