"""
业务 API 层 — 外部调用唯一入口
=============================
其他模块/子系统调用业务功能的唯一入口。**禁止跨过本层直接 import domain 内部模块。**

约束:
    from business.api import submit_audit   # ✅ 唯一合法入口
    from business.audit import ...          # ❌ 绕过 API 层，禁止

本层不写业务逻辑，只做:
    - re-export（透传 domain 模块的对外函数）
    - 数据转换（外部格式 ↔ 内部格式）
    - 路由分发（一个入口 → 多个 domain）
"""
from business.audit.audit_service import (  # noqa: F401
    submit_audit,
    record_audit_result,
    query_by_node,
    query_by_batch,
    AuditLogCreate,
    AuditLogResult,
    AuditLogUpdate,
)

# ── 上传/导入四步骤 — 全自动导入管线 (auto_import/) ──
# Step 1: AI 本体解析
from business.upload.auto_import.step1_parse import run_parse_pipeline  # noqa: F401
# Step 2: 模板校验 & 字段补全
from business.upload.auto_import.step2_validate import validate_entities  # noqa: F401
# Step 3: 符号语言填充 & 推理机校验
from business.upload.auto_import.step3_enrich import (  # noqa: F401
    enrich_entities,
    EnrichResult,
    classify_prefix,
    PREFIX_MAP,
)
# Step 4: 导入 Memgraph 图数据库
from business.upload.auto_import.step4_import import import_to_graph  # noqa: F401
