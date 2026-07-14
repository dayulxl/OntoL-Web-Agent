"""
Step 2 — 创建副本节点之间的对应关系
-----------------------------------
遍历 cm 中所有原生节点的出边，在副本节点之间重建同类型边。
保证副本空间的拓扑结构与原图一致。
"""

from business.reasoning.graph_ops import get_relationships, clone_edge


async def step2_relink(cm: dict[int, tuple[dict, int]]) -> int:
    """把所有原节点之间的边，按原始方向和类型复制到副本节点之间。

    遍历克隆映射表中的每个原生节点，对其每条出边：
    如果目标节点也在 cm 中（已被克隆），则在两个副本节点之间创建同类型边。

    Args:
        cm: 克隆映射表 {原生ID: (原生节点dict, 副本ID)}

    Returns:
        int: 创建的副本边总数
    """
    edge_count = 0
    for orig_id, (orig_node, copy_id) in cm.items():
        rels = await get_relationships(orig_id, direction="out")
        for r in rels:
            target_orig = r["target_id"]
            if target_orig in cm:
                target_copy = cm[target_orig][1]
                await clone_edge(copy_id, target_copy, r["rel_type"], r["rel_props"])
                edge_count += 1
    return edge_count
