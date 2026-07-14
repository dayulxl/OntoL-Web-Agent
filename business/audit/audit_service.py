"""
审核记录业务服务
---------------
所有 ontol_audit_log 表的 CRUD + 便捷函数集中于此。
其他模块调用入口：`from business.audit import submit_audit, record_audit_result`

数据流向：
- 调用方 → submit_audit(node_id, batch_id, input_data) → 创建一条 REVIEW 记录
- LLM 审核完成 → record_audit_result(log_id, status, score, ...) → 更新结果
- 前端页面 → GET /api/v1/audit-logs → list_audit_logs()
"""
import sqlite3
import uuid as _uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

DB_PATH = str(Path(__file__).parent.parent.parent / "infrastructure" / "db" / "ontol.db")


# ═══════════════════════════════════════════════════════════════════
# Pydantic 模型 — 其他模块调用时的入参契约
# ═══════════════════════════════════════════════════════════════════

class AuditLogCreate(BaseModel):
    """创建审核记录 — 新建一笔待审核记录时使用。"""
    node_id: str = Field(..., description="被审核的图节点 ID")
    batch_id: str = Field(..., description="审核批次号，同一批次多条记录用同一个 batch_id")
    trigger_source: str = Field(default="MANUAL", description="触发来源：MANUAL=人工, AUTO_LOOP=自动巡检")
    prompt_template: Optional[str] = Field(default=None, description="审核规则/提示词模板")
    audit_status: str = Field(default="REVIEW", description="审核状态：REVIEW=待复核, PASS=通过, FAIL=未通过")
    input_snapshot: Optional[str] = Field(default=None, description="输入数据快照（JSON 字符串）")
    create_user: str = Field(default="", description="创建人标识")


class AuditLogResult(BaseModel):
    """审核结果 — LLM 审核完成后回写结果时使用。"""
    audit_status: str = Field(..., description="审核结果：PASS / FAIL / REVIEW")
    llm_score: Optional[float] = Field(default=None, description="LLM 置信度评分 0.0~1.0")
    fail_reason: Optional[str] = Field(default=None, description="未通过时的违规/异常原因")
    suggested_data: Optional[str] = Field(default=None, description="LLM 建议修正的数据（JSON 字符串）")
    llm_raw_output: Optional[str] = Field(default=None, description="LLM 原始输出全文")
    token_usage: Optional[str] = Field(default=None, description="Token 消耗统计（JSON 字符串）")
    model_version: Optional[str] = Field(default=None, description="使用的 LLM 模型版本/名称")
    duration_ms: Optional[int] = Field(default=None, description="审核耗时（毫秒）")


class AuditLogUpdate(BaseModel):
    """人工复核更新 — 仅允许修改复核相关字段。"""
    audit_status: Optional[str] = Field(default=None, description="审核状态")
    reviewer_id: Optional[str] = Field(default=None, description="复核人 ID")
    review_comment: Optional[str] = Field(default=None, description="复核意见")
    fail_reason: Optional[str] = Field(default=None, description="违规原因")
    suggested_data: Optional[str] = Field(default=None, description="建议修正数据")
    update_user: Optional[str] = Field(default=None, description="更新人")


# ═══════════════════════════════════════════════════════════════════
# SQLite 连接
# ═══════════════════════════════════════════════════════════════════

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


