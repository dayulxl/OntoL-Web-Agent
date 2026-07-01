"""
Postgres 连接池管理
-----------------
基于 asyncpg 的连接池，支持健康检查和优雅关闭。
"""
from typing import Optional

import asyncpg
from asyncpg import Pool


# 全局连接池实例
_pool: Optional[Pool] = None


async def create_pool(dsn: str, min_size: int = 5, max_size: int = 20) -> Pool:
    """
    创建异步 Postgres 连接池。

    Args:
        dsn: 连接字符串（如 postgresql://user:pass@host:5432/db）。
        min_size: 最小连接数。
        max_size: 最大连接数。
    """
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=min_size,
        max_size=max_size,
    )
    return _pool


async def get_pool() -> Pool:
    """获取全局连接池。"""
    global _pool
    if _pool is None:
        raise RuntimeError("Postgres pool not initialized. Call create_pool() first.")
    return _pool


async def check_postgres() -> bool:
    """检查 Postgres 连通性。"""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:
        return False


async def close_pool() -> None:
    """关闭连接池。"""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def run_migrations() -> list[str]:
    """
    按序执行 infrastructure/db/migrations/ 目录下的所有 .sql 文件。

    每个迁移文件只在首次运行时执行（幂等 — 依赖 SQL 自身的 IF NOT EXISTS）。

    Returns:
        已执行的迁移文件名列表。
    """
    from pathlib import Path

    migrations_dir = Path(__file__).parent / "migrations"
    if not migrations_dir.is_dir():
        return []

    sql_files = sorted(migrations_dir.glob("*.sql"))
    if not sql_files:
        return []

    pool = await get_pool()
    executed: list[str] = []

    async with pool.acquire() as conn:
        for sql_file in sql_files:
            sql = sql_file.read_text(encoding="utf-8")
            await conn.execute(sql)
            executed.append(sql_file.name)

    return executed
