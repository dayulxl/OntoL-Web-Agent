"""
PostgreSQL 通用 Repository 基类
-------------------------------
提供任意表的增删改查、分页、条件过滤、软删除、事务支持。
所有方法基于 asyncpg 连接池，完全异步。

使用方式:
    from infrastructure.db.base_repo import BaseRepository

    repo = BaseRepository(pool, "ontol_model")
    rows = await repo.list_rows(where={"ontol_model_type": "M_ENTITY"}, limit=50)

    # 继承使用
    class MyRepo(BaseRepository):
        def __init__(self, pool):
            super().__init__(pool, "my_table", pk="id", soft_delete=True)
"""

from datetime import datetime
from typing import Any, Optional, Union

from asyncpg import Pool, Connection


WhereValue = Union[str, int, float, bool, None]
WhereClause = dict[str, WhereValue]


class BaseRepository:
    """
    通用异步 CRUD 仓库。

    参数:
        pool:       asyncpg 连接池。
        table:      表名。
        pk:         主键列名 (默认 "id")。
        soft_delete: 是否启用逻辑删除 (delete_flag 列, 默认 False)。
        auto_timestamps: 是否自动管理 create_time / update_time (默认 True)。
    """

    def __init__(
        self,
        pool: Pool,
        table: str,
        *,
        pk: str = "id",
        soft_delete: bool = False,
        auto_timestamps: bool = True,
    ):
        self._pool = pool
        self._table = table
        self._pk = pk
        self._soft_delete = soft_delete
        self._auto_ts = auto_timestamps

    # ==================================================================
    # 内部工具
    # ==================================================================

    def _now(self) -> datetime:
        return datetime.utcnow()

    def _where_clause(
        self,
        where: Optional[WhereClause] = None,
        *,
        include_deleted: bool = False,
        params: Optional[list] = None,
    ) -> tuple[str, list]:
        """
        构建参数化 WHERE 子句。

        Args:
            where:           等值条件 {col: val}。
            include_deleted: 是否包含已软删除行。
            params:          已有的参数列表（复用 idx）。

        Returns:
            (" WHERE col1=$1 AND col2=$2 AND delete_flag='0'", [$1, $2])
        """
        if params is None:
            params = []

        conditions: list[str] = []
        idx = len(params) + 1

        if self._soft_delete and not include_deleted:
            conditions.append("delete_flag = '0'")

        if where:
            for col, val in where.items():
                if val is None:
                    conditions.append(f"{col} IS NULL")
                else:
                    conditions.append(f"{col} = ${idx}")
                    params.append(val)
                    idx += 1

        clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        return clause, params

    # ==================================================================
    # CREATE
    # ==================================================================

    async def insert(self, data: dict, *, conn: Optional[Connection] = None) -> dict:
        """
        插入一行，返回完整行。

        Args:
            data: 列名→值的字典。
            conn: 可选，事务连接。

        Returns:
            插入后的完整行 (dict)。
        """
        if self._auto_ts:
            data.setdefault("create_time", self._now())

        columns = list(data.keys())
        values = list(data.values())
        placeholder = ", ".join(f"${i+1}" for i in range(len(values)))

        query = f"""
            INSERT INTO {self._table} ({', '.join(columns)})
            VALUES ({placeholder})
            RETURNING *
        """

        if conn:
            row = await conn.fetchrow(query, *values)
        else:
            async with self._pool.acquire() as c:
                row = await c.fetchrow(query, *values)

        return dict(row)

    # ==================================================================
    # READ
    # ==================================================================

    async def get_by_id(
        self,
        pk_value: Any,
        *,
        include_deleted: bool = False,
        conn: Optional[Connection] = None,
    ) -> Optional[dict]:
        """按主键获取一行。"""
        where, params = self._where_clause(
            {self._pk: pk_value},
            include_deleted=include_deleted,
        )
        query = f"SELECT * FROM {self._table}{where} LIMIT 1"

        if conn:
            row = await conn.fetchrow(query, *params)
        else:
            async with self._pool.acquire() as c:
                row = await c.fetchrow(query, *params)

        return dict(row) if row else None

    async def list_rows(
        self,
        *,
        where: Optional[WhereClause] = None,
        order_by: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
        include_deleted: bool = False,
        conn: Optional[Connection] = None,
    ) -> list[dict]:
        """
        查询列表。

        Args:
            where:           等值过滤条件 {col: val}。
            order_by:        排序 (如 "name ASC", "create_time DESC")。
            limit/offset:    分页。
            include_deleted: 是否包含已软删除行。
        """
        clause, params = self._where_clause(where, include_deleted=include_deleted)
        order = f" ORDER BY {order_by}" if order_by else ""
        params.extend([limit, offset])
        idx = len(params) - 1

        query = f"SELECT * FROM {self._table}{clause}{order} LIMIT ${idx} OFFSET ${idx+1}"

        if conn:
            rows = await conn.fetch(query, *params)
        else:
            async with self._pool.acquire() as c:
                rows = await c.fetch(query, *params)

        return [dict(row) for row in rows]

    async def search(
        self,
        keyword: str,
        columns: list[str],
        *,
        extra_where: Optional[WhereClause] = None,
        order_by: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        """
        多列模糊搜索 (ILIKE)。

        Args:
            keyword:     搜索关键词。
            columns:     要搜索的列名列表。
            extra_where: 额外的等值过滤条件。
        """
        conditions: list[str] = []
        params: list = []
        idx = 1

        if self._soft_delete:
            conditions.append("delete_flag = '0'")

        # 模糊搜索: (col1 ILIKE $1 OR col2 ILIKE $1 ...)
        like_clauses = [f"{c} ILIKE ${idx}" for c in columns]
        conditions.append("(" + " OR ".join(like_clauses) + ")")
        params.append(f"%{keyword}%")
        idx += 1

        if extra_where:
            for col, val in extra_where.items():
                if val is None:
                    conditions.append(f"{col} IS NULL")
                else:
                    conditions.append(f"{col} = ${idx}")
                    params.append(val)
                    idx += 1

        where = " WHERE " + " AND ".join(conditions)
        order = f" ORDER BY {order_by}" if order_by else ""
        params.extend([limit, offset])
        idx_last = len(params) - 1

        query = f"SELECT * FROM {self._table}{where}{order} LIMIT ${idx_last} OFFSET ${idx_last+1}"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    async def count(
        self,
        *,
        where: Optional[WhereClause] = None,
        include_deleted: bool = False,
    ) -> int:
        """统计行数。"""
        clause, params = self._where_clause(where, include_deleted=include_deleted)
        query = f"SELECT count(*) AS cnt FROM {self._table}{clause}"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            return row["cnt"] if row else 0

    async def exists(self, pk_value: Any) -> bool:
        """检查主键是否存在。"""
        r = await self.get_by_id(pk_value)
        return r is not None

    # ==================================================================
    # UPDATE
    # ==================================================================

    async def update(
        self,
        pk_value: Any,
        data: dict,
        *,
        where: Optional[WhereClause] = None,
        conn: Optional[Connection] = None,
    ) -> Optional[dict]:
        """
        按主键更新一行，返回更新后的完整行。

        Args:
            pk_value: 主键值。
            data:     要更新的列→值字典。
            where:    额外过滤条件（例如确保 delete_flag='0'）。
        """
        if not data:
            return await self.get_by_id(pk_value)

        if self._auto_ts and "update_time" not in data:
            data["update_time"] = self._now()

        columns = list(data.keys())
        values = list(data.values())
        sets = [f"{col} = ${i+1}" for i, col in enumerate(columns)]

        extra, extra_params = self._where_clause(where, params=[])
        # 移除 delete_flag 软删条件（update 按 pk 精确定位）
        conditions: list[str] = [f"{self._pk} = ${len(values)+1}"]
        if extra:
            conditions.append(extra.lstrip(" WHERE "))

        query = f"""
            UPDATE {self._table}
            SET {', '.join(sets)}
            WHERE {' AND '.join(conditions)}
            RETURNING *
        """
        params_list = values + [pk_value]

        if conn:
            row = await conn.fetchrow(query, *params_list)
        else:
            async with self._pool.acquire() as c:
                row = await c.fetchrow(query, *params_list)

        return dict(row) if row else None

    # ==================================================================
    # DELETE
    # ==================================================================

    async def delete(
        self,
        pk_value: Any,
        *,
        soft: bool | None = None,
        conn: Optional[Connection] = None,
    ) -> bool:
        """
        删除一行。

        Args:
            pk_value: 主键值。
            soft:     是否软删除。None=使用实例默认值。
        """
        use_soft = soft if soft is not None else self._soft_delete

        if use_soft:
            if conn:
                result = await conn.execute(
                    f"UPDATE {self._table} SET delete_flag = '1' WHERE {self._pk} = $1",
                    pk_value,
                )
            else:
                async with self._pool.acquire() as c:
                    result = await c.execute(
                        f"UPDATE {self._table} SET delete_flag = '1' WHERE {self._pk} = $1",
                        pk_value,
                    )
            return result == "UPDATE 1"
        else:
            if conn:
                result = await conn.execute(
                    f"DELETE FROM {self._table} WHERE {self._pk} = $1",
                    pk_value,
                )
            else:
                async with self._pool.acquire() as c:
                    result = await c.execute(
                        f"DELETE FROM {self._table} WHERE {self._pk} = $1",
                        pk_value,
                    )
            return result == "DELETE 1"

    async def delete_where(
        self,
        where: WhereClause,
        *,
        soft: bool | None = None,
        conn: Optional[Connection] = None,
    ) -> int:
        """
        批量删除（按条件）。

        Returns:
            删除行数。
        """
        use_soft = soft if soft is not None else self._soft_delete
        clause, params = self._where_clause(where, include_deleted=True)

        if use_soft:
            query = f"UPDATE {self._table} SET delete_flag = '1'{clause}"
        else:
            query = f"DELETE FROM {self._table}{clause}"

        if conn:
            result = await conn.execute(query, *params)
        else:
            async with self._pool.acquire() as c:
                result = await c.execute(query, *params)

        # asyncpg execute 返回 "UPDATE N" / "DELETE N"
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    # ==================================================================
    # UPSERT
    # ==================================================================

    async def upsert(
        self,
        data: dict,
        conflict_columns: list[str],
        *,
        update_columns: Optional[list[str]] = None,
        conn: Optional[Connection] = None,
    ) -> dict:
        """
        INSERT ... ON CONFLICT ... DO UPDATE。

        Args:
            data:             插入数据。
            conflict_columns: 冲突检测列（如 ["id"] 或 ["code"]）。
            update_columns:  冲突时更新的列，None=全部更新。
        """
        if self._auto_ts:
            data.setdefault("create_time", self._now())

        columns = list(data.keys())
        values = list(data.values())
        placeholder = ", ".join(f"${i+1}" for i in range(len(values)))

        conflict = ", ".join(conflict_columns)
        if update_columns is None:
            update_columns = [c for c in columns if c not in conflict_columns]
        update_sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_columns)

        if self._auto_ts and "update_time" not in update_columns:
            update_sets += ", update_time = EXCLUDED.update_time"
            data.setdefault("update_time", self._now())

        query = f"""
            INSERT INTO {self._table} ({', '.join(columns)})
            VALUES ({placeholder})
            ON CONFLICT ({conflict})
            DO UPDATE SET {update_sets}
            RETURNING *
        """

        if conn:
            row = await conn.fetchrow(query, *values)
        else:
            async with self._pool.acquire() as c:
                row = await c.fetchrow(query, *values)

        return dict(row)

    # ==================================================================
    # 事务
    # ==================================================================

    async def transaction(self):
        """
        事务上下文管理器。

        Usage:
            async with repo.transaction() as conn:
                await repo.insert({"id": "1", ...}, conn=conn)
                await repo.insert({"id": "2", ...}, conn=conn)
        """
        return self._pool.acquire().__aenter__()

    async def execute_raw(
        self,
        sql: str,
        *params: Any,
        conn: Optional[Connection] = None,
    ) -> list[dict]:
        """执行只读 SQL，返回 list[dict]。"""
        if conn:
            rows = await conn.fetch(sql, *params)
        else:
            async with self._pool.acquire() as c:
                rows = await c.fetch(sql, *params)
        return [dict(row) for row in rows]
