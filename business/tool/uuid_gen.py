"""
统一 ID 生成器 — 全项目唯一 ID 生成入口
========================================
所有模块需要生成主键 ID 时，必须调用此模块，禁止 inline `uuid.uuid4().hex[:16]`。

    from business.tool.uuid_gen import new_id
    record_id = new_id()   # → "a1b2c3d4e5f6a7b8" (16位 hex)

对标 Snowflake 的 `generate_snowflake_ids` — 图节点用 Snowflake int64，SQLite 元数据用 new_id() hex。
"""
import uuid as _uuid


def new_id() -> str:
    """生成全局唯一的 16 位十六进制 ID（UUID4 截取前 16 字符）。

    等价于 uuid.uuid4().hex[:16]，16^16 ≈ 1.8×10^19 空间，碰撞概率可忽略。
    全项目统一入口，便于后续替换生成策略（如加前缀/时间戳前缀）。
    """
    return _uuid.uuid4().hex[:16]
