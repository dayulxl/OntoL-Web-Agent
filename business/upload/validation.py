"""实体校验 — 检查本体模板匹配 + 计算缺失字段。"""
from business.ontology import load_ontology_types, get_inherited_fields


def validate_entities_for_import(entities: list[dict]) -> dict:
    """校验解析后的实体，检查本体模板匹配 + 计算缺失字段。

    Returns:
        {
            "valid": bool,
            "type_counts": {ont_type: count},
            "unknown_types": [{ont_type, type_name, entity_names: [...]}],
            "missing_fields": [{entity_name, ont_type, missing: [{code, name, required, default}]}],
            "summary": "校验摘要",
        }
    """
    types = load_ontology_types()
    all_type_ids = set(types.keys()) if types else set()

    type_counts: dict[str, int] = {}
    unknown_types_map: dict[str, dict] = {}
    missing_fields_list: list[dict] = []

    for ent in entities:
        ont_type = (ent.get("ont_type") or "").strip()
        name = (ent.get("name") or "").strip()
        type_name = (ent.get("type_name") or "").strip()
        props = ent.get("properties") or {}

        type_counts[ont_type] = type_counts.get(ont_type, 0) + 1

        if ont_type not in all_type_ids:
            key = ont_type
            if key not in unknown_types_map:
                unknown_types_map[key] = {"ont_type": ont_type, "type_name": type_name, "entity_names": []}
            if name and name not in unknown_types_map[key]["entity_names"]:
                unknown_types_map[key]["entity_names"].append(name)
            continue

        inherited = get_inherited_fields(ont_type)
        missing = []
        for code, finfo in inherited.items():
            if code not in props or not props.get(code):
                missing.append({
                    "code": code,
                    "name": finfo.get("name", ""),
                    "required": finfo.get("required", "0") == "1",
                    "default": finfo.get("default") or "",
                    "source_model": finfo.get("source_model", ""),
                    "source_name": finfo.get("source_name", ""),
                })
        if missing:
            missing_fields_list.append({
                "entity_name": name,
                "ont_type": ont_type,
                "type_name": type_name,
                "missing": missing,
                "has_existing_props": list(props.keys()),
            })

    unknown_types = list(unknown_types_map.values())
    has_unknown = len(unknown_types) > 0
    has_missing = len(missing_fields_list) > 0
    valid = not has_unknown

    summary_parts = []
    if has_unknown:
        unknown_names = ", ".join(
            f"{u['ont_type']}({len(u['entity_names'])}个实体)" for u in unknown_types[:5]
        )
        summary_parts.append(f"⚠️ {len(unknown_types)} 个类型无匹配模板: {unknown_names}")
    if has_missing:
        summary_parts.append(f"📋 {len(missing_fields_list)} 个实体可补全字段")
    if not summary_parts:
        summary_parts.append("✅ 所有实体类型均有匹配模板")

    return {
        "valid": valid,
        "type_counts": type_counts,
        "unknown_types": unknown_types,
        "missing_fields": missing_fields_list,
        "summary": " | ".join(summary_parts),
    }
