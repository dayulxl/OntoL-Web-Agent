"""
SQLite 文件数据库
----------------
自包含的文件数据库，无需外部 PostgreSQL 服务。
数据库文件 ontol.db 创建在 infrastructure/db/ 目录下。

接口兼容 BaseRepository 风格，参数占位符自动转为 ?。
"""
import asyncio
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(__file__).parent / "ontol.db"


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


# 匹配 PostgreSQL 风格占位符 $1, $2, ... 及其数字索引
_PG_PLACEHOLDER = re.compile(r'\$(\d+)')


def _adapt_pg_sql(sql: str, params: tuple) -> tuple[str, tuple]:
    """将 PostgreSQL SQL + 参数转换为 SQLite 兼容形式。

    处理：
    - $1, $2, ... 占位符 → ? （按出现顺序展开参数）
    - ILIKE → LIKE
    - 同一 $N 多次出现时，自动复制对应参数值
    """
    matches = list(_PG_PLACEHOLDER.finditer(sql))
    if not matches:
        sql = sql.replace('ILIKE', 'LIKE')
        return sql, params

    # 按 $N 出现顺序构建新参数列表
    new_params: list = []
    for m in matches:
        idx = int(m.group(1)) - 1  # $1 → params[0]
        if idx < len(params):
            new_params.append(params[idx])
        else:
            new_params.append(None)  # 超出范围（通常不会发生）

    # 替换所有 $N → ?
    sql = _PG_PLACEHOLDER.sub('?', sql)
    sql = sql.replace('ILIKE', 'LIKE')
    return sql, tuple(new_params)


class _Conn:
    """同步 sqlite3 连接的轻量异步包装。"""

    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def _run(self, sql: str, params: tuple = ()) -> list[dict]:
        sql, params = _adapt_pg_sql(sql, params)
        cur = self._conn.execute(sql, params)
        rows = cur.fetchall()
        self._conn.commit()
        return [dict(r) for r in rows]

    def _run_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        rows = self._run(sql, params)
        return rows[0] if rows else None

    def _exec(self, sql: str, params: tuple = ()) -> str:
        sql, params = _adapt_pg_sql(sql, params)
        cur = self._conn.execute(sql, params)
        rowcount = cur.rowcount
        self._conn.commit()
        # 兼容 BaseRepository.delete() 的返回值匹配 ("UPDATE 1" / "DELETE 1")
        verb = sql.strip().split()[0].upper()
        return f"{verb} {rowcount}"

    async def fetch(self, sql: str, *params: Any) -> list[dict]:
        return await asyncio.to_thread(self._run, sql, params)

    async def fetchrow(self, sql: str, *params: Any) -> Optional[dict]:
        return await asyncio.to_thread(self._run_one, sql, params)

    async def execute(self, sql: str, *params: Any) -> str:
        return await asyncio.to_thread(self._exec, sql, params)


class _AcquireContext:
    """异步上下文管理器，模拟 asyncpg pool.acquire() 的返回对象。"""

    def __init__(self, conn: _Conn):
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *args) -> None:
        pass


class _Pool:
    """伪连接池 — 单连接实现 acquire() 兼容接口，支持 async with。"""

    def __init__(self, path: str):
        self._conn = _Conn(path)

    def acquire(self) -> _AcquireContext:
        return _AcquireContext(self._conn)


_conn: Optional[_Conn] = None
_pool: Optional[_Pool] = None


