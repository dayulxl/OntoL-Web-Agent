"""Excel 批量导入导出服务 — 调用 infrastructure/db 层执行 SQL，service 层只做业务编排。"""
from business.tool.uuid_gen import new_id
from pathlib import Path

# [FEAT] 模型导入 Excel 列定义 — 序号|名称|编码|父级序号|类型|描述
_MODEL_IMPORT_COLS = [
    {"key": "seq",        "label": "序号",     "width": 8},
    {"key": "name",       "label": "名称",     "width": 22},
    {"key": "code",       "label": "编码",     "width": 18},
    {"key": "parent_seq", "label": "父级序号",  "width": 10},
    {"key": "type_code",  "label": "类型",     "width": 10},
    {"key": "desc",       "label": "描述",     "width": 30},
]


# ═══════════════════════════════════════════════════════════════════════
# 字段级 Excel 导入/导出 (ontol_model_attr)
# ═══════════════════════════════════════════════════════════════════════

def export_attrs(model_id: str, attr_mapping: str) -> tuple[str, list[dict]]:
    """导出模型字段为 rows 列表（含继承字段，按 attr_mapping 过滤）。"""
    from business.ontology import load_ontology_types, get_inherited_fields
    types = load_ontology_types()
    if model_id not in types:
        raise ValueError(f"模型不存在: {model_id}")
    model = types[model_id]
    # 查该 attr_mapping 下的字段 code 集合
    from infrastructure.db.ontology_repo import _SQLITE_PATH as DB_PATH
    import sqlite3
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

    SQL 全部走 infrastructure/db/ontology_repo，service 层不做 DB 操作。
    """
    from infrastructure.db.ontology_repo import (
        batch_insert_attrs, update_attr_by_code, delete_attr_by_code,
    )
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
                    delete_attr_by_code(model_id, code)
                    deleted += 1
                else:
                    errors.append(f"第{i+2}行: {code} 不存在或是系统预设"); skipped += 1
            elif action in ("update", "修改"):
                if code in existing:
                    update_attr_by_code(model_id, code, {k: row.get(k) for k in
                        ("name","data_type","length","required","is_only","default","desc")})
                    updated += 1
                else:
                    errors.append(f"第{i+2}行: {code} 不存在, 改为新增")
                    batch_insert_attrs([{
                        "code": code, "name": row.get("name", code),
                        "data_type": row.get("data_type", "VARCHAR"),
                        "length": row.get("length", ""),
                        "required": row.get("required", "0"),
                        "is_only": row.get("is_only", "0"),
                        "default": row.get("default", ""),
                        "desc": row.get("desc", ""),
                    }], model_id, attr_mapping)
                    added += 1
            elif action in ("add", "新增"):
                if code in existing:
                    errors.append(f"第{i+2}行: {code} 已存在, 改为修改")
                    update_attr_by_code(model_id, code, {k: row.get(k) for k in
                        ("name","data_type","length","required","is_only","default","desc")})
                    updated += 1
                else:
                    batch_insert_attrs([{
                        "code": code, "name": row.get("name", code),
                        "data_type": row.get("data_type", "VARCHAR"),
                        "length": row.get("length", ""),
                        "required": row.get("required", "0"),
                        "is_only": row.get("is_only", "0"),
                        "default": row.get("default", ""),
                        "desc": row.get("desc", ""),
                    }], model_id, attr_mapping)
                    added += 1
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


# ═══════════════════════════════════════════════════════════════════════
# 模型级 Excel 批量导入
# ═══════════════════════════════════════════════════════════════════════

def resolve_table_by_mapping(attr_mapping: str) -> tuple[str, str, str]:
    """根据 attr_mapping 返回 (table, parent_col, desc_col)。"""
    if attr_mapping == "01":
        return ("ontol_domain_model", "domain_parent_id", "domain_description")
    return ("ontol_model", "ontol_parent_id", "ontol_model_desc")


def generate_model_import_template(attr_mapping: str) -> str:
    """生成模型导入 Excel 模板，返回临时文件路径。"""
    import tempfile
    from business.tool.excel_handler import write_excel

    sample = [
        {"seq": "1", "name": "示例本体一", "code": "ONT_SAMPLE_1",
         "parent_seq": "", "type_code": "M1", "desc": "根节点示例"},
        {"seq": "2", "name": "示例本体二", "code": "ONT_SAMPLE_2",
         "parent_seq": "1", "type_code": "M2", "desc": "子节点示例（父级序号=1）"},
    ]
    tmp = tempfile.mktemp(suffix=".xlsx")
    write_excel(tmp, "模型导入模板", _MODEL_IMPORT_COLS, sample)
    return tmp


def import_models_from_excel(
    filepath: str,
    table: str = "ontol_model",
    parent_col: str = "ontol_parent_id",
    desc_col: str = "ontol_model_desc",
    attr_mapping: str = "00",
) -> dict:
    """从 Excel 批量导入本体模型 — service 层只做数据解析，SQL 走 infrastructure。

    Excel 列: 序号 | 名称 | 编码 | 父级序号 | 类型 | 描述
    序号为假序号仅用于 Excel 内部父级引用，入库前替换为 UUID。
    """
    from business.tool.excel_handler import read_excel
    from infrastructure.db.ontology_repo import batch_insert_models, list_existing_codes

    _headers, rows = read_excel(filepath)
    if not rows:
        raise ValueError("Excel 文件为空或无法解析")

    # ── 1. 解析行数据 ──
    parsed: list[dict] = []
    seq_set: set[str] = set()
    for i, row in enumerate(rows):
        seq = (row.get("序号") or "").strip()
        name = (row.get("名称") or "").strip()
        code = (row.get("编码") or "").strip()
        parent_seq = (row.get("父级序号") or "").strip()
        type_code = (row.get("类型") or "").strip()
        desc = (row.get("描述") or "").strip()

        if not name and not code:
            continue
        if not name:
            raise ValueError(f"Excel 第 {i + 2} 行: 名称为空")
        if not code:
            raise ValueError(f"Excel 第 {i + 2} 行 ({name}): 编码为空")
        if seq and seq in seq_set:
            raise ValueError(f"Excel 第 {i + 2} 行: 序号 '{seq}' 重复")
        if seq:
            seq_set.add(seq)

        parsed.append({
            "seq": seq, "name": name, "code": code,
            "parent_seq": parent_seq, "type_code": type_code, "desc": desc,
            "row": i + 2,
        })

    # ── 2. 序号 → UUID 映射 ──
    seq_to_uuid: dict[str, str] = {}
    for p in parsed:
        if p["seq"]:
            seq_to_uuid[p["seq"]] = new_id()

    # ── 3. 编码唯一性检查 ──
    existing = list_existing_codes(table)
    dups = [f"第 {p['row']} 行: '{p['code']}'" for p in parsed if p["code"] in existing]
    if dups:
        raise ValueError("编码已存在:\n" + "\n".join(dups[:10]))

    # ── 4. 解析父级序号 → 父级 UUID ──
    errors: list[str] = []
    models_to_insert: list[dict] = []
    for p in parsed:
        parent_id = None
        if p["parent_seq"]:
            parent_id = seq_to_uuid.get(p["parent_seq"])
            if parent_id is None:
                errors.append(
                    f"第 {p['row']} 行 ({p['name']}): "
                    f"父级序号 '{p['parent_seq']}' 在 Excel 中找不到"
                )
        models_to_insert.append({
            "id": seq_to_uuid.get(p["seq"]) or new_id(),
            "name": p["name"],
            "code": p["code"],
            "parent_id": parent_id,
            "type_code": p["type_code"],
            "desc": p["desc"],
        })
    if errors:
        raise ValueError("父级序号解析失败:\n" + "\n".join(errors[:10]))

    # ── 5. 插入（覆盖 id 为序号映射的 UUID）──
    created = batch_insert_models(models_to_insert, table, parent_col, desc_col)

    from business.ontology import clear_cache
    clear_cache()

    return {
        "created": created,
        "total_rows": len(parsed),
        "table": table,
        "attr_mapping": attr_mapping,
    }


def import_models_from_upload(file_bytes: bytes, filename: str, attr_mapping: str) -> dict:
    """从上传文件批量导入模型 — 统一入口（校验 → 存临时文件 → 导入）。"""
    import tempfile

    if not filename or not filename.endswith((".xlsx", ".xls")):
        raise ValueError("仅支持 .xlsx/.xls 文件")

    table, parent_col, desc_col = resolve_table_by_mapping(attr_mapping)
    tmp = tempfile.mktemp(suffix=".xlsx")
    Path(tmp).write_bytes(file_bytes)
    return import_models_from_excel(tmp, table, parent_col, desc_col, attr_mapping)
