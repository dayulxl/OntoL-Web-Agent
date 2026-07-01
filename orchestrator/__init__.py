"""
LangGraph 编排层 (Orchestrator Layer)
-------------------------------------
核心调度引擎，负责图结构的定义、状态管理和流程控制。
每个业务图独立模块，通过 StateGraph 定义节点和边，
状态通过 Postgres checkpoint 持久化，支持断点续跑和故障恢复。
"""
