"""能力层 — Agent 实现模块。

公开的子模块:
  - base:               BaseAgent 抽象基类（ReAct 模式）

注意:
  具体业务 Agent 已迁移至 business/ 层:
    - MasterAgent        → business/master_agent.py
    - RoutePlanningAgent → business/route_planning/agent.py
    - StrikeDecisionAgent→ business/strike_decision/agent.py

  能力层仅保留可复用的抽象基类，不包含业务逻辑。
"""
