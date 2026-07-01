"""
检查点持久化
-----------
封装 PostgresSaver 的初始化，处理 checkpoint 的 setup 和 teardown。
"""
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


async def create_checkpointer(postgres_uri: str) -> AsyncPostgresSaver:
    """
    创建并初始化异步 Postgres Checkpoint 存储。

    执行 LangGraph 所需的数据库表迁移 (setup)，
    返回可用于图编译的 AsyncPostgresSaver 实例。
    """
    checkpointer = AsyncPostgresSaver.from_conn_string(postgres_uri)
    await checkpointer.setup()
    return checkpointer


def create_checkpointer_sync(postgres_uri: str) -> PostgresSaver:
    """
    创建并初始化同步 Postgres Checkpoint 存储（用于非异步环境）。
    """
    checkpointer = PostgresSaver.from_conn_string(postgres_uri)
    checkpointer.setup()
    return checkpointer
