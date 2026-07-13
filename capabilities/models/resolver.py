"""
LLM 模型解析器 — 共享模块
------------------------
/chat、/upload 等所有需要解析 LLM 的模块统一通过此接口获取模型实例。

优先级：
  1. ontol_llm_config 表（DB 配置，由 /llm-config 页面管理）
  2. models.yaml 兜底

调用方式:
    from capabilities.models.resolver import resolve_llm
    llm_iface = resolve_llm(config_id)   # config_id = ontol_llm_config.id
    llm = await llm_iface.get_llm()
"""

import sqlite3
from pathlib import Path
from typing import Optional

from capabilities.models.factory import ModelFactory
from capabilities.models.interfaces import ModelInterface


_DB_PATH = Path("infrastructure/db/ontol.db")


def resolve_llm(config_id: str = "") -> ModelInterface:
    """
    根据 LLM 配置 ID 解析模型实例。

    Args:
        config_id: ontol_llm_config 表中的配置主键。为空时走 models.yaml 默认。

    Returns:
        ModelInterface 实例，调用方通过 await iface.get_llm() 获取 LangChain LLM。

    Raises:
        ValueError:   config_id 在 DB 中不存在。
        RuntimeError:  DB 不可用且 config_id 非空时。
    """
    factory = ModelFactory()

    if not config_id:
        # 无配置 → models.yaml 默认
        return factory.create_llm("")

    if not _DB_PATH.exists():
        raise RuntimeError("数据库未就绪：ontol.db 不存在，无法解析 LLM 配置")

    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM ontol_llm_config WHERE id=? AND delete_flag='0'",
        (config_id,),
    ).fetchone()
    conn.close()

    if not row:
        raise ValueError(f"LLM 配置 '{config_id}' 不存在或已被删除")

    return factory.create_llm_from_config(
        base_url=row["llm_url"] or "",
        api_key=row["llm_key"] or "",
        model_name=row["llm_model"] or row["name"],
    )