async def create_sqlite_db(path: Optional[str] = None) -> _Pool:
    """初始化 SQLite 数据库，建表 + 种子数据。"""
    global _conn, _pool
    p = path or str(DB_PATH)
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    _conn = _Conn(p)
    _pool = _Pool(p)

    # ------------------------------------------------------------------
    # 建表
    # ------------------------------------------------------------------
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_model (
            id                TEXT PRIMARY KEY,
            ontol_parent_id   TEXT,
            ontol_name        TEXT    NOT NULL,
            ontol_model_type  TEXT    NOT NULL,
            ontol_model_status TEXT   NOT NULL DEFAULT '0',
            ontol_model_desc  TEXT,
            create_id         TEXT,
            create_time       TEXT    NOT NULL DEFAULT (datetime('now')),
            update_id         TEXT,
            update_time       TEXT,
            delete_flag       TEXT    NOT NULL DEFAULT '0',
            FOREIGN KEY (ontol_parent_id) REFERENCES ontol_model(id) ON DELETE CASCADE
        )
    """)
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_model_attr (
            id                    TEXT PRIMARY KEY,
            ontol_model_id        TEXT    NOT NULL,
            attr_name             TEXT    NOT NULL,
            attr_code             TEXT    NOT NULL,
            attr_data_type        TEXT    NOT NULL DEFAULT '0',
            attr_length           TEXT,
            attr_digit            TEXT,
            attr_is_only          TEXT    NOT NULL DEFAULT '0',
            attr_cascade_colum    TEXT,
            attr_data_source_flag TEXT,
            attr_data_source      TEXT,
            attr_required         TEXT    NOT NULL DEFAULT '0',
            attr_default_value    TEXT,
            attr_relation_flag    TEXT    NOT NULL DEFAULT '0',
            attr_desc             TEXT,
            create_id             TEXT,
            create_time           TEXT    NOT NULL DEFAULT (datetime('now')),
            delete_flag           TEXT    NOT NULL DEFAULT '0',
            FOREIGN KEY (ontol_model_id) REFERENCES ontol_model(id) ON DELETE CASCADE
        )
    """)

    # 索引
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_om_parent ON ontol_model(ontol_parent_id)",
        "CREATE INDEX IF NOT EXISTS idx_om_type   ON ontol_model(ontol_model_type)",
        "CREATE INDEX IF NOT EXISTS idx_om_del    ON ontol_model(delete_flag)",
        "CREATE INDEX IF NOT EXISTS idx_oma_mid   ON ontol_model_attr(ontol_model_id)",
        "CREATE INDEX IF NOT EXISTS idx_oma_del   ON ontol_model_attr(delete_flag)",
    ]:
        _conn._exec(idx_sql)

    # ------------------------------------------------------------------
    # 种子数据
    # ------------------------------------------------------------------
    now = _now()
    models = [
        ("M_ROOT",           None,       "本体根节点", "M1", "0", "所有本体模型的根节点",           "system", now),
        ("M_ENTITY",         "M_ROOT",   "实体",       "M1", "0", "可独立存在的物理或逻辑实体",       "system", now),
        ("M_BEHAVIOR",       "M_ROOT",   "行为",       "M2", "0", "实体可执行的动作或操作",           "system", now),
        ("M_RULE",           "M_ROOT",   "规则",       "M3", "0", "约束、推理规则与业务逻辑",         "system", now),
        ("M_SCENE",          "M_ROOT",   "场景",       "M4", "0", "实体行为发生的时空上下文",         "system", now),
        ("M_AGENT",          "M_ROOT",   "主体",       "M5", "0", "具有自主决策能力的智能体",         "system", now),
        ("M_EXCEPTION",      "M_ROOT",   "异常补偿",   "M6", "0", "异常处理与补偿回滚机制",           "system", now),
        ("M_QUALITY",        "M_ROOT",   "质量约束",   "M7", "0", "数据质量校验约束与度量",           "system", now),
        ("M_EVENT",          "M_ROOT",   "事件",       "ME", "0", "本体中发生的状态变化事件",         "system", now),
        ("M_TEMPLATE",       "M_ROOT",   "模板",       "MT", "0", "可复用的本体模板定义",             "system", now),
        ("M_BASE_ONTOLOGY",  "M_ROOT",   "基本本体",   "M1", "0", "基础本体模型，定义通用属性和关系", "system", now),
    ]
    for m in models:
        _conn._exec(
            "INSERT OR IGNORE INTO ontol_model(id,ontol_parent_id,ontol_name,ontol_model_type,ontol_model_status,ontol_model_desc,create_id,create_time) VALUES(?,?,?,?,?,?,?,?)",
            m,
        )

    # cols: id, ontol_model_id, attr_name, attr_code, attr_data_type, attr_length, attr_digit,
    #       attr_is_only, attr_cascade_colum, attr_data_source_flag, attr_data_source,
    #       attr_required, attr_default_value, attr_relation_flag, attr_desc, create_id, create_time
    a0 = None  # placeholder for nullable fields
    attrs = [
        ("ATTR_M1_ID",  "M_ENTITY",        "主键ID","id",  "0","32", a0,"1",a0,a0,a0,"1",a0,"0","实体唯一标识符",      "system",now),
        ("ATTR_M1_NAME","M_ENTITY",        "名称",  "name","0","100",a0,"0",a0,a0,a0,"1",a0,"0","实体名称",            "system",now),
        ("ATTR_M1_CODE","M_ENTITY",        "编码",  "code","0","50", a0,"0",a0,a0,a0,"0",a0,"0","实体业务编码",        "system",now),
        ("ATTR_M1_DESC","M_ENTITY",        "描述",  "desc","0","255",a0,"0",a0,a0,a0,"0",a0,"0","实体描述",            "system",now),
        ("ATTR_M2_ID",  "M_BEHAVIOR",      "主键ID","id",  "0","32", a0,"1",a0,a0,a0,"1",a0,"0","行为唯一标识符",      "system",now),
        ("ATTR_M2_NAME","M_BEHAVIOR",      "名称",  "name","0","100",a0,"0",a0,a0,a0,"1",a0,"0","行为名称",            "system",now),
        ("ATTR_M2_CODE","M_BEHAVIOR",      "编码",  "code","0","50", a0,"0",a0,a0,a0,"0",a0,"0","行为业务编码",        "system",now),
        ("ATTR_M2_DESC","M_BEHAVIOR",      "描述",  "desc","0","255",a0,"0",a0,a0,a0,"0",a0,"0","行为描述",            "system",now),
        ("ATTR_M4_ID",  "M_SCENE",         "主键ID","id",  "0","32", a0,"1",a0,a0,a0,"1",a0,"0","场景唯一标识符",      "system",now),
        ("ATTR_M4_NAME","M_SCENE",         "名称",  "name","0","100",a0,"0",a0,a0,a0,"1",a0,"0","场景名称",            "system",now),
        ("ATTR_M4_CODE","M_SCENE",         "编码",  "code","0","50", a0,"0",a0,a0,a0,"0",a0,"0","场景业务编码",        "system",now),
        ("ATTR_M4_DESC","M_SCENE",         "描述",  "desc","0","255",a0,"0",a0,a0,a0,"0",a0,"0","场景描述",            "system",now),
        ("ATTR_M5_ID",  "M_AGENT",         "主键ID","id",  "0","32", a0,"1",a0,a0,a0,"1",a0,"0","主体唯一标识符",      "system",now),
        ("ATTR_M5_NAME","M_AGENT",         "名称",  "name","0","100",a0,"0",a0,a0,a0,"1",a0,"0","主体名称",            "system",now),
        ("ATTR_M5_CODE","M_AGENT",         "编码",  "code","0","50", a0,"0",a0,a0,a0,"0",a0,"0","主体业务编码",        "system",now),
        ("ATTR_M5_DESC","M_AGENT",         "描述",  "desc","0","255",a0,"0",a0,a0,a0,"0",a0,"0","主体描述",            "system",now),
        ("ATTR_BO_ID",  "M_BASE_ONTOLOGY", "主键ID","id",  "0","32", a0,"1",a0,a0,a0,"1",a0,"0","基本本体唯一标识符",  "system",now),
        ("ATTR_BO_NAME","M_BASE_ONTOLOGY", "名称",  "name","0","100",a0,"0",a0,a0,a0,"1",a0,"0","基本本体名称",        "system",now),
        ("ATTR_BO_CODE","M_BASE_ONTOLOGY", "编码",  "code","0","50", a0,"0",a0,a0,a0,"0",a0,"0","基本本体业务编码",    "system",now),
        ("ATTR_BO_DESC","M_BASE_ONTOLOGY", "描述",  "desc","0","255",a0,"0",a0,a0,a0,"0",a0,"0","基本本体描述",        "system",now),
    ]
    for a in attrs:
        _conn._exec(
            "INSERT OR IGNORE INTO ontol_model_attr(id,ontol_model_id,attr_name,attr_code,attr_data_type,attr_length,attr_digit,attr_is_only,attr_cascade_colum,attr_data_source_flag,attr_data_source,attr_required,attr_default_value,attr_relation_flag,attr_desc,create_id,create_time) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            a,
        )

    return _pool


def get_sqlite_pool() -> _Pool:
    global _pool
    if _pool is None:
        raise RuntimeError("SQLite not initialized. Call create_sqlite_db() first.")
    return _pool


def get_sqlite_conn() -> _Conn:
    global _conn
    if _conn is None:
        raise RuntimeError("SQLite not initialized.")
    return _conn
