"""
审核记录业务域 — ontol_audit_log 表 CRUD + 便捷调用入口。

其他模块调用示例:
    from business.audit import submit_audit, record_audit_result

    # 1. 提交审核
    log_id = submit_audit("node_123", batch_id="B001", input_snapshot=json.dumps(data))

    # 2. LLM 审核完成后回写结果
    record_audit_result(log_id, audit_status="PASS", llm_score=0.95, model_version="gpt-4")

    # 3. 查询某个节点的审核历史
    from business.audit import query_by_node
    history = query_by_node("node_123")
"""

from business.audit.audit_service import (  # noqa: F401
    # 便捷函数（其他模块最常用）
    submit_audit,
    record_audit_result,
    # 查询
    list_audit_logs,
    get_audit_log,
    query_by_batch,
    query_by_node,
    # 完整 CRUD
    create_audit_log,
    update_audit_log,
    delete_audit_log,
    # Pydantic 模型
    AuditLogCreate,
    AuditLogResult,
    AuditLogUpdate,
)
