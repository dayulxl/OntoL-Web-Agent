"""
本体领域图操作
==============
领域实现层 — 定义本体 Label（Entity/Behavior/Rule...）、关系类型（owl2:subClassOf 等），
调用 base_graph_repo 执行复杂图遍历和子图构建。

职责边界:
  base_graph_repo.py        — 通用对象→Cypher (create/merge/match/delete/search/relate)
  ontology_graph_repo.py    — 领域实现: 本体 Label 映射 / 关系类型常量 / 复杂图遍历

外部调用方                          infrastructure/graph
==================              ================================
business/reasoning/              base_graph_repo.py (通用映射)
  step1_clone.py ──clone──→       create_node / merge_edge / delete_node
  step4_reason.py ──reason──→     get_relationships / search_nodes
                                   ↑
                              ontology_graph_repo.py (领域实现)
                                Label: TYPE_TO_LABEL
                                Rel:   OWL2_SUBCLASS_OF / INFERENCE_ACTION_TYPE
                                Walking: climb_subclass_chain / walk_inference_chain

使用方式:
    from infrastructure.graph.ontology_graph_repo import (
        TYPE_TO_LABEL, OWL2_SUBCLASS_OF, climb_subclass_chain, walk_inference_chain
    )
    from infrastructure.graph.base_graph_repo import GraphBaseRepo

    repo = GraphBaseRepo()
    ancestors = await climb_subclass_chain(seed_node_id)
"""
from __future__ import annotations

from typing import Optional

from infrastructure.graph.base_graph_repo import GraphBaseRepo


# ═══════════════════════════════════════════════════════════════════
# 本体 Label 映射 (ont_type → Memgraph Label)
# ═══════════════════════════════════════════════════════════════════

TYPE_TO_LABEL: dict[str, str] = {
    "M_ENTITY":   "Entity",
    "M_BEHAVIOR": "Behavior",
    "M_RULE":     "Rule",
    "M_SCENE":    "Scene",
    "M_AGENT":    "Agent",
    "M_EXCEPTION":"Exception",
    "M_QUALITY":  "Quality",
    "M_EVENT":    "Event",
    "M_TEMPLATE": "Template",
    "M_ROOT":     "Entity",
    "M_BASE_ONTOLOGY": "Entity",
}


# ═══════════════════════════════════════════════════════════════════
# 关系类型常量
# ═══════════════════════════════════════════════════════════════════

OWL2_SUBCLASS_OF    = "owl2:subClassOf"
OWL2_EQUIVALENT     = "owl2:equivalentClass"
OWL2_DISJOINT       = "owl2:disjointWith"
OWL2_INVERSE        = "owl2:inverseOf"
INFERENCE_ACTION_TYPE = "inference"   # actionType 属性值


# ═══════════════════════════════════════════════════════════════════
# 图遍历 — 领域特有递归逻辑
# ═══════════════════════════════════════════════════════════════════

async def climb_subclass_chain(
    node_id: int, visited: set = None
) -> list[dict]:
    """沿 owl2:subClassOf 递归上爬祖先链 [父, 祖父, ..., 顶层]。

    这是 OWL2 语义的核心：子类型继承父类型所有属性。
    返回列表从上到下（近→远），不含自身。
    """
    if visited is None:
        visited = set()
    if node_id in visited:
        return []
    visited.add(node_id)

    repo = GraphBaseRepo()
    parents = await repo.get_outgoing_by_rel_type(node_id, OWL2_SUBCLASS_OF)
    chain = []
    for p in parents:
        upper = await climb_subclass_chain(p["id"], visited)
        chain.extend(upper)
        chain.append(p)
    return chain


async def walk_inference_chain(
    node_id: int, result: list, visited: set
) -> None:
    """沿 actionType=inference 边递归下探下游链 (DFS 防环)。"""
    if node_id in visited:
        return
    visited.add(node_id)

    driver = await _get_driver()
    async with driver.session() as session:
        rec = await session.run(
            "MATCH (n)-[r]->(m) WHERE id(n) = $id "
            "AND (type(r) CONTAINS 'inference' OR r.actionType = $at) "
            "RETURN id(m) AS id, labels(m) AS labels, properties(m) AS props",
            id=node_id, at=INFERENCE_ACTION_TYPE,
        )
        for row in await rec.data():
            ds = {"id": row["id"], "labels": row["labels"], "props": dict(row["props"])}
            result.append(ds)
            await walk_inference_chain(row["id"], result, visited)


async def get_inference_outgoing_edges(node_id: int) -> list[dict]:
    """查 actionType=inference 的出边 — 返回 {id, labels, props, rel_type, rel_props}。"""
    driver = await _get_driver()
    async with driver.session() as session:
        rec = await session.run(
            "MATCH (n)-[r]->(m) WHERE id(n) = $id "
            "AND (type(r) CONTAINS 'inference' OR r.actionType = $at) "
            "RETURN id(m) AS id, labels(m) AS labels, properties(m) AS props, "
            "type(r) AS rel_type, properties(r) AS rel_props",
            id=node_id, at=INFERENCE_ACTION_TYPE,
        )
        return [
            {"id": r["id"], "labels": r["labels"], "props": dict(r["props"]),
             "rel_type": r["rel_type"], "rel_props": dict(r["rel_props"])}
            for r in await rec.data()
        ]


# ================================
# 合并继承属性
# ================================

def merge_inherited_props(
    ancestors: list[dict], seed: dict
) -> dict:
    """OWL2 subClassOf 属性继承：祖先属性为基底 → 逐层被子类覆盖 → 种子扩展保留。

    ancestors: [顶层, ..., 直接父类] (climb_subclass_chain 返回顺序)
    seed:      {"id": ..., "labels": [...], "props": {...}}
    返回合并后的完整属性 dict。
    """
    merged = {}
    for anc in ancestors:
        merged.update(anc.get("props", {}) or {})
    merged.update(seed.get("props", {}) or {})
    return merged


# ================================
# 内部
# ================================

def _get_driver():
    from infrastructure.graph.neo4j import get_driver as _g
    return _g()
