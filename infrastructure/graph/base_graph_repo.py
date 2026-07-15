"""
对象 → Cypher 转换器
====================
基础设施层 — 将 Pydantic 模型 / dict 对象拆解为 Node/Edge 结构，
生成参数化 Cypher 模板，处理 ID 校验。

职责边界:
  base_graph_repo.py       — 通用对象→Cypher 转换 (create/merge/match/delete/search/relate)
                             不写死 Label 名，不写死关系类型，不写业务遍历逻辑
  ontology_graph_repo.py   — 领域实现：定义本体 Label（Entity/Behavior/Rule...），
                             关系类型（owl2:subClassOf 等），复杂图遍历/子图构建

外部 Service                          infrastructure/graph
=================                ==================================
business/reasoning/               base_graph_repo.py (对象→Cypher)
  graph_ops.py                     create_node(label, props)
  step1_clone.py                   merge_edge(src,tgt,type,props)
                                   delete_node(node_id)
                                 |
                               ontology_graph_repo.py (领域实现)
                                  labels: Entity/Behavior/Rule/Scene/...
                                  traversal: climb_subclass_chain / walk_inference_chain

使用方式:
    from infrastructure.graph.base_graph_repo import GraphBaseRepo

    repo = GraphBaseRepo()
    await repo.create_node("Entity", {"name": "航母", "code": "CV_001"})
    await repo.merge_edge(123, 456, "owl2:subClassOf", {"actionType": "inference"})
"""
from __future__ import annotations

from typing import Any, Optional

from infrastructure.graph.neo4j import get_driver


