"""
对话元数据业务服务
-----------------
所有 ontol_char 表的 CRUD 逻辑集中于此。
路由层只做参数解析 + 调用本模块 + 格式化响应。

数据分工：
- ontol_char 表（DB）：对话 ID、名称、创建/更新时间
- localStorage（浏览器）：消息内容、场景绑定 ID 等运行时数据
"""
import sqlite3
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

def list_chats() -> list[dict[str, Any]]:
    """查询所有未删除的对话，按更新时间降序。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, name, code, create_time, update_time "
            "FROM ontol_char WHERE delete_flag='0' "
            "ORDER BY update_time DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_chat(chat_id: str) -> Optional[dict[str, Any]]:
    """获取单条对话记录，不存在返回 None。"""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, name, code, create_time, update_time "
            "FROM ontol_char WHERE id=? AND delete_flag='0'",
            (chat_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# 写
# ═══════════════════════════════════════════════════════════════════

def create_chat(chat_id: str, name: str = "新对话", code: str = "") -> str:
    """创建对话记录（INSERT OR REPLACE，兼容重复创建），返回 chat_id。"""
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO ontol_char (id, name, code, create_time, update_time) "
            "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            (chat_id, name, code),
        )
        conn.commit()
        return chat_id
    finally:
        conn.close()


def update_chat(chat_id: str, name: Optional[str] = None) -> bool:
    """更新对话名称。返回 False 表示不存在。"""
    conn = _connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM ontol_char WHERE id=? AND delete_flag='0'", (chat_id,)
        ).fetchone()
        if not exists:
            return False

        fields = []
        params: list = []
        if name is not None:
            fields.append("name=?")
            params.append(name)
        if not fields:
            return True

        fields.append("update_time=datetime('now')")
        params.append(chat_id)
        conn.execute(
            f"UPDATE ontol_char SET {', '.join(fields)} WHERE id=?",
            tuple(params),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def delete_chat(chat_id: str) -> None:
    """软删除对话记录。"""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE ontol_char SET delete_flag='1', update_time=datetime('now') "
            "WHERE id=?",
            (chat_id,),
        )
        conn.commit()
    finally:
        conn.close()
