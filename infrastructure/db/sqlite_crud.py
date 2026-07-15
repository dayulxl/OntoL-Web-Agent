"""
SQLite 通用 CRUD 基类 — 对象↔SQL 双向转换
==========================================
所有 SQLite 表的写操作必须经过此类。子类只指定表名/主键，不写 SQL。

    使用方式:
        from infrastructure.db.sqlite_crud import SqliteCrud

        repo = SqliteCrud("ontol_llm_config", pk="id", soft_delete=True)

        # 写
        repo.insert({"id":"x","name":"test"})         # dict → INSERT
        repo.update("x", {"name":"new"})              # dict → UPDATE
        repo.delete("x")                               # 软删除
        repo.delete("x", soft=False)                  # 物理删除

        # 读
        row  = repo.get_by_id("x")                    # SELECT → dict
        rows = repo.list_rows(where={"type":"gpt"})   # SELECT → list[dict]
        rows = repo.list_rows(limit=10, offset=0)
        cnt  = repo.count()
"""
import sqlite3 as _sqlite3
from pathlib import Path
from typing import Any, Optional

_DB_PATH = str(Path(__file__).parent / "ontol.db")


class SqliteCrud:
    """通用 SQLite CRUD — dict 对象 → 参数化 SQL → 执行 → 返回 dict/None。

    不写死表名/列名，不写业务逻辑，不做加解密。
    """

    def __init__(self, table: str, *, pk: str = "id", soft_delete: bool = True):
        self._table = table
        self._pk = pk
        self._soft_delete = soft_delete

    # ═══════════════════════════════════════════════
    # 内部
    # ═══════════════════════════════════════════════

    def _connect(self):
        conn = _sqlite3.connect(_DB_PATH)
        conn.row_factory = _sqlite3.Row
        return conn

    def _where(self, where: Optional[dict] = None, include_deleted: bool = False) -> tuple[str, tuple]:
        conditions, params = [], []
        if self._soft_delete and not include_deleted:
            conditions.append("delete_flag='0'")
        if where:
            for col, val in where.items():
                conditions.append(f"{col}=?")
                params.append(val)
        return (" WHERE " + " AND ".join(conditions), tuple(params)) if conditions else ("", ())

    # ═══════════════════════════════════════════════
    # 写 — INSERT
    # ═══════════════════════════════════════════════

    def insert(self, data: dict) -> dict:
        cols = list(data.keys())
        vals = tuple(data.values())
        ph = ", ".join("?" for _ in cols)
        sql = f"INSERT INTO [{self._table}] ({', '.join(cols)}) VALUES ({ph})"
        conn = self._connect()
        try:
            conn.execute(sql, vals)
            conn.commit()
            return self.get_by_id(data[self._pk])
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ═══════════════════════════════════════════════
    # 写 — UPDATE
    # ═══════════════════════════════════════════════

    def update(self, pk_val: Any, data: dict) -> Optional[dict]:
        if not data:
            return self.get_by_id(pk_val)
        sets = [f"{col}=?" for col in data]
        vals = list(data.values()) + [pk_val]
        sql = f"UPDATE [{self._table}] SET {', '.join(sets)} WHERE {self._pk}=?"
        conn = self._connect()
        try:
            conn.execute(sql, vals)
            conn.commit()
            return self.get_by_id(pk_val)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ═══════════════════════════════════════════════
    # 写 — DELETE
    # ═══════════════════════════════════════════════

    def delete(self, pk_val: Any, soft: bool = True) -> bool:
        conn = self._connect()
        try:
            if soft and self._soft_delete:
                conn.execute(f"UPDATE [{self._table}] SET delete_flag='1' WHERE {self._pk}=?", (pk_val,))
            else:
                conn.execute(f"DELETE FROM [{self._table}] WHERE {self._pk}=?", (pk_val,))
            conn.commit()
            return True
        finally:
            conn.close()

    def delete_where(self, where: dict, soft: bool = True) -> int:
        cond, params = self._where(where, include_deleted=True)
        conn = self._connect()
        try:
            if soft and self._soft_delete:
                conn.execute(f"UPDATE [{self._table}] SET delete_flag='1'{cond}", params)
            else:
                conn.execute(f"DELETE FROM [{self._table}]{cond}", params)
            conn.commit()
            return conn.total_changes
        finally:
            conn.close()

    # ═══════════════════════════════════════════════
    # 读
    # ═══════════════════════════════════════════════

    def get_by_id(self, pk_val: Any) -> Optional[dict]:
        sql = f"SELECT * FROM [{self._table}] WHERE {self._pk}=? AND delete_flag='0'"
        conn = self._connect()
        try:
            row = conn.execute(sql, (pk_val,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_rows(
        self,
        where: Optional[dict] = None,
        order_by: Optional[str] = None,
        order_desc: bool = True,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        cond, params = self._where(where)
        order = f" ORDER BY {order_by} {'DESC' if order_desc else 'ASC'}" if order_by else ""
        sql = f"SELECT * FROM [{self._table}]{cond}{order} LIMIT ? OFFSET ?"
        conn = self._connect()
        try:
            rows = conn.execute(sql, params + (limit, offset)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def count(self, where: Optional[dict] = None) -> int:
        cond, params = self._where(where)
        sql = f"SELECT COUNT(*) FROM [{self._table}]{cond}"
        conn = self._connect()
        try:
            return conn.execute(sql, params).fetchone()[0]
        finally:
            conn.close()

    def exists(self, pk_val: Any) -> bool:
        return self.get_by_id(pk_val) is not None

    def execute_raw(self, sql: str, *params: Any) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
