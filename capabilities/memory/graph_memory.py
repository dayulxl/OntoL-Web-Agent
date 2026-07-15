"""
图记忆管理
----------
基于 Memgraph（Neo4j 兼容协议）的知识图谱存储与检索，
支持节点/关系 CRUD、Schema 发现、图遍历。
封装图数据库操作，供 Agent 和 Chain 使用。
"""
from typing import Optional
from datetime import datetime

from neo4j._async.driver import AsyncDriver

from common.exceptions.base import InfrastructureError


class GraphMemory:
    """
    知识图谱记忆存储。

    封装 Memgraph/Neo4j 图数据库的节点/关系操作，提供 Schema 发现和子图遍历能力。
    通过 langchain-neo4j 的 Neo4jGraph 兼容 LangChain 生态。

    使用方式:
        from infrastructure.graph.neo4j import get_driver
        driver = await get_driver()
        graph = GraphMemory(driver)
        nodes = await graph.list_nodes("Entity", limit=50)
    """

    def __init__(self, driver: AsyncDriver):
        """
        Args:
            driver: 图数据库异步驱动实例（来自 infrastructure/db/neo4j.py）。
        """
        self._driver = driver

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    async def get_schema(self) -> dict:
        """
        获取图 Schema：所有标签和关系类型。

        Memgraph 不使用 CALL db.labels() / CALL db.relationshipTypes()
        这些是 Neo4j 专有存储过程，在此用标准 Cypher 替代。

        Returns:
            {"labels": [...], "relationship_types": [...],
             "node_count": int, "edge_count": int}
        """
        async with self._driver.session() as session:
            # Memgraph 兼容：使用 UNWIND labels(n) 替代 CALL db.labels()
            labels_result = await session.run(
                "MATCH (n) UNWIND labels(n) AS label RETURN DISTINCT label"
            )
            labels = [record["label"] async for record in labels_result]

            # Memgraph 兼容：使用 DISTINCT type(r) 替代 CALL db.relationshipTypes()
            rels_result = await session.run(
                "MATCH ()-[r]->() RETURN DISTINCT type(r) AS relationshipType"
            )
            relationship_types = [record["relationshipType"] async for record in rels_result]

            node_count_r = await session.run("MATCH (n) RETURN count(n) AS cnt")
            node_count_rec = await node_count_r.single()
            node_count = node_count_rec["cnt"] if node_count_rec else 0

            edge_count_r = await session.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
            edge_count_rec = await edge_count_r.single()
            edge_count = edge_count_rec["cnt"] if edge_count_rec else 0

        return {
            "labels": sorted(labels),
            "relationship_types": sorted(relationship_types),
            "node_count": node_count,
            "edge_count": edge_count,
        }

    # ------------------------------------------------------------------
    # Node CRUD
    # ------------------------------------------------------------------

    async def list_nodes(self, label: Optional[str] = None, limit: int = 100, keyword: Optional[str] = None) -> list[dict]:
        """
        列出节点。

        Args:
            label: 按标签过滤，None 表示所有标签。
            limit: 最大返回数。
            keyword: 按 name/title 属性模糊搜索。

        Returns:
            节点列表 [{id, label, properties}, ...]。
        """
        if label:
            clause = f"MATCH (n:`{label}`)"
        else:
            clause = "MATCH (n)"

        conditions = []
        if keyword:
            conditions.append("(n.name CONTAINS $keyword OR n.title CONTAINS $keyword)")

        where = ""
        if conditions:
            where = " WHERE " + " AND ".join(conditions)

        query = f"{clause}{where} RETURN n LIMIT $limit"

        async with self._driver.session() as session:
            result = await session.run(query, label=label, keyword=keyword, limit=limit)
            nodes = []
            async for record in result:
                node = record["n"]
                nodes.append({
                    "id": node.id,
                    "labels": list(node.labels),
                    "properties": dict(node),
                })
            return nodes

    async def get_node(self, node_id: int) -> Optional[dict]:
        """
        获取节点详情及邻接关系。

        Args:
            node_id: 图数据库内部节点 ID。

        Returns:
            {"id", "labels", "properties", "relationships": [...]} 或 None。
        """
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (n)
                WHERE id(n) = $node_id
                OPTIONAL MATCH (n)-[r]-(m)
                RETURN n, collect({edge_id: id(r), type: type(r), props: properties(r),
                                   source_id: id(startNode(r)), target_id: id(endNode(r)),
                                   related_id: id(m), related_labels: labels(m)}) AS relationships
                """,
                node_id=node_id,
            )
            record = await result.single()
            if not record:
                return None

            node = record["n"]
            return {
                "id": node.id,
                "labels": list(node.labels),
                "properties": dict(node),
                "relationships": [
                    r for r in record["relationships"] if r.get("target_id") is not None
                ],
            }

    async def create_node(self, label: str, properties: dict) -> dict:
        """
        创建节点。

        Args:
            label: 节点标签（如 'Entity', 'Event'）。
            properties: 节点属性。

        Returns:
            {"id", "labels", "properties"}。
        """
        safe_label = label.replace("`", "")
        # 注入创建/更新时间
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        properties["create_time"] = now
        properties["update_time"] = now
        async with self._driver.session() as session:
            result = await session.run(
                f"CREATE (n:`{safe_label}`) SET n = $props RETURN n",
                props=properties,
            )
            record = await result.single()
            if not record:
                raise InfrastructureError("Node creation returned empty result")
            node = record["n"]
            return {"id": node.id, "labels": list(node.labels), "properties": dict(node)}

    async def update_node(self, node_id: int, properties: dict, remove_keys: Optional[list[str]] = None) -> Optional[dict]:
        """
        更新节点属性。SET 合并新属性，REMOVE 清除指定 key。自动刷新 update_time。

        Args:
            node_id: 节点 ID。
            properties: 要更新的属性。
            remove_keys: 要删除的属性 key 列表。

        Returns:
            {"id", "labels", "properties"} 或 None。
        """
        # 注入更新时间，移除不可修改的系统字段
        properties["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        properties.pop("create_time", None)  # 创建时间不可修改
        async with self._driver.session() as session:
            # 1. 合并新属性
            await session.run(
                "MATCH (n) WHERE id(n) = $node_id SET n += $props",
                node_id=node_id,
                props=properties,
            )
            # 2. 删除指定属性（Memgraph 不支持 n[$key] 动态属性访问，用 safe key + Cypher REMOVE）
            # 系统字段保护，不可删除
            _PROTECTED_KEYS = {"create_time", "update_time", "id", "type"}
            if remove_keys:
                import re as _re
                for k in remove_keys:
                    if k in _PROTECTED_KEYS:
                        continue
                    # 只允许字母/数字/下划线，防注入
                    if not _re.match(r'^[A-Za-z_]\w*$', k):
                        continue
                    await session.run(
                        f"MATCH (n) WHERE id(n) = $node_id REMOVE n.`{k}`",
                        node_id=node_id,
                    )
            # 3. 返回最新状态
            result = await session.run(
                "MATCH (n) WHERE id(n) = $node_id RETURN n",
                node_id=node_id,
            )
            record = await result.single()
            if not record:
                return None
            node = record["n"]
            return {"id": node.id, "labels": list(node.labels), "properties": dict(node)}

    async def delete_node(self, node_id: int) -> bool:
        """
        删除节点及其所有关联关系。

        Args:
            node_id: 节点 ID。

        Returns:
            True 表示成功删除。
        """
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (n) WHERE id(n) = $node_id DETACH DELETE n RETURN count(n) AS deleted",
                node_id=node_id,
            )
            record = await result.single()
            return record["deleted"] > 0

    # ------------------------------------------------------------------
    # Edge CRUD
    # ------------------------------------------------------------------

    async def create_edge(self, source_id: int, target_id: int, rel_type: str, properties: Optional[dict] = None) -> dict:
        """
        创建关系。

        Args:
            source_id: 起始节点 ID。
            target_id: 目标节点 ID。
            rel_type: 关系类型。
            properties: 关系属性。

        Returns:
            {"id", "type", "properties", "source_id", "target_id"}。
        """
        safe_type = rel_type.replace("`", "")
        props = properties or {}
        # 注入创建/更新时间
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        props["create_time"] = now
        props["update_time"] = now
        async with self._driver.session() as session:
            result = await session.run(
                f"MATCH (a), (b) WHERE id(a) = $source_id AND id(b) = $target_id "
                f"CREATE (a)-[r:`{safe_type}` $props]->(b) RETURN r, id(a) AS source_id, id(b) AS target_id",
                source_id=source_id,
                target_id=target_id,
                props=props,
            )
            record = await result.single()
            if not record:
                raise InfrastructureError(f"Could not create edge: source or target node not found")
            edge = record["r"]
            return {
                "id": edge.id,
                "type": edge.type,
                "properties": dict(edge),
                "source_id": record["source_id"],
                "target_id": record["target_id"],
            }

    async def delete_edge(self, edge_id: int) -> bool:
        """
        删除关系。

        Args:
            edge_id: 关系 ID。

        Returns:
            True 表示成功删除。
        """
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH ()-[r]->() WHERE id(r) = $edge_id DELETE r RETURN count(r) AS deleted",
                edge_id=edge_id,
            )
            record = await result.single()
            return record["deleted"] > 0

    async def update_edge(self, edge_id: int, properties: dict) -> Optional[dict]:
        """
        更新关系的属性。会自动刷新 update_time。

        Args:
            edge_id: 关系 ID。
            properties: 要合并的属性。

        Returns:
            {"id", "properties"}，不存在则返回 None。
        """
        props = dict(properties)
        # 系统字段保护：创建时间不可修改，更新时间强制刷新
        props.pop("create_time", None)
        props["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH ()-[e]->() WHERE id(e) = $eid SET e += $props "
                "RETURN id(e) AS id, properties(e) AS props",
                eid=edge_id, props=props,
            )
            rec = await result.single()
            if not rec:
                return None
            return {"id": rec["id"], "properties": dict(rec["props"] or {})}

    async def list_all_edges(self, limit: int = 2000) -> list[dict]:
        """
        列出所有关系（边）。

        Args:
            limit: 最大返回数。

        Returns:
            边列表 [{id, type, source_id, target_id, properties}, ...]。
        """
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (a)-[r]->(b) RETURN id(r) AS id, type(r) AS type, properties(r) AS properties, "
                "id(a) AS source_id, id(b) AS target_id ORDER BY id LIMIT $limit",
                limit=limit,
            )
            return [
                {
                    "id": record["id"],
                    "type": record["type"],
                    "source_id": record["source_id"],
                    "target_id": record["target_id"],
                    "properties": record["properties"] or {},
                }
                async for record in result
            ]

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def search_nodes(self, keyword: str, limit: int = 20) -> list[dict]:
        """
        按关键词搜索节点（大小写不敏感）。

        使用 toLower + CONTAINS 替代 Neo4j 的 =~ 正则，
        Memgraph 的 =~ 使用 RE2/ECMAScript 正则，不兼容 (?i) 内联标志。

        Args:
            keyword: 搜索关键词（在 name/title/description 属性中模糊匹配）。
            limit: 最大返回数。

        Returns:
            匹配节点列表。
        """
        kw = keyword.lower()
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (n)
                WHERE toLower(n.name) CONTAINS $kw
                   OR toLower(n.title) CONTAINS $kw
                   OR toLower(n.description) CONTAINS $kw
                RETURN n LIMIT $limit
                """,
                kw=kw,
                limit=limit,
            )
            return [
                {"id": record["n"].id, "labels": list(record["n"].labels), "properties": dict(record["n"])}
                async for record in result
            ]

    async def get_neighborhood(self, node_id: int, depth: int = 2) -> dict:
        """
        获取节点的图邻域。

        Args:
            node_id: 起始节点 ID。
            depth: 遍历深度 1-3，默认 2。

        Returns:
            {"node": {...}, "neighbors": [{"node":..., "path_length": N, "relationship": {...}}]}。
        """
        depth = max(1, min(depth, 3))
        async with self._driver.session() as session:
            # 先查节点自身
            node_rec = await session.run(
                "MATCH (n) WHERE id(n) = $node_id "
                "RETURN n", node_id=node_id)
            node_row = await node_rec.single()
            if not node_row:
                return {"node": None, "neighbors": []}
            node = node_row["n"]

            # 再查邻居（兼容 Memgraph 不支持的 length(path) → size(rels)）
            neighbor_rec = await session.run(
                f"""
                MATCH (n) WHERE id(n) = $node_id
                MATCH path = (n)-[*1..{depth}]-(m)
                WITH m, relationships(path) AS rels, size(relationships(path)) AS dist
                RETURN collect(DISTINCT {{
                    node_id: id(m),
                    labels: labels(m),
                    properties: properties(m),
                    path_length: dist,
                    edge: {{id: id(rels[0]), type: type(rels[0]), properties: properties(rels[0]),
                           source_id: id(startNode(rels[0])), target_id: id(endNode(rels[0]))}}
                }}) AS neighbors
                """,
                node_id=node_id,
            )
            neighbor_row = await neighbor_rec.single()
            raw = (neighbor_row["neighbors"] if neighbor_row else []) or []
            neighbors = [nb for nb in raw if nb is not None]

            return {
                "node": {"id": node.id, "labels": list(node.labels), "properties": dict(node)},
                "neighbors": neighbors,
            }

    async def execute_readonly_cypher(self, query: str, params: Optional[dict] = None) -> list[dict]:
        """
        执行只读 Cypher 查询。

        Args:
            query: Cypher 查询语句（仅允许 READ 操作）。
            params: 查询参数。

        Returns:
            查询结果列表。
        """
        # 基本安全检查：拒写操作
        upper = query.strip().upper()
        forbidden = ["CREATE", "DELETE", "DROP", "SET", "MERGE", "REMOVE", "DETACH"]
        for kw in forbidden:
            if upper.startswith(kw) or f"\n{kw}" in upper or f" {kw}" in upper:
                raise InfrastructureError(f"Read-only query rejected: forbidden keyword '{kw}'")

        params = params or {}
        async with self._driver.session() as session:
            result = await session.run(query, **params)
            return [dict(record) async for record in result]

    # ------------------------------------------------------------------
    # LangChain 集成
    # ------------------------------------------------------------------

    def as_langchain_graph(self):
        """
        获取 langchain-neo4j 兼容的 Neo4jGraph 实例。

        Returns:
            langchain_neo4j.Neo4jGraph
        """
        from langchain_neo4j import Neo4jGraph

        return Neo4jGraph(
            url="bolt://127.0.0.1:7687",
            username="",
            password="",
            enhanced_schema=True,
        )
