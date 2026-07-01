"""
图扩展契约
---------
GraphExtension Protocol —— 产品层 (orchestrator) 对业务工作流图的唯一期待。

业务域只需要满足此协议即可被 GraphExecutor 识别和调度，
无需直接依赖 orchestrator 的内部实现。
"""
from typing import Any, AsyncIterator, Optional, Protocol, runtime_checkable


@runtime_checkable
class GraphExtension(Protocol):
    """
    业务工作流图扩展点协议。

    这是产品层与业务层之间的隔离边界。业务图只需满足此协议，
    无需了解 orchestrator 的内部如何调度、如何管理 checkpoint。

    协议要求:
      - graph_name: 唯一标识名，字符串类属性
      - initialize(): 初始化图（编译 + 创建 checkpointer）
      - run(): 同步执行，返回最终结果
      - stream(): 流式执行，逐步产出事件
      - get_state(): 根据 thread_id 查询执行状态
      - close(): 清理资源

    注意: 这是一个 Protocol，业务图可以通过继承 BaseWorkflowGraph
    (orchestrator 提供的默认实现) 来间接满足此协议，也可以完全自行实现。
    """

    graph_name: str

    async def initialize(self) -> None:
        """初始化工作流图：编译 StateGraph 并创建 checkpointer。"""
        ...

    async def run(
        self,
        input_data: dict,
        config: Optional[dict] = None,
    ) -> dict:
        """
        同步执行工作流图。

        Args:
            input_data: 工作流输入数据
            config: 运行时配置，至少包含 {"configurable": {"thread_id": "..."}}

        Returns:
            dict 包含 run_id, status, output
        """
        ...

    async def stream(
        self,
        input_data: dict,
        config: Optional[dict] = None,
    ) -> AsyncIterator[dict]:
        """
        流式执行工作流图。

        Args:
            input_data: 工作流输入数据
            config: 运行时配置

        Yields:
            每个节点的执行事件
        """
        ...

    async def get_state(self, thread_id: str) -> Optional[dict]:
        """
        获取指定会话的当前执行状态。

        Args:
            thread_id: 会话标识

        Returns:
            当前状态 dict，或 None（若会话不存在）
        """
        ...

    async def close(self) -> None:
        """关闭图资源（checkpointer 连接等）。"""
        ...
