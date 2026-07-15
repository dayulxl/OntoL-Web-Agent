"""
LLM 配置业务服务
===============
调用 infrastructure/db/llm_config_repo 做 SQL，本层负责 llm_key 加解密。
路由层调用本模块，不写业务逻辑。
"""
from __future__ import annotations

from typing import Any, Optional

from business.tool.uuid_gen import new_id
from business.tool.SecurityUtils import aes_encrypt, aes_decrypt
from infrastructure.db.llm_config_repo import (
    list_configs as _db_list,
    get_config as _db_get,
    create_config as _db_create,
    update_config as _db_update,
    delete_config as _db_delete,
)


def _decrypt_key(row: dict | None) -> dict | None:
    if row is None:
        return None
    key = (row.get("llm_key") or "").strip()
    if key:
        try:
            row["llm_key"] = aes_decrypt(key)
        except Exception:
            pass
    return row


def list_configs(type_config_id: str = "") -> list[dict[str, Any]]:
    return [_decrypt_key(r) for r in _db_list(type_config_id)]


def get_config(config_id: str) -> Optional[dict[str, Any]]:
    return _decrypt_key(_db_get(config_id))


def create_config(
    name: str,
    llm_type_config_id: str = "",
    llm_model: str = "",
    llm_url: str = "",
    llm_key: str = "",
    llm_description: str = "",
    config_id: str = "",
) -> dict[str, Any]:
    data = {
        "id": config_id.strip() or new_id(),
        "llm_type_config_id": llm_type_config_id or None,
        "name": name,
        "llm_model": llm_model or None,
        "llm_url": llm_url or "",
        "llm_key": aes_encrypt(llm_key) if llm_key.strip() else "",
        "llm_description": llm_description or "",
    }
    return _decrypt_key(_db_create(data))


def update_config(config_id: str, data: dict) -> Optional[dict[str, Any]]:
    filtered = {k: v for k, v in data.items() if v is not None}
    if "llm_key" in filtered and filtered["llm_key"].strip():
        filtered["llm_key"] = aes_encrypt(filtered["llm_key"].strip())
    return _decrypt_key(_db_update(config_id, filtered))


def delete_config(config_id: str, soft: bool = True) -> bool:
    return _db_delete(config_id, soft=soft)


def resolve_api_key(config_id: str) -> str:
    """Resolver 专用 — 从 DB 读 key 解密返回明文。"""
    row = _db_get(config_id)
    return _decrypt_key(row).get("llm_key", "") if row else ""
