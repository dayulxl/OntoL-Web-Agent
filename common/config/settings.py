"""
配置管理（基于 Pydantic Settings）
-------------------------------
支持从环境变量和 .env 文件加载配置，所有敏感信息通过环境变量注入。
"""
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    应用配置。

    所有字段可通过同名环境变量（如 POSTGRES_URI、REDIS_URI）覆盖。
    敏感信息（API Key 等）不设默认值，必须通过环境变量提供。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # 应用
    # ------------------------------------------------------------------
    debug: bool = False
    cors_origins: list[str] = ["*"]

    # ------------------------------------------------------------------
    # 模型
    # ------------------------------------------------------------------
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    custom_llm_base_url: Optional[str] = None
    custom_llm_api_key: Optional[str] = None

    # ------------------------------------------------------------------
    # Postgres (可选)
    # ------------------------------------------------------------------
    postgres_uri: str = "postgresql://localhost:5432/langgraph"

    # ------------------------------------------------------------------
    # 限流
    # ------------------------------------------------------------------
    rate_limit_per_minute: int = 60

    # ------------------------------------------------------------------
    # 知识图谱推理机
    # ------------------------------------------------------------------
    kg_server_url: str = "http://192.168.56.1:8085"

    # ------------------------------------------------------------------
    # Neo4j
    # ------------------------------------------------------------------
    neo4j_uri: str = "neo4j://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: Optional[str] = "12345678"

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------
    log_level: str = "INFO"


@lru_cache()
def get_settings() -> Settings:
    """获取全局配置单例（线程安全）。"""
    return Settings()
