"""
LLM 配置数据访问层 — 委托 SqliteCrud，不写 SQL
==============================================
"""
from infrastructure.db.sqlite_crud import SqliteCrud

_repo = SqliteCrud("ontol_llm_config", pk="id", soft_delete=True)


def list_configs(type_config_id: str = "") -> list[dict]:
    if type_config_id:
        return _repo.list_rows(where={"llm_type_config_id": type_config_id},
                               order_by="create_time")
    return _repo.list_rows(order_by="create_time")


def get_config(config_id: str) -> dict | None:
    return _repo.get_by_id(config_id)


def create_config(data: dict) -> dict:
    return _repo.insert(data)


def update_config(config_id: str, data: dict) -> dict | None:
    return _repo.update(config_id, data)


def delete_config(config_id: str, soft: bool = True) -> bool:
    return _repo.delete(config_id, soft=soft)
