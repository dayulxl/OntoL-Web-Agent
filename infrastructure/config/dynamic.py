"""
动态配置热更新
------------
从 Redis 读取动态配置，支持不重启应用即可更新限流阈值、模型选择等参数。

注意：此类放在 infrastructure/ 而非 common/，因为它需要直接访问 Redis 客户端。
common/config/ 只保留纯 Pydantic Settings（无外部依赖）。
"""
from typing import Any, Optional

from infrastructure.cache.redis import cache_get, cache_set
from common.config.settings import get_settings


class DynamicConfig:
    """
    动态配置管理器。

    配置优先级: 动态配置 (Redis) > 环境变量 > 默认值

    使用方式:
        dynamic = DynamicConfig()
        value = await dynamic.get("rate_limit_per_minute", default=60)
    """

    def __init__(self):
        self._cache: dict[str, Any] = {}

    async def get(self, key: str, default: Any = None) -> Any:
        """
        获取动态配置值。

        Args:
            key: 配置键名。
            default: 默认值（若 Redis 中不存在）。
        """
        if key in self._cache:
            return self._cache[key]

        try:
            value = await cache_get(f"config:{key}")
            if value is not None:
                import json
                parsed = json.loads(value)
                self._cache[key] = parsed
                return parsed
        except Exception:
            pass

        settings = get_settings()
        env_value = getattr(settings, key, default)
        return env_value if env_value is not None else default

    async def set(self, key: str, value: Any) -> None:
        """写入动态配置（持久化到 Redis）。"""
        import json
        await cache_set(f"config:{key}", json.dumps(value), ttl=0)
        self._cache[key] = value

    async def refresh(self) -> None:
        """清空本地缓存，下次访问时从 Redis 重新加载。"""
        self._cache.clear()
