"""
状态管理器
--------
对接 Postgres checkpoint，提供状态的增删查改操作。
"""
from typing import Optional

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from orchestrator.state.schema import GraphState


class StateManager:
    """
    图状态管理器。

    封装 AsyncPostgresSaver，提供更高层次的状态查询和管理接口。
    """

    def __init__(self, checkpointer: AsyncPostgresSaver):
        self._checkpointer = checkpointer

    async def get(self, thread_id: str) -> Optional[dict]:
        """获取指定线程的最新状态。"""
        config = {"configurable": {"thread_id": thread_id}}
        state = await self._checkpointer.aget(config)
        return state if state else None

    async def list_threads(self, limit: int = 50, offset: int = 0) -> list:
        """列出最近的线程（需要配合 Postgres 查询视图实现）。"""
        # LangGraph checkpoint 的表结构: checkpoints, checkpoint_writes, checkpoint_blobs
        # 可通过直接查询 checkpoints 表获取线程列表
        raise NotImplementedError("需通过 Postgres 直接查询 checkpoint 表实现")

    async def delete(self, thread_id: str) -> None:
        """删除指定线程的所有 checkpoint 数据。"""
        # 通过 Postgres 删除对应 thread_id 的记录
        raise NotImplementedError("需通过 Postgres DELETE 操作实现")

    async def list_checkpoints(self, thread_id: str) -> list:
        """列出指定线程的所有 checkpoint 版本。"""
        config = {"configurable": {"thread_id": thread_id}}
        checkpoints = []
        async for checkpoint in self._checkpointer.alist(config):
            checkpoints.append(checkpoint)
        return checkpoints
