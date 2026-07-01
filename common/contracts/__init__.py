"""
契约层 (Contracts Layer)
-----------------------
定义产品层对业务层的抽象契约。产品代码仅依赖此层的接口，
业务代码实现这些契约，从而实现产品 ↔ 业务的解耦隔离。

契约清单:
  - GraphExtension: 业务工作流图必须满足的 Protocol
  - GraphStateBase: 所有业务 State 必须包含的基础字段
"""
from common.contracts.graph_extension import GraphExtension
from common.contracts.state_schema import GraphStateBase

__all__ = ["GraphExtension", "GraphStateBase"]
