"""
统一异常定义
----------
定义应用的异常层次结构，支持标准化的错误码和 HTTP 状态码映射。
"""
from typing import Optional


class AppException(Exception):
    """
    应用基础异常。

    所有业务异常应继承此类。
    """
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, detail: str = "", status_code: Optional[int] = None):
        self.detail = detail or self.__doc__ or ""
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.detail)


# ------------------------------------------------------------------
# 客户端错误 (4xx)
# ------------------------------------------------------------------

class ValidationError(AppException):
    """请求参数校验失败。"""
    status_code = 400
    error_code = "VALIDATION_ERROR"


class AuthenticationError(AppException):
    """认证失败。"""
    status_code = 401
    error_code = "AUTHENTICATION_ERROR"


class AuthorizationError(AppException):
    """权限不足。"""
    status_code = 403
    error_code = "AUTHORIZATION_ERROR"


class NotFoundError(AppException):
    """资源不存在。"""
    status_code = 404
    error_code = "NOT_FOUND"


class RateLimitError(AppException):
    """请求频率超限。"""
    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"


# ------------------------------------------------------------------
# 服务端错误 (5xx)
# ------------------------------------------------------------------

class WorkflowError(AppException):
    """工作流执行错误。"""
    status_code = 500
    error_code = "WORKFLOW_ERROR"


class ModelError(AppException):
    """模型调用错误。"""
    status_code = 502
    error_code = "MODEL_ERROR"


class InfrastructureError(AppException):
    """基础设施错误（数据库/缓存/队列不可用）。"""
    status_code = 503
    error_code = "INFRASTRUCTURE_ERROR"


class ConfigurationError(AppException):
    """配置错误。"""
    status_code = 500
    error_code = "CONFIGURATION_ERROR"
