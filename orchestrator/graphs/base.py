"""
基础图抽象类
-----------
所有业务工作流的基类，封装 StateGraph 构建、编译和执行逻辑。

此类实现 GraphExtension 协议，是产品层对外提供的默认实现。
业务图继承此类即可满足 GraphExtension 契约。
"""
from business.tool.uuid_gen import new_id
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from common.contracts import GraphExtension, GraphStateBase
from orchestrator.state.schema import GraphState


class BaseWorkflowGraph(GraphExtension, ABC):
    """
    工作流图基类 — 实现 GraphExtension 协议。

    子类需实现：
      - _build_graph(): 构建 StateGraph 实例
      - graph_name: 类属性，工作流唯一标识名

    使用方式:
        class MyWorkflow(BaseWorkflowGraph):
            graph_name = "my_workflow"

            def _build_graph(self) -> StateGraph:
                workflow = StateGraph(MyState)
                workflow.add_node("step1", self.step1)
                workflow.add_edge(START, "step1")
                workflow.add_conditional_edges("step1", self.route)
                workflow.add_edge("step2", END)
                return workflow
    """

    graph_name: str = "base"

    def __init__(self, postgres_uri: str):
        self.postgres_uri = postgres_uri
        self.checkpointer: Optional[PostgresSaver] = None
        self._graph: Optional[StateGraph] = None
        self._app = None

    # ------------------------------------------------------------------
    # GraphExtension 协议实现: 初始化
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """初始化 checkpointer 并编译图。"""
        self.checkpointer = await self._create_checkpointer()
        self._graph = self._build_graph()
        self._app = self._graph.compile(checkpointer=self.checkpointer)

    async def _create_checkpointer(self) -> AsyncPostgresSaver:
        """创建异步 Postgres Checkpoint 存储。"""
        checkpointer = AsyncPostgresSaver.from_conn_string(self.postgres_uri)
        await checkpointer.setup()
        return checkpointer

    # ------------------------------------------------------------------
    # 子类必须实现
    # ------------------------------------------------------------------

    @abstractmethod
    def _build_graph(self) -> StateGraph:
        """
        构建 StateGraph。

        定义节点、边和条件分支，返回尚未编译的 StateGraph 实例。
        """
        ...

    # ------------------------------------------------------------------
    # 节点路由 (可被子类覆盖)
    # ------------------------------------------------------------------

    async def _route_condition(
        self, state: GraphState
    ) -> str:
        """默认条件路由：根据 state 中的路由键决定下一步。"""
        next_step = state.get("next_node")
        if next_step:
            return next_step
        return END

    # ------------------------------------------------------------------
    # GraphExtension 协议实现: 执行
    # ------------------------------------------------------------------

    def _make_config(self, thread_id: Optional[str] = None, user_id: Optional[str] = None) -> dict:
        """构造 LangGraph 运行配置。"""
        return {
            "configurable": {
                "thread_id": thread_id or new_id(),
                "user_id": user_id or "system",
            }
        }

    async def run(self, input_data: dict, config: Optional[dict] = None) -> dict:
        """同步运行工作流，返回最终状态。"""
        if self._app is None:
            await self.initialize()

        thread_config = config or self._make_config()
        run_id = thread_config["configurable"]["thread_id"]

        result = await self._app.ainvoke(
            {"input": input_data, "data": input_data},
            thread_config,
        )

        return {
            "run_id": run_id,
            "status": "completed",
            "output": result,
        }

    async def stream(
        self, input_data: dict, config: Optional[dict] = None
    ) -> AsyncIterator[dict]:
        """流式运行工作流，逐步返回每个节点的输出。"""
        if self._app is None:
            await self.initialize()

        thread_config = config or self._make_config()

        async for event in self._app.astream_events(
            {"input": input_data, "data": input_data},
            thread_config,
            version="v2",
        ):
            yield event

    async def get_state(self, thread_id: str) -> Optional[dict]:
        """获取指定线程的当前状态。"""
        if self._app is None:
            await self.initialize()

        config = self._make_config(thread_id=thread_id)
        state = await self._app.aget_state(config)
        return state.values if state else None

    # ------------------------------------------------------------------
    # GraphExtension 协议实现: 生命周期
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """关闭 checkpointer 连接。"""
        if self.checkpointer:
            await self.checkpointer.close()
