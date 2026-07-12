"""
底层图操作（纯 DB 原子操作）
--------------------------
供推理引擎和转换层调用的 Memgraph 原子操作。
不包含任何本体语言逻辑——本体语义由 transformation/ 层处理。
"""

from typing import Optional

from common.exceptions.base import InfrastructureError as GraphQueryError
from common.utils.logger import get_logger
from infrastructure.db.neo4j import get_driver

logger = get_logger(__name__)

# ---- 节点查询 ----

async def get_node(node_id: int) -> Optional[dict]:
    """按原生 ID 查节点，返回 {id, labels, props}。"""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (n) WHERE id(n) = $node_id "
            "RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props",
            node_id=node_id,
        )
        record = await result.single()
        if record is None:
            return None
        return {"id": record["id"], "labels": record["labels"], "props": dict(record["props"])}


async def search_nodes(keyword: str, limit: int = 50) -> list[dict]:
    """按 code / name / ont_type 模糊搜索节点。"""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (n) WHERE (n.code IS NOT NULL AND n.code CONTAINS $kw) "
            "OR (n.name IS NOT NULL AND n.name CONTAINS $kw) "
            "OR (n.ont_type IS NOT NULL AND n.ont_type CONTAINS $kw) "
            "RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props LIMIT $limit",
            kw=keyword, limit=limit,
        )
        return [{"id": r["id"], "labels": r["labels"], "props": dict(r["props"])} for r in await result.data()]


# ---- 关系查询 ----

async def get_relationships(node_id: int, direction: str = "both") -> list[dict]:
    """查节点所有关系（边类型、属性、对端节点）。"""
    clauses = {"out": "MATCH (n)-[r]->(m)", "in": "MATCH (n)<-[r]-(m)", "both": "MATCH (n)-[r]-(m)"}
    clause = clauses.get(direction, clauses["both"])
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            f"{clause} WHERE id(n) = $id "
            "RETURN type(r) AS rel_type, properties(r) AS rel_props, "
            "id(m) AS target_id, labels(m) AS target_labels, properties(m) AS target_props",
            id=node_id,
        )
        return [
            {"rel_type": r["rel_type"], "rel_props": dict(r["rel_props"]),
             "target_id": r["target_id"], "target_labels": r["target_labels"],
             "target_props": dict(r["target_props"])}
            for r in await result.data()
        ]


async def get_outgoing_by_rel_type(node_id: int, rel_type: str) -> list[dict]:
    """查指定关系类型 + actionType 的出边目标节点（用于推理链下探）。"""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (n)-[r]->(m) WHERE id(n) = $id "
            "AND (type(r) = $rel OR r.actionType = $action) "
            "RETURN id(m) AS id, labels(m) AS labels, properties(m) AS props, "
            "type(r) AS rel_type, properties(r) AS rel_props",
            id=node_id, rel=rel_type, action="inference",
        )
        return [{"id": r["id"], "labels": r["labels"], "props": dict(r["props"]),
                 "rel_type": r["rel_type"], "rel_props": dict(r["rel_props"])}
                for r in await result.data()]


# ---- 写操作 ----

async def clone_node(original_id: int, cope_version: str, cm: dict[int, tuple[dict, int]]) -> int:
    """克隆节点到副本空间（cope_version 注入）。cm: {原生ID: (原节点, 副本ID)}。"""
    if original_id in cm:
        return cm[original_id][1]
    node = await get_node(original_id)
    if node is None:
        raise GraphQueryError(f"Node {original_id} not found for cloning")
    props = dict(node["props"])
    props["cope_version"] = cope_version
    labels_str = ":".join(node["labels"])
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            f"CREATE (n:{labels_str}) SET n = $props RETURN id(n) AS new_id", props=props)
        rec = await result.single()
        new_id = rec["new_id"]
    cm[original_id] = (node, new_id)
    return new_id


async def clone_edge(src_copy_id: int, tgt_copy_id: int, rel_type: str, rel_props: dict) -> None:
    """副本节点间建边。"""
    driver = await get_driver()
    async with driver.session() as session:
        await session.run(
            "MATCH (a), (b) WHERE id(a) = $src AND id(b) = $tgt "
            f"CREATE (a)-[r:`{rel_type}`]->(b) SET r = $props",
            src=src_copy_id, tgt=tgt_copy_id, props=rel_props)


async def update_node_props(node_id: int, props: dict) -> None:
    """增量合并节点属性。"""
    driver = await get_driver()
    async with driver.session() as session:
        await session.run("MATCH (n) WHERE id(n) = $id SET n += $props", id=node_id, props=props)


# ---- 属性继承（纯数据操作，不含本体语义） ----

def merge_inherited_props(ancestor_chain: list[dict], seed: dict) -> dict:
    """
    父子链属性合并：顶层为基底 → 逐层覆盖 → 底端子节点最高优先级。
    ancestor_chain = [最顶层, ..., 直接父类]，不含种子自身。
    """
    merged = {}
    for a in ancestor_chain:
        merged.update(a.get("props", {}))
    merged.update(seed.get("props", {}))
    return merged


# ---- Cypher 裸执行 ----

async def run_cypher(cypher: str, params: dict = None) -> list[dict]:
    """直接执行 Cypher 语句并返回结果。供转换层调用。"""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(cypher, params or {})
        return await result.data()
