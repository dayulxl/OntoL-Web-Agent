"""
Step 4 — 导入 Memgraph 图数据库
================================
将实体/关系写入图数据库 + 场景绑定。

单入口: import_to_graph(entities, relationships, scene_ids, filename) -> dict
异步函数，操作 Memgraph + SQLite。
"""


async def import_to_graph(
    entities: list[dict],
    relationships: list[dict],
    scene_ids: list[str],
    filename: str = "",
) -> dict:
    """导入实体/关系到 Memgraph 图数据库 + SQLite 场景绑定。

    流程: 雪花ID映射 → MERGE节点(补全字段) → MERGE关系 → 场景绑定

    Returns: {nodes_created, edges_created, entity_count, filled_fields, scene_bind_count}
    """
    from business.upload.import_service import import_entities_to_graph as _import
    return await _import(entities, relationships, scene_ids, filename)
