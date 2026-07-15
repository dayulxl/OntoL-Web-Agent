"""
本体模型 PostgreSQL Repository
-------------------------------
ontol_model / ontol_model_attr 两张表的数据访问层。
继承 BaseRepository，复用通用 CRUD，仅保留领域特有查询方法。

使用方式:
    from infrastructure.db.postgres import get_pool
    from infrastructure.db.ontology_repo import OntologyRepo

    pool = await get_pool()
    repo = OntologyRepo(pool)
    models = await repo.get_tree()
"""

from datetime import datetime
from typing import Optional

from asyncpg import Pool

from infrastructure.db.base_repo import BaseRepository


class OntologyRepo:
    """
    ontol_model + ontol_model_attr 的数据访问层。

    内部使用两个 BaseRepository 实例:
        - model_repo  → ontol_model (软删除, 自动时间戳)
        - attr_repo   → ontol_model_attr (软删除, 自动时间戳)

    所有查询以逻辑删除过滤（delete_flag='0'）为基础。
    """

    def __init__(self, pool: Pool):
        self._pool = pool
        self.model = BaseRepository(pool, "ontol_model", pk="id", soft_delete=True, auto_timestamps=True)
        self.attr = BaseRepository(pool, "ontol_model_attr", pk="id", soft_delete=True, auto_timestamps=False)

    # ==================================================================
    # 树形查询 (递归 CTE)
    # ==================================================================

    async def get_tree(self, root_id: Optional[str] = None) -> list[dict]:
        """递归 CTE 获取完整树。root_id=None 从根节点开始。"""
        async with self._pool.acquire() as conn:
            if root_id:
                rows = await conn.fetch(
                    """
                    WITH RECURSIVE tree AS (
                        SELECT m.*, 0 AS depth
                        FROM ontol_model m
                        WHERE m.id = $1 AND m.delete_flag = '0'
                        UNION ALL
                        SELECT m.*, t.depth + 1
                        FROM ontol_model m
                        INNER JOIN tree t ON m.ontol_parent_id = t.id
                        WHERE m.delete_flag = '0'
                    )
                    SELECT * FROM tree ORDER BY depth, ontol_data_type, name
                    """,
                    root_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    WITH RECURSIVE tree AS (
                        SELECT m.*, 0 AS depth
                        FROM ontol_model m
                        WHERE m.ontol_parent_id IS NULL AND m.delete_flag = '0'
                        UNION ALL
                        SELECT m.*, t.depth + 1
                        FROM ontol_model m
                        INNER JOIN tree t ON m.ontol_parent_id = t.id
                        WHERE m.delete_flag = '0'
                    )
                    SELECT * FROM tree ORDER BY depth, ontol_data_type, name
                    """
                )
            return [dict(r) for r in rows]

    async def get_children(self, parent_id: str) -> list[dict]:
        """获取直接子节点。"""
        return await self.model.list_rows(where={"ontol_parent_id": parent_id}, order_by="ontol_data_type, name")

    # ==================================================================
    # 模型 + 属性 复合查询
    # ==================================================================

    async def get_model_with_attrs(self, model_id: str) -> Optional[dict]:
        """获取本体模型及其所有属性字段（一次返回）。"""
        model = await self.model.get_by_id(model_id)
        if not model:
            return None
        attrs = await self.attr.list_rows(where={"ontol_model_id": model_id}, order_by="attr_is_system DESC, attr_order, code")
        model["attributes"] = attrs
        return model

    async def get_full_tree_with_attrs(self, root_id: Optional[str] = None) -> list[dict]:
        """获取完整树，每个节点附带属性字段。"""
        tree = await self.get_tree(root_id)
        # 批量获取所有 model 的属性
        model_ids = [node["id"] for node in tree]
        if not model_ids:
            return tree

        async with self._pool.acquire() as conn:
            # 用 IN (?, ?, ...) 替代 PostgreSQL 的 ANY($1)，兼容 SQLite
            placeholders = ", ".join(["?" for _ in model_ids])
            rows = await conn.fetch(
                f"""
                SELECT * FROM ontol_model_attr
                WHERE ontol_model_id IN ({placeholders}) AND delete_flag = '0'
                ORDER BY attr_is_system DESC, attr_order, code
                """,
                *model_ids,
            )
        attrs = [dict(r) for r in rows]
        attr_map: dict[str, list] = {}
        for a in attrs:
            attr_map.setdefault(a["ontol_model_id"], []).append(a)

        for node in tree:
            node["attributes"] = attr_map.get(node["id"], [])
        return tree

    async def get_attrs_by_model(self, model_id: str, *, is_system: Optional[str] = None) -> list[dict]:
        """获取模型属性列表。"""
        where = {"ontol_model_id": model_id}
        if is_system:
            where["attr_is_system"] = is_system
        return await self.attr.list_rows(where=where, order_by="attr_is_system DESC, attr_order, code")

    # ==================================================================
    # 搜索
    # ==================================================================

    async def search_models(self, keyword: str, limit: int = 50) -> list[dict]:
        """按名称/描述模糊搜索本体模型。"""
        return await self.model.search(
            keyword,
            columns=["name", "ontol_model_desc"],
            limit=limit,
        )

    # ==================================================================
    # 统计
    # ==================================================================

    async def get_stats(self) -> dict:
        """获取全局统计：本体模型 + 词典 + 场景。"""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    (SELECT count(*) FROM ontol_model WHERE delete_flag='0')        AS model_count,
                    (SELECT count(*) FROM ontol_model_attr WHERE delete_flag='0')    AS attr_count,
                    (SELECT count(*) FROM ontol_model_scene WHERE delete_flag='0')   AS scene_count,
                    (SELECT count(*) FROM ontol_scene_prompt WHERE delete_flag='0')  AS prompt_count,
                    (SELECT count(*) FROM ontol_scene_dictionary WHERE delete_flag='0') AS dict_count,
                    (SELECT count(*) FROM ontol_dictionary_type WHERE delete_flag='0')  AS dict_type_count,
                    (SELECT count(*) FROM ontol_scene_dictionary_relation WHERE delete_flag='0') AS dict_rel_count
                """
            )
            return dict(row) if row else {
                "model_count": 0, "attr_count": 0, "scene_count": 0,
                "prompt_count": 0, "dict_count": 0, "dict_type_count": 0, "dict_rel_count": 0,
            }


