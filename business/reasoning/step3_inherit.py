"""
Step 3 — 继承属性（owl2:subClassOf 语义）
-----------------------------------------
祖先属性为基底，逐层被子类属性覆盖，子节点扩展字段保留。
属性有变化才写回副本节点，避免无效写操作。
"""

from business.reasoning.graph_ops import merge_inherited_props, update_node_props


async def step3_inherit(
    cm: dict[int, tuple[dict, int]],
    ancestors: list[dict],
) -> int:
    """RDFS 语义生效——遍历所有克隆节点，合并祖先属性到子节点副本。

    合并逻辑（由 merge_inherited_props 实现）：
      顶层祖先属性为基底 → 逐层括号内属性覆盖 → 子节点属性最后覆盖（最高优先级）

    Args:
        cm: 克隆映射表 {原生ID: (原生节点dict, 副本ID)}
        ancestors: 祖先链列表 [顶层, ..., 直接父类]，不含种子自身

    Returns:
        int: 属性发生变化的节点数量
    """
    merged_count = 0
    for orig_id, (orig_node, copy_id) in cm.items():
        merged = merge_inherited_props(ancestors, orig_node)
        if merged != orig_node.get("props", {}):
            await update_node_props(copy_id, merged)
            merged_count += 1
    return merged_count
