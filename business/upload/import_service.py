"""实体导入服务 — 将解析后的实体/关系写入图数据库（Memgraph/Neo4j）。"""
import uuid as _uuid
from typing import Any

from business.ontology import get_inherited_fields
from business.tool.snowflake import generate_snowflake_ids

# ont_type → Memgraph label 映射
_TYPE_TO_LABEL = {
    "M_ENTITY": "Entity",
    "M_BEHAVIOR": "Behavior",
    "M_RULE": "Rule",
    "M_SCENE": "Scene",
    "M_AGENT": "Agent",
    "M_EXCEPTION": "Exception",
    "M_QUALITY": "Quality",
    "M_EVENT": "Event",
    "M_TEMPLATE": "Template",
    "M_ROOT": "Entity",
    "M_BASE_ONTOLOGY": "Entity",
}


async def import_entities_to_graph(
    entities: list[dict],
    relationships: list[dict],
    scene_ids: list[str],
    filename: str = "",
) -> dict[str, Any]:
    """将实体和关系导入图数据库。

    流程: 查询已有ID → 雪花ID映射 → 创建节点(补全字段) → 创建关系 → 场景绑定
    """
    from infrastructure.db.neo4j import get_driver

    driver = await get_driver()
    filled_fields_count = 0
    edges_created = 0
    nodes_created = 0
    scene_bind_count = 0

    async with driver.session() as session:
        # 1. 收集已有 ID
        existing_ids: set[int] = set()
        try:
            node_result = await session.run(
                "MATCH (n) WHERE n.id IS NOT NULL RETURN DISTINCT n.id AS nid"
            )
            async for rec in node_result:
                val = rec.get("nid")
                if val is not None:
                    try:
                        existing_ids.add(int(val))
                    except (ValueError, TypeError):
                        pass
            edge_result = await session.run(
                "MATCH ()-[r]->() WHERE r.id IS NOT NULL RETURN DISTINCT r.id AS rid"
            )
            async for rec in edge_result:
                val = rec.get("rid")
                if val is not None:
                    try:
                        existing_ids.add(int(val))
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass

        # 2. 雪花 ID 映射
        id_map = generate_snowflake_ids(entities, relationships, existing_ids)

        # 3. 替换实体的 properties.id
        for ent in entities:
            props = ent.get("properties") or {}
            eid = (props.get("id") or "").strip()
            if eid in id_map:
                props["id"] = id_map[eid]

        # 4. 替换关系中的节点引用
        for rel in relationships:
            for key in ("start_node_id", "end_node_id", "subject", "object"):
                val = (rel.get(key) or "").strip()
                if val in id_map:
                    rel[key] = id_map[val]

        # 5. 创建节点
        for ent in entities:
            name = (ent.get("name") or "").strip()
            ont_type = (ent.get("ont_type") or "M_ENTITY").strip()
            props = ent.get("properties") or {}
            if not name:
                continue
            if "name" not in props:
                props["name"] = name

            # 补全缺失字段
            inherited = get_inherited_fields(ont_type)
            if inherited:
                for code, finfo in inherited.items():
                    if code not in props or not props.get(code):
                        default_val = finfo.get("default") or ""
                        if default_val:
                            props[code] = default_val
                            filled_fields_count += 1
                        elif finfo.get("required", "0") == "1":
                            props[code] = ""
                            filled_fields_count += 1

            clean_props = {k: v for k, v in props.items() if v is not None and v != ""}
            node_label = _TYPE_TO_LABEL.get(ont_type, "Entity")

            await session.run(
                f"""
                MERGE (n:{node_label} {{name: $name}})
                SET n += $props
                SET n.ont_type = $ont_type
                """,
                name=name, props=clean_props, ont_type=ont_type,
            )

        # 6. 创建关系
        for rel in relationships:
            subj = (rel.get("start_node_id") or rel.get("subject") or "").strip()
            pred = (rel.get("type") or rel.get("predicate") or "").strip()
            obj = (rel.get("end_node_id") or rel.get("object") or "").strip()
            if not subj or not pred or not obj:
                continue
            safe_pred = pred.replace("`", "").replace(" ", "_")
            await session.run(
                f"""
                MATCH (a {{name: $subj}})
                MATCH (b {{name: $obj}})
                MERGE (a)-[r:RELATES {{type: $pred}}]->(b)
                SET r.predicate = $pred
                """,
                subj=subj, obj=obj, pred=pred,
            )
            edges_created += 1

        # 统计节点数
        node_result = await session.run("MATCH (n) RETURN count(n) AS cnt")
        node_rec = await node_result.single()
        nodes_created = node_rec["cnt"] if node_rec else 0

    # 7. 场景绑定
    if scene_ids:
        scene_bind_count = _bind_entities_to_scenes(entities, scene_ids)

    return {
        "filename": filename,
        "nodes_created": nodes_created,
        "edges_created": edges_created,
        "entity_count": len(entities),
        "filled_fields": filled_fields_count,
        "scene_bind_count": scene_bind_count,
    }


def _bind_entities_to_scenes(entities: list[dict], scene_ids: list[str]) -> int:
    """将实体名绑定到场景，写入 ontol_node_scene_relation 表。"""
    import sqlite3
    from pathlib import Path

    db_path = str(Path(__file__).parent.parent.parent / "infrastructure" / "db" / "ontol.db")
    conn = sqlite3.connect(db_path)
    count = 0
    try:
        for ent in entities:
            entity_name = (ent.get("name") or "").strip()
            if not entity_name:
                continue
            for sid in scene_ids:
                try:
                    conn.execute(
                        "INSERT INTO ontol_node_scene_relation (id, scene_id, scene_desc) VALUES (?,?,?)",
                        (_uuid.uuid4().hex[:16], sid, entity_name),
                    )
                    count += 1
                except Exception:
                    pass
        conn.commit()
    finally:
        conn.close()
    return count
