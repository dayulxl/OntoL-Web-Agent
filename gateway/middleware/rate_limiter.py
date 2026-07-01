"""
限流中间件
--------
基于 Redis 滑动窗口实现请求频率限制。
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from common.config.settings import get_settings


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """
    滑动窗口限流中间件。

    默认限制：每用户每分钟 60 次请求（可通过配置覆盖）。
    """

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()

        # 跳过健康检查端点
        if request.url.path in ("/health", "/ready", "/api/v1/health", "/api/v1/ready"):
            return await call_next(request)

        # TODO: 实现 Redis 滑动窗口限流逻辑
        # key = f"ratelimit:{user_id}:{int(time.time() / 60)}"
        # if redis_client.incr(key) > settings.rate_limit_per_minute:
        #     return JSONResponse(status_code=429, content={"detail": "Too Many Requests"})

        return await call_next(request)
