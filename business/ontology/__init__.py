"""本体类型加载器 — 从 SQLite ontol_model / ontol_model_attr 加载类型定义和继承链。"""
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = str(Path(__file__).parent.parent.parent / "infrastructure" / "db" / "ontol.db")

_ONTOLOGY_TYPES_CACHE: Optional[dict] = None


def load_ontology_types() -> dict:
    """从 SQLite 加载所有本体类型及其字段定义（平铺，带缓存）。"""
    global _ONTOLOGY_TYPES_CACHE
    if _ONTOLOGY_TYPES_CACHE is not None:
        return _ONTOLOGY_TYPES_CACHE

    types = {}
    db_path = Path(DB_PATH)
    if not db_path.exists():
        _ONTOLOGY_TYPES_CACHE = types
        return types

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        models = conn.execute(
            "SELECT * FROM ontol_model WHERE delete_flag='0' ORDER BY ontol_model_type, id"
        ).fetchall()
        for m in models:
            md = dict(m)
            attrs = conn.execute(
                """SELECT id, name, code, attr_data_type, attr_length,
                          attr_required, attr_default_value, attr_desc, attr_order
                   FROM ontol_model_attr
                   WHERE ontol_model_id=? AND delete_flag='0'
                   ORDER BY attr_order, code""",
                (md["id"],),
            ).fetchall()
            types[md["id"]] = {
                "id": md["id"],
                "name": md["name"],
                "parent_id": md.get("ontol_parent_id") or None,
                "type_code": md["ontol_model_type"],
                "desc": md["ontol_model_desc"] or "",
                "fields": [
                    {
                        "id": a["id"], "name": a["name"], "code": a["code"],
                        "data_type": a["attr_data_type"], "length": a["attr_length"],
                        "required": a["attr_required"], "default": a["attr_default_value"],
                        "desc": a["attr_desc"] or "", "order": a["attr_order"],
                    }
                    for a in attrs
                ],
            }
    finally:
        conn.close()

    _ONTOLOGY_TYPES_CACHE = types
    return types


def get_inherited_fields(ont_type: str) -> dict[str, dict]:
    """获取指定本体类型的完整字段列表（含继承链 M_ROOT → … → ont_type）。

    子类型字段覆盖父类型同名字段，返回 {field_code: field_info}。
    """
    types = load_ontology_types()
    if not types or ont_type not in types:
        return {}

    fields: dict[str, dict] = {}
    current_id = ont_type
    visited = set()

    while current_id and current_id in types and current_id not in visited:
        visited.add(current_id)
        t = types[current_id]
        for f in t.get("fields", []):
            code = f.get("code", "")
            if code not in fields:
                fields[code] = {**f, "source_model": current_id, "source_name": t.get("name", "")}
        current_id = t.get("parent_id")

    return fields


def clear_cache() -> None:
    """清除类型缓存（用于强制刷新）。"""
    global _ONTOLOGY_TYPES_CACHE
    _ONTOLOGY_TYPES_CACHE = None
