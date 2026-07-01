"""
日志中间件
--------
记录每个请求的耗时、状态码、trace_id 等结构化信息。
"""
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from common.utils.logger import get_logger
from gateway.middleware.auth import request_context

logger = get_logger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """记录请求日志的中间件。"""

    async def dispatch(self, request: Request, call_next):
        ctx = request_context.get()
        trace_id = ctx.get("trace_id", "-")
        user_id = ctx.get("user_id", "-")

        start_time = time.perf_counter()

        response = await call_next(request)

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        logger.info(
            "request completed",
            extra={
                "trace_id": trace_id,
                "user_id": user_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "elapsed_ms": round(elapsed_ms, 2),
            },
        )

        return response
