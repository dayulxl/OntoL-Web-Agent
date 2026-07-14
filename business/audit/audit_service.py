"""
审核记录业务服务
---------------
所有 ontol_audit_log 表的查询、写入、更新、删除逻辑集中于此。
路由层只做参数解析 + 调用本模块 + 格式化响应。
"""
import sqlite3
import uuid as _uuid
from pathlib import Path
from typing import Any, Optional

DB_PATH = str(Path(__file__).parent.parent.parent / "infrastructure" / "db" / "ontol.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ═══════════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════════

def list_audit_logs(
    *,
    audit_status: Optional[str] = None,
    trigger_source: Optional[str] = None,
    node_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """分页查询审核记录，返回 {rows, stats, total}。"""
    where = ["delete_flag='0'"]
    params: list = []

    if audit_status:
        where.append("audit_status=?")
        params.append(audit_status)
    if trigger_source:
        where.append("trigger_source=?")
        params.append(trigger_source)
    if node_id:
        where.append("node_id LIKE ?")
        params.append(f"%{node_id}%")
    if batch_id:
        where.append("batch_id LIKE ?")
        params.append(f"%{batch_id}%")
    if keyword:
        where.append(
            "(id LIKE ? OR node_id LIKE ? OR batch_id LIKE ? "
            "OR fail_reason LIKE ? OR model_version LIKE ? OR reviewer_id LIKE ?)"
        )
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw, kw, kw, kw])

    wc = " AND ".join(where)

    conn = _connect()
    try:
        # 统计各状态数量
        stat_rows = conn.execute(
            f"SELECT audit_status, COUNT(*) AS cnt FROM ontol_audit_log WHERE {wc} GROUP BY audit_status",
            tuple(params),
        ).fetchall()
        stats = {"total": 0, "pass": 0, "fail": 0, "review": 0}
        for sr in stat_rows:
            sr = dict(sr)
            key = sr["audit_status"].lower()
            if key in stats:
                stats[key] = sr["cnt"]
            stats["total"] += sr["cnt"]

        # 总数
        total_row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM ontol_audit_log WHERE {wc}",
            tuple(params),
        ).fetchone()
        total = dict(total_row)["cnt"] if total_row else 0

        # 分页数据
        rows = conn.execute(
            f"SELECT * FROM ontol_audit_log WHERE {wc} ORDER BY create_time DESC LIMIT ? OFFSET ?",
            tuple(params) + (limit, offset),
        ).fetchall()
        return {"rows": [dict(r) for r in rows], "stats": stats, "total": total}
    finally:
        conn.close()


def get_audit_log(log_id: str) -> Optional[dict[str, Any]]:
    """获取单条审核记录，不存在返回 None。"""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM ontol_audit_log WHERE id=? AND delete_flag='0'",
            (log_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# 写
# ═══════════════════════════════════════════════════════════════════

def create_audit_log(data: dict[str, Any]) -> str:
    """创建审核记录，返回新记录 ID。"""
    log_id = data.get("id") or _uuid.uuid4().hex[:16]
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO ontol_audit_log (id, node_id, batch_id, trigger_source, "
            "prompt_template, audit_status, llm_score, fail_reason, suggested_data, "
            "input_snapshot, llm_raw_output, token_usage, model_version, duration_ms, "
            "reviewer_id, review_comment, create_user) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                log_id,
                data.get("node_id", ""),
                data.get("batch_id", ""),
                data.get("trigger_source", "MANUAL"),
                data.get("prompt_template"),
                data.get("audit_status", "REVIEW"),
                data.get("llm_score"),
                data.get("fail_reason"),
                data.get("suggested_data"),
                data.get("input_snapshot"),
                data.get("llm_raw_output"),
                data.get("token_usage"),
                data.get("model_version"),
                data.get("duration_ms"),
                data.get("reviewer_id"),
                data.get("review_comment"),
                data.get("create_user", ""),
            ),
        )
        conn.commit()
        return log_id
    finally:
        conn.close()


def update_audit_log(log_id: str, data: dict[str, Any]) -> bool:
    """更新审核记录（仅允许复核字段+状态）。返回 False 表示记录不存在。"""
    conn = _connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM ontol_audit_log WHERE id=? AND delete_flag='0'", (log_id,)
        ).fetchone()
        if not exists:
            return False

        updatable = [
            "audit_status", "reviewer_id", "review_comment", "fail_reason",
            "suggested_data", "update_user",
        ]
        fields = []
        params: list = []
        for key in updatable:
            if key in data:
                fields.append(f"{key}=?")
                params.append(data[key])
        if not fields:
            return True  # nothing to update, but exists

        fields.append("update_time=datetime('now','localtime')")
        params.append(log_id)
        conn.execute(
            f"UPDATE ontol_audit_log SET {', '.join(fields)} WHERE id=?",
            tuple(params),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def delete_audit_log(log_id: str) -> None:
    """软删除审核记录。"""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE ontol_audit_log SET delete_flag='1', "
            "update_time=datetime('now','localtime') WHERE id=?",
            (log_id,),
        )
        conn.commit()
    finally:
        conn.close()