class GraphBaseRepo:
    """对象→Cypher 转换器 + 执行。

    纯基础设施层：不包含任何业务 Label 或关系类型的硬编码。
    所有 Label / props / rel_type 均由调用方通过参数传入。

    方法返回：
      - 写入操作 → dict (创建的节点/边信息)
      - 查询操作 → list[dict] | dict | None
    """

    # ═══════════════════════════════════════════════════════════════
    # 节点
    # ═══════════════════════════════════════════════════════════════

    async def create_node(self, label: str, props: dict[str, Any]) -> dict:
        """创建节点 — dict → CREATE (n:Label {props})。

        自动注入 create_time / update_time (Unix 时间戳 int64)。

        Returns: {"id": node_id, "labels": [...], "properties": {...}}
        """
        import time
        ts = int(time.time())
        props.setdefault("create_time", ts)
        props.setdefault("update_time", ts)

        keys = list(props.keys())
        ph = ", ".join(f"${k}" for k in keys)
        cy = f"CREATE (n:{label} {{{ph}}}) RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props"

        driver = await get_driver()
        async with driver.session() as session:
            rec = await session.run(cy, **props)
            row = await rec.single()
            return {"id": row["id"], "labels": row["labels"], "properties": dict(row["props"])}

    async def merge_node(self, label: str, match: dict[str, Any], props: dict[str, Any]) -> dict:
        """MERGE 节点（按 match 字段去重，不存在则创建 + SET 其余属性）。

        Returns: {"id", "labels", "properties", "created": bool}
        """
        import time
        ts = int(time.time())

        # MERGE 条件
        match_parts = [f"{k}: ${'m_'+k}" for k in match]
        match_params = {f"m_{k}": v for k, v in match.items()}

        # SET 属性（不在 match 中的 + 时间戳）
        set_parts = []
        set_params = {}
        for k, v in props.items():
            if k not in match:
                set_parts.append(f"n.{k} = ${'s_'+k}")
                set_params[f"s_{k}"] = v
        set_parts.append(f"n.update_time = {ts}")

        cy = (
            f"MERGE (n:{label} {{{', '.join(match_parts)}}}) "
            f"ON CREATE SET n.create_time = {ts}, {', '.join(set_parts)} "
            f"ON MATCH SET {', '.join(set_parts)} "
            f"RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props"
        )

        driver = await get_driver()
        async with driver.session() as session:
            rec = await session.run(cy, **{**match_params, **set_params})
            row = await rec.single()
            return {"id": row["id"], "labels": row["labels"],
                    "properties": dict(row["props"])}

    async def get_node(self, node_id: int) -> Optional[dict]:
        """按原生 ID 查节点。"""
        driver = await get_driver()
        async with driver.session() as session:
            rec = await session.run(
                "MATCH (n) WHERE id(n) = $id "
                "RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props",
                id=node_id,
            )
            row = await rec.single()
            if row is None:
                return None
            return {"id": row["id"], "labels": row["labels"], "props": dict(row["props"])}

    async def search_nodes(
        self, keyword: str, *, label: str = None, limit: int = 50
    ) -> list[dict]:
        """模糊搜索节点 — 按 name / code / ont_type CONTAINS kw。"""
        params = {"kw": keyword, "lim": limit}
        label_filter = f"AND n:{label}" if label else ""
        cy = (
            f"MATCH (n{label_filter}) "
            f"WHERE (n.name IS NOT NULL AND n.name CONTAINS $kw) "
            f"OR (n.code IS NOT NULL AND n.code CONTAINS $kw) "
            f"OR (n.ont_type IS NOT NULL AND n.ont_type CONTAINS $kw) "
            f"RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props LIMIT $lim"
        )
        driver = await get_driver()
        async with driver.session() as session:
            result = await session.run(cy, **params)
            return [
                {"id": r["id"], "labels": r["labels"], "props": dict(r["props"])}
                for r in await result.data()
            ]

    async def list_nodes(self, label: str = None, limit: int = 100) -> list[dict]:
        """按标签列出节点。"""
        params = {"lim": limit}
        label_filter = f":{label}" if label else ""
        cy = (
            f"MATCH (n{label_filter}) "
            f"RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props LIMIT $lim"
        )
        driver = await get_driver()
        async with driver.session() as session:
            result = await session.run(cy, **params)
            return [
                {"id": r["id"], "labels": r["labels"], "props": dict(r["props"])}
                for r in await result.data()
            ]

    async def update_node(self, node_id: int, props: dict[str, Any]) -> Optional[dict]:
        """更新节点属性 — SET += 新属性，空值 key 被移除。"""
        import time
        ts = int(time.time())

        set_parts = []
        set_params = {"nid": node_id, "ts": ts}
        for k, v in props.items():
            set_parts.append(f"n.{k} = ${'p_'+k}")
            set_params[f"p_{k}"] = v
        set_parts.append("n.update_time = $ts")

        cy = (
            f"MATCH (n) WHERE id(n) = $nid "
            f"SET {', '.join(set_parts)} "
            f"RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props"
        )
        driver = await get_driver()
        async with driver.session() as session:
            rec = await session.run(cy, **set_params)
            row = await rec.single()
            if row is None:
                return None
            return {"id": row["id"], "labels": row["labels"], "props": dict(row["props"])}

    async def delete_node(self, node_id: int) -> bool:
        """删除节点及其所有边 (DETACH DELETE)。"""
        driver = await get_driver()
        async with driver.session() as session:
            rec = await session.run(
                "MATCH (n) WHERE id(n) = $id DETACH DELETE n RETURN count(n) AS cnt",
                id=node_id,
            )
            row = await rec.single()
            return bool(row and row["cnt"] > 0)

    # ═══════════════════════════════════════════════════════════════
    # 边
    # ═══════════════════════════════════════════════════════════════

    async def create_edge(
        self,
        source_id: int,
        target_id: int,
        rel_type: str,
        props: dict[str, Any] = None,
    ) -> dict:
        """在 source → target 之间创建关系边。"""
        import time
        ts = int(time.time())
        props = dict(props or {})
        props.setdefault("create_time", ts)
        props.setdefault("update_time", ts)

        safe_type = rel_type.replace("`", "").replace(" ", "_")
        keys = list(props.keys())
        ph = ", ".join(f"r.{k} = ${'e_'+k}" for k in keys) if keys else ""
        set_clause = f"SET {ph}" if ph else ""
        params = {"sid": source_id, "tid": target_id}
        for k in keys:
            params[f"e_{k}"] = props[k]

        cy = (
            f"MATCH (a) WHERE id(a) = $sid "
            f"MATCH (b) WHERE id(b) = $tid "
            f"CREATE (a)-[r:`{safe_type}`]->(b) "
            f"{set_clause} "
            f"RETURN id(r) AS id, type(r) AS type, properties(r) AS props"
        )
        driver = await get_driver()
        async with driver.session() as session:
            rec = await session.run(cy, **params)
            row = await rec.single()
            return {"id": row["id"], "type": row["type"], "props": dict(row["props"])}

    async def merge_edge(
        self,
        source_id: int,
        target_id: int,
        rel_type: str,
        props: dict[str, Any] = None,
    ) -> dict:
        """MERGE 关系（幂等，不存在则创建）。"""
        import time
        ts = int(time.time())
        props = dict(props or {})

        safe_type = rel_type.replace("`", "").replace(" ", "_")
        keys = list(props.keys())
        set_parts = [f"r.{k} = ${'e_'+k}" for k in keys] if keys else []
        set_parts.append(f"r.update_time = {ts}")
        set_clause = f"ON CREATE SET {', '.join(set_parts)} ON MATCH SET {', '.join(set_parts)}"
        params = {"sid": source_id, "tid": target_id}
        for k in keys:
            params[f"e_{k}"] = props[k]

        cy = (
            f"MATCH (a) WHERE id(a) = $sid "
            f"MATCH (b) WHERE id(b) = $tid "
            f"MERGE (a)-[r:`{safe_type}`]->(b) "
            f"{set_clause} "
            f"RETURN id(r) AS id, type(r) AS type, properties(r) AS props"
        )
        driver = await get_driver()
        async with driver.session() as session:
            rec = await session.run(cy, **params)
            row = await rec.single()
            return {"id": row["id"], "type": row["type"], "props": dict(row["props"])}

    async def get_relationships(
        self, node_id: int, direction: str = "both"
    ) -> list[dict]:
        """查节点的所有关系（边类型 + 属性 + 对端节点）。"""
        clauses = {
            "out": "MATCH (n)-[r]->(m)",
            "in": "MATCH (n)<-[r]-(m)",
            "both": "MATCH (n)-[r]-(m)",
        }
        clause = clauses.get(direction, clauses["both"])
        cy = (
            f"{clause} WHERE id(n) = $id "
            f"RETURN type(r) AS rel_type, properties(r) AS rel_props, "
            f"id(m) AS target_id, labels(m) AS target_labels, properties(m) AS target_props"
        )
        driver = await get_driver()
        async with driver.session() as session:
            result = await session.run(cy, id=node_id)
            return [
                {
                    "rel_type": r["rel_type"],
                    "rel_props": dict(r["rel_props"]),
                    "target_id": r["target_id"],
                    "target_labels": r["target_labels"],
                    "target_props": dict(r["target_props"]),
                }
                for r in await result.data()
            ]

    async def delete_edge(self, edge_id: int) -> bool:
        """按边 ID 删除关系。"""
        driver = await get_driver()
        async with driver.session() as session:
            rec = await session.run(
                "MATCH ()-[r]->() WHERE id(r) = $id DELETE r RETURN count(r) AS cnt",
                id=edge_id,
            )
            row = await rec.single()
            return bool(row and row["cnt"] > 0)

    async def get_outgoing_by_rel_type(
        self, node_id: int, rel_type: str
    ) -> list[dict]:
        """按关系类型查出边 → 返回对端节点列表。"""
        safe_type = rel_type.replace("`", "").replace(" ", "_")
        driver = await get_driver()
        async with driver.session() as session:
            result = await session.run(
                f"MATCH (n)-[r:`{safe_type}`]->(m) WHERE id(n) = $id "
                f"RETURN id(m) AS id, labels(m) AS labels, properties(m) AS props",
                id=node_id,
            )
            return [
                {"id": r["id"], "labels": r["labels"], "props": dict(r["props"])}
                for r in await result.data()
            ]

    # ═══════════════════════════════════════════════════════════════
    # 图 Schema
    # ═══════════════════════════════════════════════════════════════

    async def get_schema(self) -> dict:
        """获取图 Schema — 所有 Label + 关系类型 + 计数。"""
        driver = await get_driver()
        async with driver.session() as session:
            labels_r = await session.run(
                "MATCH (n) UNWIND labels(n) AS label RETURN DISTINCT label"
            )
            labels = [r["label"] async for r in labels_r]

            rels_r = await session.run(
                "MATCH ()-[r]->() RETURN DISTINCT type(r) AS rel_type"
            )
            rel_types = [r["rel_type"] async for r in rels_r]

            nc_r = await session.run("MATCH (n) RETURN count(n) AS cnt")
            nc = (await nc_r.single())["cnt"]

            ec_r = await session.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
            ec = (await ec_r.single())["cnt"]

        return {
            "labels": sorted(labels),
            "relationship_types": sorted(rel_types),
            "node_count": nc,
            "edge_count": ec,
        }

    # ═══════════════════════════════════════════════════════════════
    # 裸 Cypher
    # ═══════════════════════════════════════════════════════════════

    async def execute_readonly(self, cypher: str, **params) -> list[dict]:
        """执行只读 Cypher，返回 list[dict]。"""
        driver = await get_driver()
        async with driver.session() as session:
            rows = await session.run(cypher, **params)
            return [dict(r) for r in await rows.data()]

    async def execute_write(self, cypher: str, **params) -> dict:
        """执行写 Cypher (CREATE/MERGE/SET/DELETE)，返回单行结果。"""
        driver = await get_driver()
        async with driver.session() as session:
            rec = await session.run(cypher, **params)
            row = await rec.single()
            return dict(row) if row else {}
