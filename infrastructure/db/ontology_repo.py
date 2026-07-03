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
                    SELECT * FROM tree ORDER BY depth, ontol_model_type, ontol_name
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
                    SELECT * FROM tree ORDER BY depth, ontol_model_type, ontol_name
                    """
                )
            return [dict(r) for r in rows]

    async def get_children(self, parent_id: str) -> list[dict]:
        """获取直接子节点。"""
        return await self.model.list(where={"ontol_parent_id": parent_id}, order_by="ontol_model_type, ontol_name")

    # ==================================================================
    # 模型 + 属性 复合查询
    # ==================================================================

    async def get_model_with_attrs(self, model_id: str) -> Optional[dict]:
        """获取本体模型及其所有属性字段（一次返回）。"""
        model = await self.model.get_by_id(model_id)
        if not model:
            return None
        attrs = await self.attr.list(where={"ontol_model_id": model_id}, order_by="attr_relation_flag DESC, attr_code")
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
                ORDER BY attr_relation_flag DESC, attr_code
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

    async def get_attrs_by_model(self, model_id: str, *, relation_flag: Optional[str] = None) -> list[dict]:
        """获取模型属性列表。"""
        where = {"ontol_model_id": model_id}
        if relation_flag:
            where["attr_relation_flag"] = relation_flag
        return await self.attr.list(where=where, order_by="attr_relation_flag DESC, attr_code")

    # ==================================================================
    # 搜索
    # ==================================================================

    async def search_models(self, keyword: str, limit: int = 50) -> list[dict]:
        """按名称/描述模糊搜索本体模型。"""
        return await self.model.search(
            keyword,
            columns=["ontol_name", "ontol_model_desc"],
            limit=limit,
        )

    # ==================================================================
    # 统计
    # ==================================================================

    async def get_stats(self) -> dict:
        """获取全局统计。"""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    (SELECT count(*) FROM ontol_model WHERE delete_flag='0') AS model_count,
                    (SELECT count(*) FROM ontol_model_attr WHERE delete_flag='0') AS attr_count
                """
            )
            return dict(row) if row else {"model_count": 0, "attr_count": 0}
