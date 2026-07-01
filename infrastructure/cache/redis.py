"""
Redis 客户端
-----------
提供异步 Redis 连接，支持缓存操作和 Pub/Sub 通信。
"""
from typing import Optional

import redis.asyncio as aioredis
from redis.asyncio import Redis


# 全局 Redis 客户端实例
_redis_client: Optional[Redis] = None


async def create_client(redis_url: str) -> Redis:
    """
    创建异步 Redis 客户端。

    Args:
        redis_url: Redis 连接 URL（如 redis://localhost:6379/0）。
    """
    global _redis_client
    _redis_client = aioredis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    return _redis_client


async def get_client() -> Redis:
    """获取全局 Redis 客户端。"""
    global _redis_client
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call create_client() first.")
    return _redis_client


async def check_redis() -> bool:
    """检查 Redis 连通性。"""
    try:
        client = await get_client()
        await client.ping()
        return True
    except Exception:
        return False


async def close_client() -> None:
    """关闭 Redis 客户端。"""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None


# ------------------------------------------------------------------
# 缓存操作便捷方法
# ------------------------------------------------------------------

async def cache_get(key: str) -> Optional[str]:
    """读取缓存。"""
    client = await get_client()
    return await client.get(key)


async def cache_set(key: str, value: str, ttl: int = 300) -> None:
    """
    写入缓存。

    Args:
        key: 缓存键。
        value: 缓存值。
        ttl: 过期时间（秒），默认 300s。
    """
    client = await get_client()
    await client.set(key, value, ex=ttl)


async def cache_delete(key: str) -> None:
    """删除缓存。"""
    client = await get_client()
    await client.delete(key)


# ------------------------------------------------------------------
# Pub/Sub 操作
# ------------------------------------------------------------------

async def publish(channel: str, message: str) -> None:
    """发布消息到 Redis 频道（用于集群内实例间通信）。"""
    client = await get_client()
    await client.publish(channel, message)


async def subscribe(channel: str):
    """订阅 Redis 频道。"""
    client = await get_client()
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    return pubsub
