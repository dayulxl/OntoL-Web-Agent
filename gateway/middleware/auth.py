"""
鉴权中间件
--------
验证请求的 API Key / JWT Token，注入 user_id 到请求上下文中。
"""
import uuid
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from common.config.settings import get_settings

# 请求上下文变量
request_context: ContextVar[dict] = ContextVar("request_context", default={})


class AuthMiddleware(BaseHTTPMiddleware):
    """
    鉴权中间件。

    验证 `Authorization: Bearer <token>` 或 `X-API-Key: <key>` 头，
    将解析后的 user_id 和 trace_id 注入上下文变量。
    """

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()

        # 跳过健康检查端点
        if request.url.path in ("/health", "/ready", "/api/v1/health", "/api/v1/ready"):
            return await call_next(request)

        # 提取 trace_id（若无则生成）
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))

        # 鉴权验证
        user_id = "anonymous"
        auth_header = request.headers.get("Authorization", "")
        api_key = request.headers.get("X-API-Key", "")

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            user_id = await self._validate_jwt(token, settings)
        elif api_key:
            user_id = await self._validate_api_key(api_key, settings)

        # 注入上下文
        ctx = {"trace_id": trace_id, "user_id": user_id}
        token = request_context.set(ctx)

        try:
            response = await call_next(request)
            response.headers["X-Trace-ID"] = trace_id
            return response
        finally:
            request_context.reset(token)

    async def _validate_jwt(self, token: str, settings) -> str:
        """验证 JWT Token 并返回 user_id。"""
        # TODO: 实现 JWT 解码与校验逻辑
        return "user_from_jwt"

    async def _validate_api_key(self, api_key: str, settings) -> str:
        """验证 API Key 并返回 user_id。"""
        # TODO: 实现 API Key 校验逻辑
        return "user_from_api_key"
