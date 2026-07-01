"""
图执行器
-------
通过 business.REGISTRY 显式加载业务域工作流图，调度执行（同步/流式），
管理运行中的任务。

不再使用 pkgutil 自动扫描 business/ 包 —— 业务域必须显式注册。
"""
from typing import Any, AsyncIterator, Optional

from common.contracts import GraphExtension


class GraphExecutor:
    """
    图执行器。

    从 business.REGISTRY 加载显式注册的工作流图类，负责：
      - 工作流加载与注册
      - 同步执行 (run)
      - 流式执行 (stream)
      - 状态查询 (get_status)
      - 任务取消 (cancel)

    使用方式:
        executor = GraphExecutor(postgres_uri="...")
        await executor.initialize()
        result = await executor.run("route_planning", {"query": "..."})
    """

    def __init__(self, postgres_uri: str):
        self.postgres_uri = postgres_uri
        self._graphs: dict[str, GraphExtension] = {}
        self._running: dict[str, dict] = {}  # run_id → metadata

    # ------------------------------------------------------------------
    # 初始化与注册
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """从 business.REGISTRY 加载并初始化所有工作流图。"""
        graph_classes = self._load_registry()
        for graph_cls in graph_classes:
            self._register(graph_cls(self.postgres_uri))

        for graph in self._graphs.values():
            await graph.initialize()

    def _load_registry(self) -> list[type]:
        """
        从 business.REGISTRY 加载显式注册的业务图类。

        业务域通过在 business/__init__.py 的 REGISTRY 列表中
        声明自己的图类来注册，而不是被 pkgutil 自动发现。

        Returns:
            图类列表（每个都满足 GraphExtension 协议）
        """
        try:
            from business import REGISTRY
        except ImportError:
            return []

        if not isinstance(REGISTRY, (list, tuple)):
            raise TypeError(
                "business.REGISTRY must be a list or tuple of graph classes"
            )

        for graph_cls in REGISTRY:
            if not isinstance(graph_cls, type):
                raise TypeError(
                    f"REGISTRY entry {graph_cls!r} is not a class"
                )
            if not issubclass(graph_cls, GraphExtension):
                raise TypeError(
                    f"Registered class '{graph_cls.__name__}' does not satisfy "
                    f"GraphExtension protocol. Missing: graph_name, initialize, "
                    f"run, stream, get_state, close."
                )

        return list(REGISTRY)

    def _register(self, graph: GraphExtension) -> None:
        """注册一个工作流图实例。"""
        self._graphs[graph.graph_name] = graph

    def register_graph(self, graph: GraphExtension) -> None:
        """外部注册自定义工作流图实例。"""
        if not isinstance(graph, GraphExtension):
            raise TypeError(
                f"'{type(graph).__name__}' does not satisfy GraphExtension protocol"
            )
        self._graphs[graph.graph_name] = graph

    def get_graph(self, name: str) -> GraphExtension:
        """根据名称获取工作流图。"""
        graph = self._graphs.get(name)
        if graph is None:
            raise ValueError(
                f"Workflow '{name}' not found. Available: {list(self._graphs.keys())}"
            )
        return graph

    # ------------------------------------------------------------------
    # 执行接口
    # ------------------------------------------------------------------

    async def run(
        self,
        workflow_name: str,
        input_data: dict,
        config: Optional[dict] = None,
    ) -> dict:
        """同步执行工作流。"""
        graph = self.get_graph(workflow_name)
        result = await graph.run(input_data, config)

        # 记录运行元数据
        self._running[result["run_id"]] = {
            "workflow": workflow_name,
            "status": "completed",
            "started_at": None,  # 可从 tracing 中获取
        }

        return result

    async def stream(
        self,
        workflow_name: str,
        input_data: dict,
        config: Optional[dict] = None,
    ) -> AsyncIterator[dict]:
        """流式执行工作流。"""
        graph = self.get_graph(workflow_name)
        async for event in graph.stream(input_data, config):
            yield event

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    async def get_status(self, run_id: str) -> Optional[dict]:
        """获取运行状态。"""
        return self._running.get(run_id)

    async def cancel(self, run_id: str) -> bool:
        """取消运行中的任务。"""
        meta = self._running.get(run_id)
        if meta and meta.get("status") == "running":
            # TODO: 实现中断逻辑（LangGraph 原生支持 interrupt）
            meta["status"] = "cancelled"
            return True
        return False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """关闭所有图的连接。"""
        for graph in self._graphs.values():
            await graph.close()
