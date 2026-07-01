"""
业务域层 (Business Domain Layer)
--------------------------------
按业务域组织的 LangGraph 工作流 + Agent。每个业务域是独立子包，
包含自己的图定义、状态 Schema、节点实现、Agent 和专用提示词/工具。

隔离边界:
  - 业务代码仅依赖 common.contracts 契约层和 orchestrator 的抽象基类
  - 产品代码 (orchestrator) 通过本模块的 REGISTRY 列表发现业务图
  - 不再使用 pkgutil 自动扫描，业务域必须显式注册

依赖:
  - orchestrator.graphs.base.BaseWorkflowGraph (抽象基类，提供默认实现)
  - capabilities.agents.base.BaseAgent (Agent 基类)
  - capabilities.* (接口 / 注册中心)
  - common.contracts.GraphExtension (扩展点协议)
  - common.* (配置 / 异常 / 工具)

目录约定:
    business/
        __init__.py         # 本文件 — 业务层入口 + REGISTRY
        master_agent.py     # MasterAgent — 跨域总调度 Agent
        prompts/            # 跨域共享提示词（如 master.txt）
        <domain_name>/
            __init__.py
            graph.py        -- 工作流图类 (继承 BaseWorkflowGraph)
            state.py        -- 域专用 State TypedDict (继承 GraphStateBase)
            nodes.py        -- 图节点实现
            agent.py        -- 域专用 Agent (继承 BaseAgent)
            prompts/        -- 域专用提示词模板 (.txt)
            tools/          -- 域专用工具定义
"""

# ------------------------------------------------------------------
# 显式注册 — GraphExecutor 从此列表加载业务图
# ------------------------------------------------------------------
# 新增业务域时，在此处添加导入和注册：
#
#   from business.<new_domain>.graph import <NewDomainGraph>
#   REGISTRY = [..., <NewDomainGraph>]
#
# 注册的类必须满足 GraphExtension 协议（通常继承 BaseWorkflowGraph 即可）。

from business.route_planning.graph import RoutePlanningGraph
from business.strike_decision.graph import StrikeDecisionGraph

REGISTRY = [RoutePlanningGraph, StrikeDecisionGraph]
