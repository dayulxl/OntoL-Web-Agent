"""
航路规划 — 图节点实现
-------------------
每个节点函数接收域 State 并返回状态更新字典。
"""
from business.route_planning.state import RoutePlanningState


async def classify_intent(state: RoutePlanningState) -> dict:
    """分类用户意图（航路查询、修改、对比等）。"""
    user_query = state["input"].get("query", "")
    # TODO: 调用 LLM 进行意图分类
    intent = "route_planning"
    return {"data": {**state["data"], "intent": intent}}


async def fetch_waypoints(state: RoutePlanningState) -> dict:
    """获取 / 解析途径点信息。"""
    waypoints = state.get("waypoints", [])
    # TODO: 从输入中解析起止点和途经点
    return {"data": {**state["data"], "waypoints": waypoints}}


async def generate_route(state: RoutePlanningState) -> dict:
    """调用航路生成算法 / LLM 生成路线。"""
    criteria = state.get("optimization_criteria", "distance")
    # TODO: 调用航路规划引擎
    generated = {"segments": [], "total_distance": 0.0, "criteria": criteria}
    return {"data": {**state["data"], "generated_route": generated}}


async def evaluate_alternatives(state: RoutePlanningState) -> dict:
    """评估并生成备选路线。"""
    # TODO: 生成多套方案并排序
    return {"data": {**state["data"], "alternatives": []}}


async def log_result(state: RoutePlanningState) -> dict:
    """记录规划结果（日志 / 数据库）。"""
    return {"data": {**state["data"], "logged": True}}