# =========================================================================
# [FEAT] SQLite 同步写操作 — 批量导入模型 & 字段（不走 asyncpg，直接写 SQLite）
# =========================================================================

import sqlite3 as _sqlite3
from business.tool.uuid_gen import new_id
from pathlib import Path as _Path
from datetime import datetime as _datetime

_SQLITE_PATH = str(_Path(__file__).parent / "ontol.db")


def _now() -> str:
    return _datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def batch_insert_models(
    models: list[dict],
    table: str = "ontol_model",
    parent_col: str = "ontol_parent_id",
    desc_col: str = "ontol_model_desc",
) -> int:
    """批量插入本体模型 — service 传对象，DB 层拼 SQL 执行。"""
    conn = _sqlite3.connect(_SQLITE_PATH)
    now = _now()
    created = 0
    try:
        for m in models:
            rid = m.get("id") or new_id()
            conn.execute(
                f"INSERT INTO [{table}] "
                f"(id, name, code, {parent_col}, ontol_data_type, {desc_col}, "
                f" ontol_model_status, create_time, delete_flag) "
                f"VALUES (?,?,?,?,?,?,?,?,?)",
                (rid, m["name"], m["code"], m.get("parent_id"),
                 m.get("type_code", ""), m.get("desc", ""), "0", now, "0"),
            )
            created += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return created


def list_existing_codes(table: str = "ontol_model") -> set[str]:
    """查询表中已有编码集合 — 用于导入前查重。"""
    conn = _sqlite3.connect(_SQLITE_PATH)
    try:
        rows = conn.execute(
            f"SELECT code FROM [{table}] WHERE delete_flag='0'"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def batch_insert_attrs(attrs: list[dict], model_id: str, attr_mapping: str = "00") -> int:
    """批量插入字段 — service 传对象，DB 层拼 SQL 执行。"""
    conn = _sqlite3.connect(_SQLITE_PATH)
    now = _now()
    created = 0
    try:
        for a in attrs:
            rid = new_id()
            conn.execute(
                "INSERT INTO ontol_model_attr "
                "(id, ontol_model_id, name, code, attr_data_type, attr_length, "
                " attr_required, attr_is_only, attr_default_value, attr_desc, "
                " attr_is_system, attr_mapping, create_time, delete_flag) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'0')",
                (rid, model_id, a.get("name", a.get("code", "")), a["code"],
                 a.get("data_type", "VARCHAR"), a.get("length", ""),
                 a.get("required", "0"), a.get("is_only", "0"),
                 a.get("default", ""), a.get("desc", ""), "0", attr_mapping, now),
            )
            created += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return created


def update_attr_by_code(model_id: str, code: str, updates: dict) -> bool:
    """按 model_id + code 更新字段。"""
    field_map = {
        "name": "name", "data_type": "attr_data_type", "length": "attr_length",
        "required": "attr_required", "is_only": "attr_is_only",
        "default": "attr_default_value", "desc": "attr_desc",
    }
    sets, vals = [], []
    for ek, col in field_map.items():
        if ek in updates and updates[ek]:
            sets.append(f"{col}=?")
            vals.append(updates[ek])
    if not sets:
        return False
    vals.extend([model_id, code])
    conn = _sqlite3.connect(_SQLITE_PATH)
    try:
        conn.execute(
            f"UPDATE ontol_model_attr SET {', '.join(sets)} "
            f"WHERE ontol_model_id=? AND code=?", tuple(vals))
        conn.commit()
        return True
    finally:
        conn.close()


def delete_attr_by_code(model_id: str, code: str) -> bool:
    """按 model_id + code 删除字段。"""
    conn = _sqlite3.connect(_SQLITE_PATH)
    try:
        conn.execute(
            "DELETE FROM ontol_model_attr WHERE ontol_model_id=? AND code=? AND attr_is_system!='1'",
            (model_id, code))
        conn.commit()
        return True
    finally:
        conn.close()
    return True


