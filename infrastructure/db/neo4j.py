"""
Neo4j 驱动管理
-------------
基于 neo4j 官方 Python 驱动的连接池封装，支持健康检查和优雅关闭。
Neo4j Driver 本身即为连接池，无需额外池化层。
"""
from typing import Optional

from neo4j import AsyncGraphDatabase
from neo4j._async.driver import AsyncDriver

from common.exceptions.base import InfrastructureError


# 全局驱动实例 (本身就是连接池)
_driver: Optional[AsyncDriver] = None


async def create_driver(uri: str, user: str, password: str) -> AsyncDriver:
    """
    创建 Neo4j 异步驱动（内置连接池）。

    Args:
        uri: Neo4j 连接地址（如 neo4j://127.0.0.1:7687）。
        user: 用户名。
        password: 密码。

    Returns:
        AsyncDriver 实例。
    """
    global _driver
    _driver = AsyncGraphDatabase.driver(
        uri,
        auth=(user, password),
        max_connection_lifetime=3600,
        max_connection_pool_size=50,
        connection_acquisition_timeout=30,
    )
    return _driver


async def get_driver() -> AsyncDriver:
    """
    获取全局 Neo4j 驱动。

    Raises:
        InfrastructureError: 驱动未初始化。
    """
    global _driver
    if _driver is None:
        raise InfrastructureError("Neo4j driver not initialized. Call create_driver() first.")
    return _driver


async def check_neo4j() -> bool:
    """检查 Neo4j 连通性。"""
    try:
        driver = await get_driver()
        async with driver.session() as session:
            await session.run("RETURN 1")
        return True
    except Exception:
        return False


async def close_driver() -> None:
    """关闭 Neo4j 驱动。"""
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
