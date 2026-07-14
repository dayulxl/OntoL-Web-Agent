"""Excel 批量导入导出服务 — ontol_model_attr 表的批量 CRUD。"""
import sqlite3
import uuid as _uuid
from datetime import datetime
from pathlib import Path

DB_PATH = str(Path(__file__).parent.parent.parent / "infrastructure" / "db" / "ontol.db")


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _exec(sql: str, params: tuple = ()) -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def export_attrs(model_id: str, attr_mapping: str) -> tuple[str, list[dict]]:
    """导出模型字段为 rows 列表（含继承字段，按 attr_mapping 过滤）。返回 (model_name, rows)。"""
    from business.ontology import load_ontology_types, get_inherited_fields
    types = load_ontology_types()
    if model_id not in types:
        raise ValueError(f"模型不存在: {model_id}")
    model = types[model_id]
    # 查该 attr_mapping 下的字段 code 集合，只导出匹配的继承字段
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    valid_codes = set(r["code"] for r in conn.execute(
        "SELECT DISTINCT code FROM ontol_model_attr WHERE delete_flag='0' AND attr_mapping=?", (attr_mapping,)))
    conn.close()
    inherited = get_inherited_fields(model_id)
    rows = []
    for code, a in sorted(inherited.items(), key=lambda x: (x[1].get("source_model","") == model_id, x[0])):
        if code not in valid_codes:
            continue
        rows.append({
            "action": "—", "code": code, "name": a.get("name", ""),
            "data_type": a.get("data_type", ""), "length": a.get("length", "") or "",
            "required": a.get("required", "") or "0", "is_only": a.get("is_only", "") or "0",
            "default": a.get("default", "") or "", "desc": a.get("desc", "") or "",
        })
    return model.get("name", model_id), rows


def import_attrs(model_id: str, attr_mapping: str, rows: list[dict]) -> dict:
    """批量导入字段 — 按操作列执行新增/修改/删除。
    rows: [{action, code, name, data_type, length, required, is_only, default, desc}, ...]
    """
    from business.ontology import load_ontology_types
    types = load_ontology_types()
    model = types.get(model_id, {})
    existing = {a["code"]: a for a in model.get("fields", [])}

    added, updated, deleted, skipped = 0, 0, 0, 0
    errors: list[str] = []

    for i, row in enumerate(rows):
        action = (row.get("action") or "").strip()
        code = (row.get("code") or "").strip()
        if not action or action in ("—", "保持"):
            skipped += 1; continue
        if not code:
            errors.append(f"第{i+2}行: 字段编码为空, 跳过"); skipped += 1; continue
        try:
            if action in ("delete", "删除"):
                if code in existing and existing[code].get("attr_is_system") != "1":
                    _exec("DELETE FROM ontol_model_attr WHERE ontol_model_id=? AND code=? AND attr_is_system!='1'", (model_id, code))
                    deleted += 1
                else:
                    errors.append(f"第{i+2}行: {code} 不存在或是系统预设"); skipped += 1
            elif action in ("update", "修改"):
                if code in existing:
                    _update_attr(model_id, code, row); updated += 1
                else:
                    errors.append(f"第{i+2}行: {code} 不存在, 改为新增")
                    _insert_attr(model_id, code, row, attr_mapping); added += 1
            elif action in ("add", "新增"):
                if code in existing:
                    errors.append(f"第{i+2}行: {code} 已存在, 改为修改")
                    _update_attr(model_id, code, row); updated += 1
                else:
                    _insert_attr(model_id, code, row, attr_mapping); added += 1
            else:
                errors.append(f"第{i+2}行: 未知操作 '{action}'"); skipped += 1
        except Exception as e:
            errors.append(f"第{i+2}行: {e}"); skipped += 1

    from business.ontology import clear_cache
    clear_cache()
    return {
        "model_id": model_id, "total_rows": len(rows),
        "added": added, "updated": updated, "deleted": deleted, "skipped": skipped,
        "errors": errors[:20],
    }


def _insert_attr(model_id: str, code: str, row: dict, attr_mapping: str):
    _exec(
        "INSERT INTO ontol_model_attr (id, ontol_model_id, name, code, attr_data_type, "
        "attr_length, attr_required, attr_is_only, attr_default_value, attr_desc, "
        "attr_is_system, attr_mapping, create_time, delete_flag) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'0')",
        (_uuid.uuid4().hex[:16], model_id, row.get("name", code), code,
         row.get("data_type", "VARCHAR"), row.get("length", ""),
         row.get("required", "0"), row.get("is_only", "0"),
         row.get("default", ""), row.get("desc", ""), "0", attr_mapping, _now()),
    )


def _update_attr(model_id: str, code: str, row: dict):
    field_map = {
        "name": "name", "data_type": "attr_data_type", "length": "attr_length",
        "required": "attr_required", "is_only": "attr_is_only",
        "default": "attr_default_value", "desc": "attr_desc",
    }
    sets, vals = [], []
    for ek, col in field_map.items():
        if ek in row and row[ek]:
            sets.append(f"{col}=?"); vals.append(row[ek])
    if sets:
        vals.extend([model_id, code])
        _exec(f"UPDATE ontol_model_attr SET {', '.join(sets)} WHERE ontol_model_id=? AND code=?", tuple(vals))
