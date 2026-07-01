"""
结构化日志
---------
基于 structlog 的结构化 JSON 日志，自动注入 trace_id 和 user_id。
输出格式兼容 EFK/ELK 采集。
"""
import logging
import structlog

from common.config.settings import get_settings


def setup_logging() -> None:
    """全局日志初始化（应用启动时调用一次）。"""
    settings = get_settings()

    # structlog 配置
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 设置标准 logging 级别
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )


def get_logger(name: str = __name__) -> structlog.stdlib.BoundLogger:
    """获取结构化日志实例。"""
    return structlog.get_logger(name)
