"""
Memgraph 驱动管理（Neo4j 兼容协议）
----------------------------------
Memgraph 通过 Bolt 协议与 neo4j Python 驱动兼容。
本模块封装连接池管理、健康检查和优雅关闭。
Neo4j/Memgraph Driver 本身即为连接池，无需额外池化层。
"""
from typing import Optional

from neo4j import AsyncGraphDatabase
from neo4j._async.driver import AsyncDriver

from common.exceptions.base import InfrastructureError


# 全局驱动实例 (本身就是连接池)
_driver: Optional[AsyncDriver] = None


def _normalize_uri(uri: str) -> str:
    """
    标准化数据库 URI，将 memgraph:// 替换为 bolt://。
    Memgraph 通过 Bolt 协议通信，neo4j 驱动不识别 memgraph:// scheme。
    """
    if uri.startswith("memgraph://"):
        return "bolt://" + uri[len("memgraph://"):]
    if uri.startswith("memgraph+s://"):
        return "bolt+s://" + uri[len("memgraph+s://"):]
    if uri.startswith("memgraph+ssc://"):
        return "bolt+ssc://" + uri[len("memgraph+ssc://"):]
    return uri


async def create_driver(uri: str, user: str, password: str) -> AsyncDriver:
    """
    创建 Memgraph/Neo4j 异步驱动（内置连接池）。

    Memgraph 默认无认证，当 user 和 password 均为空字符串时跳过认证。

    Args:
        uri: 数据库连接地址（支持 bolt:// 或 memgraph://，后者自动转换为 bolt://）。
        user: 用户名（Memgraph 默认为空）。
        password: 密码（Memgraph 默认为空）。

    Returns:
        AsyncDriver 实例。
    """
    global _driver

    uri = _normalize_uri(uri)

    # Memgraph 默认无认证：用户名和密码均为空时跳过 auth
    if not user and not password:
        _driver = AsyncGraphDatabase.driver(
            uri,
            max_connection_lifetime=3600,
            max_connection_pool_size=50,
            connection_acquisition_timeout=30,
        )
    else:
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
    获取全局图数据库驱动。

    Raises:
        InfrastructureError: 驱动未初始化。
    """
    global _driver
    if _driver is None:
        raise InfrastructureError("Graph DB driver not initialized. Call create_driver() first.")
    return _driver


async def check_graph_db() -> bool:
    """检查图数据库连通性。"""
    try:
        driver = await get_driver()
        async with driver.session() as session:
            await session.run("RETURN 1")
        return True
    except Exception:
        return False


async def close_driver() -> None:
    """关闭图数据库驱动。"""
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