def query_by_batch(batch_id: str) -> list[dict[str, Any]]:
    """按批次号查询同一批次的所有审核记录。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM ontol_audit_log WHERE batch_id=? AND delete_flag='0' "
            "ORDER BY create_time",
            (batch_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_by_node(node_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """按节点 ID 查询该节点的所有审核历史。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM ontol_audit_log WHERE node_id=? AND delete_flag='0' "
            "ORDER BY create_time DESC LIMIT ?",
            (node_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# ══ 便捷函数 — 其他模块调用入口 ══
# ═══════════════════════════════════════════════════════════════════

def submit_audit(
    node_id: str,
    batch_id: str = "",
    input_snapshot: str = "",
    *,
    trigger_source: str = "MANUAL",
    prompt_template: Optional[str] = None,
    create_user: str = "",
) -> str:
    """
    提交审核 — 最简调用入口，其他模块只需传 node_id + 输入数据。

    用法:
        from business.audit import submit_audit, record_audit_result

        # 1. 创建审核记录
        log_id = submit_audit("node_123", batch_id="B001", input_snapshot=json.dumps(data))

        # 2. LLM 审核完成后回写结果
        record_audit_result(log_id, audit_status="PASS", llm_score=0.95, model_version="gpt-4")

    返回: 新建的审核记录 ID
    """
    if not batch_id:
        batch_id = _uuid.uuid4().hex[:12]
    log_id = _uuid.uuid4().hex[:16]
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO ontol_audit_log "
            "(id, node_id, batch_id, trigger_source, prompt_template, audit_status, "
            "input_snapshot, create_user) "
            "VALUES (?, ?, ?, ?, ?, 'REVIEW', ?, ?)",
            (log_id, node_id, batch_id, trigger_source, prompt_template,
             input_snapshot, create_user),
        )
        conn.commit()
        return log_id
    finally:
        conn.close()


def record_audit_result(
    log_id: str,
    audit_status: str,
    *,
    llm_score: Optional[float] = None,
    fail_reason: Optional[str] = None,
    suggested_data: Optional[str] = None,
    llm_raw_output: Optional[str] = None,
    token_usage: Optional[str] = None,
    model_version: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> bool:
    """
    回写审核结果 — LLM 审核完成后，把结果写入已有记录。

    返回: True=更新成功, False=记录不存在
    """
    conn = _connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM ontol_audit_log WHERE id=? AND delete_flag='0'", (log_id,)
        ).fetchone()
        if not exists:
            return False

        fields = [
            "audit_status=?", "update_time=datetime('now')",
        ]
        params: list = [audit_status]
        for col, val in [
            ("llm_score", llm_score),
            ("fail_reason", fail_reason),
            ("suggested_data", suggested_data),
            ("llm_raw_output", llm_raw_output),
            ("token_usage", token_usage),
            ("model_version", model_version),
            ("duration_ms", duration_ms),
        ]:
            if val is not None:
                fields.append(f"{col}=?")
                params.append(val)

        params.append(log_id)
        conn.execute(
            f"UPDATE ontol_audit_log SET {', '.join(fields)} WHERE id=?",
            tuple(params),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def create_audit_log(data: AuditLogCreate) -> str:
    """
    完整创建审核记录 — 传入 Pydantic 模型，返回 log_id。

    用法:
        from business.audit import create_audit_log, AuditLogCreate
        log_id = create_audit_log(AuditLogCreate(node_id="n1", batch_id="b1", input_snapshot="{...}"))
    """
    log_id = data.node_id and _uuid.uuid4().hex[:16] or _uuid.uuid4().hex[:16]
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO ontol_audit_log "
            "(id, node_id, batch_id, trigger_source, prompt_template, audit_status, "
            "llm_score, fail_reason, suggested_data, input_snapshot, create_user) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                log_id,
                data.node_id,
                data.batch_id,
                data.trigger_source,
                data.prompt_template,
                data.audit_status,
                None,  # llm_score
                None,  # fail_reason
                None,  # suggested_data
                data.input_snapshot,
                data.create_user,
            ),
        )
        conn.commit()
        return log_id
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# 更新 & 删除
# ═══════════════════════════════════════════════════════════════════

def update_audit_log(log_id: str, data: AuditLogUpdate) -> bool:
    """人工复核更新审核记录。返回 False 表示记录不存在。"""
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
        data_dict = data.model_dump(exclude_none=True)
        for key in updatable:
            if key in data_dict:
                fields.append(f"{key}=?")
                params.append(data_dict[key])
        if not fields:
            return True

        fields.append("update_time=datetime('now')")
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
            "update_time=datetime('now') WHERE id=?",
            (log_id,),
        )
        conn.commit()
    finally:
        conn.close()
