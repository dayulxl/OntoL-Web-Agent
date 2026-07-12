"""
SQLite 文件数据库
----------------
自包含的文件数据库，无需外部 PostgreSQL 服务。
数据库文件 ontol.db 创建在 infrastructure/db/ 目录下。

接口兼容 BaseRepository 风格，参数占位符自动转为 ?。
"""
import asyncio
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "ontol.db"


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


_PG_PLACEHOLDER = re.compile(r'\$(\d+)')


def _adapt_pg_sql(sql: str, params: tuple) -> tuple[str, tuple]:
    matches = list(_PG_PLACEHOLDER.finditer(sql))
    if not matches:
        sql = sql.replace('ILIKE', 'LIKE')
        return sql, params
    new_params: list = []
    for m in matches:
        idx = int(m.group(1)) - 1
        if idx < len(params):
            new_params.append(params[idx])
        else:
            new_params.append(None)
    sql = _PG_PLACEHOLDER.sub('?', sql)
    sql = sql.replace('ILIKE', 'LIKE')
    return sql, tuple(new_params)


class _Conn:
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
        verb = (sql.strip().split() or [""])[0].upper()
        return f"{verb} {rowcount}"

    async def fetch(self, sql: str, *params: Any) -> list[dict]:
        return await asyncio.to_thread(self._run, sql, params)

    async def fetchrow(self, sql: str, *params: Any) -> Optional[dict]:
        return await asyncio.to_thread(self._run_one, sql, params)

    async def execute(self, sql: str, *params: Any) -> str:
        return await asyncio.to_thread(self._exec, sql, params)


class _AcquireContext:
    def __init__(self, conn: _Conn):
        self._conn = conn
    async def __aenter__(self) -> _Conn:
        return self._conn
    async def __aexit__(self, *args) -> None:
        pass


class _Pool:
    def __init__(self, path: str):
        self._conn = _Conn(path)
    def acquire(self) -> _AcquireContext:
        return _AcquireContext(self._conn)


_conn: Optional[_Conn] = None
_pool: Optional[_Pool] = None


async def create_sqlite_db(path: Optional[str] = None) -> _Pool:
    global _conn, _pool
    p = path or str(DB_PATH)
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    _conn = _Conn(p)
    _pool = _Pool(p)

    # ═══════════════════════════════════════════════════════════
    # 建表 (全部使用新列名: name / code)
    # ═══════════════════════════════════════════════════════════

    # ── 本体模型表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_model (
            id                TEXT PRIMARY KEY,
            ontol_parent_id   TEXT,
            name              TEXT    NOT NULL,
            ontol_model_type  TEXT    NOT NULL,
            ontol_model_status TEXT   NOT NULL DEFAULT '0',
            ontol_model_desc  TEXT,
            code              TEXT,
            create_id         TEXT,
            create_time       TEXT    NOT NULL DEFAULT (datetime('now')),
            update_id         TEXT,
            update_time       TEXT,
            delete_flag       TEXT    NOT NULL DEFAULT '0',
            is_system         TEXT    NOT NULL DEFAULT '0',
            FOREIGN KEY (ontol_parent_id) REFERENCES ontol_model(id) ON DELETE CASCADE
        )
    """)

    # ── 本体模型属性表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_model_attr (
            id                    TEXT PRIMARY KEY,
            ontol_model_id        TEXT    NOT NULL,
            name                  TEXT    NOT NULL,
            code                  TEXT    NOT NULL,
            attr_data_type        TEXT    NOT NULL DEFAULT 'VARCHAR',
            attr_length           TEXT,
            attr_digit            TEXT,
            attr_is_only          TEXT    NOT NULL DEFAULT '0',
            attr_cascade_colum    TEXT,
            attr_data_source_flag TEXT,
            attr_data_source      TEXT,
            attr_required         TEXT    NOT NULL DEFAULT '0',
            attr_default_value    TEXT,
            attr_is_system        TEXT    NOT NULL DEFAULT '0',
            attr_order            INTEGER NOT NULL DEFAULT 0,
            attr_desc             TEXT,
            create_id             TEXT,
            create_time           TEXT    NOT NULL DEFAULT (datetime('now')),
            delete_flag           TEXT    NOT NULL DEFAULT '0',
            is_system             TEXT    NOT NULL DEFAULT '0',
            FOREIGN KEY (ontol_model_id) REFERENCES ontol_model(id) ON DELETE CASCADE
        )
    """)

    # ── 场景表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_model_scene (
            id               TEXT PRIMARY KEY,
            name             TEXT    NOT NULL,
            scene_desc       TEXT,
            parent_scene_id  TEXT,
            code             TEXT,
            scene_is_system  TEXT    NOT NULL DEFAULT '0',
            create_id        TEXT,
            create_time      TEXT    NOT NULL DEFAULT (datetime('now')),
            delete_flag      TEXT    NOT NULL DEFAULT '0',
            is_system        TEXT    NOT NULL DEFAULT '0',
            FOREIGN KEY (parent_scene_id) REFERENCES ontol_model_scene(id) ON DELETE SET NULL
        )
    """)

    # ── 场景提示词表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_scene_prompt (
            id                 TEXT PRIMARY KEY,
            scene_id           TEXT    NOT NULL,
            name               TEXT    NOT NULL,
            prompt_content     TEXT    NOT NULL,
            prompt_desc        TEXT,
            prompt_description TEXT,
            create_id          TEXT,
            create_time        TEXT    NOT NULL DEFAULT (datetime('now')),
            delete_flag        TEXT    NOT NULL DEFAULT '0',
            is_system          TEXT    NOT NULL DEFAULT '0',
            FOREIGN KEY (scene_id) REFERENCES ontol_model_scene(id) ON DELETE CASCADE
        )
    """)

    # ── 场景词典表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_scene_dictionary (
            id                    TEXT PRIMARY KEY,
            scene_id              TEXT    NOT NULL,
            name                  TEXT    NOT NULL,
            code                  TEXT,
            dictionary_type_id    TEXT,
            dictionary_content    TEXT,
            create_time           TEXT    NOT NULL DEFAULT (datetime('now')),
            delete_flag           TEXT    NOT NULL DEFAULT '0',
            is_system             TEXT    NOT NULL DEFAULT '0',
            FOREIGN KEY (scene_id) REFERENCES ontol_model_scene(id) ON DELETE CASCADE,
            FOREIGN KEY (dictionary_type_id) REFERENCES ontol_dictionary_type(id) ON DELETE SET NULL
        )
    """)

    # ── 词典类型表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_dictionary_type (
            id                      TEXT PRIMARY KEY,
            name                    TEXT    NOT NULL,
            dictionary_description  TEXT,
            is_system               TEXT    NOT NULL DEFAULT '0',
            create_time             TEXT    NOT NULL DEFAULT (datetime('now')),
            delete_flag             TEXT    NOT NULL DEFAULT '0'
        )
    """)

    # ── 数据源类型表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_datasource_type (
            id                      TEXT PRIMARY KEY,
            name                    TEXT    NOT NULL,
            datasource_description  TEXT,
            is_system               TEXT    NOT NULL DEFAULT '0',
            create_time             TEXT    NOT NULL DEFAULT (datetime('now')),
            delete_flag             TEXT    NOT NULL DEFAULT '0'
        )
    """)

    # ── 数据源配置表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_datasource (
            id                       INTEGER PRIMARY KEY,
            name                     TEXT    NOT NULL,
            driver_class             TEXT    NOT NULL DEFAULT '',
            jdbc_url                 TEXT    NOT NULL DEFAULT '',
            username                 TEXT    NOT NULL DEFAULT '',
            password_cipher          TEXT    NOT NULL DEFAULT '',
            config_extra             TEXT    NOT NULL DEFAULT '{}',
            status                   INTEGER NOT NULL DEFAULT 1,
            created_by               TEXT    NOT NULL DEFAULT '',
            create_time              TEXT    NOT NULL DEFAULT (datetime('now')),
            ontol_datasource_type_id TEXT,
            is_system                TEXT    NOT NULL DEFAULT '0',
            FOREIGN KEY (ontol_datasource_type_id) REFERENCES ontol_datasource_type(id) ON DELETE SET NULL
        )
    """)

    # ── 数据源日志表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_datasource_log (
            id                    TEXT PRIMARY KEY,
            ontol_datasource_id   TEXT    NOT NULL,
            biz_id                TEXT    NOT NULL DEFAULT '',
            batch_no              TEXT,
            create_time           TEXT    NOT NULL DEFAULT (datetime('now')),
            is_system             TEXT    NOT NULL DEFAULT '0',
            FOREIGN KEY (ontol_datasource_id) REFERENCES ontol_datasource(id) ON DELETE CASCADE
        )
    """)

    # ── 场景词条关联表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_scene_dictionary_relation (
            id                           TEXT PRIMARY KEY,
            scene_id                     TEXT    NOT NULL,
            ontol_scene_dictionary_id    TEXT    NOT NULL,
            name                         TEXT    NOT NULL DEFAULT '',
            code                         TEXT    NOT NULL DEFAULT '',
            create_time                  TEXT    NOT NULL DEFAULT (datetime('now')),
            create_user                  TEXT    NOT NULL DEFAULT '',
            update_time                  TEXT    NOT NULL DEFAULT '',
            update_user                  TEXT    NOT NULL DEFAULT '',
            delete_flag                  INTEGER NOT NULL DEFAULT 0,
            is_system                    TEXT    NOT NULL DEFAULT '0',
            FOREIGN KEY (scene_id) REFERENCES ontol_model_scene(id) ON DELETE CASCADE,
            FOREIGN KEY (ontol_scene_dictionary_id) REFERENCES ontol_scene_dictionary(id) ON DELETE CASCADE
        )
    """)

    # ── LLM 模型配置表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_llm_config (
            id                  TEXT PRIMARY KEY,
            llm_type_config_id  TEXT,
            name                TEXT    NOT NULL,
            llm_model           TEXT,
            llm_url             TEXT,
            llm_key             TEXT,
            llm_description     TEXT,
            create_time         TEXT    NOT NULL DEFAULT (datetime('now')),
            delete_flag         TEXT    NOT NULL DEFAULT '0',
            is_system           TEXT    NOT NULL DEFAULT '0',
            FOREIGN KEY (llm_type_config_id) REFERENCES ontol_llm_type_config(id) ON DELETE SET NULL
        )
    """)

    # ── LLM 类型配置表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_llm_type_config (
            id               TEXT PRIMARY KEY,
            name             TEXT    NOT NULL,
            llm_description  TEXT,
            is_system        TEXT    NOT NULL DEFAULT '0',
            create_time      TEXT    NOT NULL DEFAULT (datetime('now')),
            delete_flag      TEXT    NOT NULL DEFAULT '0'
        )
    """)

    # ── 动态函数类型表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_function_type (
            id                      TEXT PRIMARY KEY,
            name                    TEXT    NOT NULL,
            function_description    TEXT,
            is_system               TEXT    NOT NULL DEFAULT '0',
            create_time             TEXT    NOT NULL DEFAULT (datetime('now')),
            delete_flag             TEXT    NOT NULL DEFAULT '0'
        )
    """)
    _conn._exec("CREATE INDEX IF NOT EXISTS idx_oft_del ON ontol_function_type(delete_flag)")

    # ── 动态函数配置表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_function (
            id                  TEXT PRIMARY KEY,
            function_type_id    TEXT,
            code                TEXT    NOT NULL,
            name                TEXT    NOT NULL DEFAULT '',
            function_classpath  TEXT,
            function_method     TEXT,
            function_type       TEXT    NOT NULL DEFAULT 'PYTHON',
            function_timeout_ms INTEGER NOT NULL DEFAULT 30000,
            function_max_retry  INTEGER NOT NULL DEFAULT 0,
            status              INTEGER NOT NULL DEFAULT 1,
            description         TEXT,
            create_time         TEXT    NOT NULL DEFAULT (datetime('now')),
            create_user         TEXT    NOT NULL DEFAULT '',
            update_time         TEXT    NOT NULL DEFAULT '',
            update_user         TEXT    NOT NULL DEFAULT '',
            delete_flag         TEXT    NOT NULL DEFAULT '0',
            is_system           TEXT    NOT NULL DEFAULT '0',
            FOREIGN KEY (function_type_id) REFERENCES ontol_function_type(id) ON DELETE SET NULL
        )
    """)

    # ── 副本版本关联表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_cope_version (
            id                  TEXT PRIMARY KEY,
            name                TEXT    NOT NULL DEFAULT '',
            code                TEXT    NOT NULL DEFAULT '',
            cope_version_status TEXT    NOT NULL DEFAULT '00',
            description         TEXT    NOT NULL DEFAULT '',
            init_note_id        TEXT    NOT NULL DEFAULT '',
            init_note_name      TEXT    NOT NULL DEFAULT '',
            confidence          REAL    NOT NULL DEFAULT 0.8,
            create_time         TEXT    NOT NULL DEFAULT (datetime('now')),
            create_user         TEXT    NOT NULL DEFAULT '',
            update_time         TEXT    NOT NULL DEFAULT '',
            update_user         TEXT    NOT NULL DEFAULT '',
            delete_flag         TEXT    NOT NULL DEFAULT '0',
            is_system           TEXT    NOT NULL DEFAULT '0'
        )
    """)

    # ── 对话-推演副本关联表 ──
    _conn._exec("""
        CREATE TABLE IF NOT EXISTS ontol_chat_cope_version_relation (
            id                TEXT PRIMARY KEY,
            name              TEXT    NOT NULL DEFAULT '',
            code              TEXT    NOT NULL DEFAULT '',
            chat_id           TEXT    NOT NULL DEFAULT '',
            cope_version_id   TEXT    NOT NULL DEFAULT '',
            create_time       TEXT    NOT NULL DEFAULT (datetime('now')),
            create_user       TEXT    NOT NULL DEFAULT '',
            update_time       TEXT    NOT NULL DEFAULT '',
            update_user       TEXT    NOT NULL DEFAULT '',
            delete_flag       TEXT    NOT NULL DEFAULT '0',
            is_system         TEXT    NOT NULL DEFAULT '0'
        )
    """)

    # ═══════════════════════════════════════════════════════════
    # 迁移：补全通用字段 (仅 ADD COLUMN，不做 RENAME)
    # ═══════════════════════════════════════════════════════════
    _MIGRATE_TABLES = [
        "ontol_model","ontol_model_attr","ontol_model_scene","ontol_scene_prompt",
        "ontol_scene_dictionary","ontol_dictionary_type","ontol_datasource_type",
        "ontol_datasource","ontol_datasource_log","ontol_scene_dictionary_relation",
        "ontol_llm_config","ontol_llm_type_config","ontol_function_type","ontol_function",
        "ontol_cope_version","ontol_chat_cope_version_relation",
    ]
    for tbl in _MIGRATE_TABLES:
        cols = [r["name"] for r in _conn._run(f"PRAGMA table_info('{tbl}')")]
        if "create_user" not in cols:
            _conn._exec(f"ALTER TABLE {tbl} ADD COLUMN create_user TEXT NOT NULL DEFAULT ''")
        if "update_time" not in cols:
            _conn._exec(f"ALTER TABLE {tbl} ADD COLUMN update_time TEXT NOT NULL DEFAULT ''")
        if "update_user" not in cols:
            _conn._exec(f"ALTER TABLE {tbl} ADD COLUMN update_user TEXT NOT NULL DEFAULT ''")
        if "delete_flag" not in cols:
            _conn._exec(f"ALTER TABLE {tbl} ADD COLUMN delete_flag TEXT NOT NULL DEFAULT '0'")
        if "is_system" not in cols:
            _conn._exec(f"ALTER TABLE {tbl} ADD COLUMN is_system TEXT NOT NULL DEFAULT '0'")

    # ── 专项：dictionary_type → dictionary_type_id ──
    osd_cols = [r["name"] for r in _conn._run("PRAGMA table_info('ontol_scene_dictionary')")]
    if "dictionary_type" in osd_cols and "dictionary_type_id" not in osd_cols:
        _conn._exec("ALTER TABLE ontol_scene_dictionary DROP COLUMN dictionary_type")
    if "dictionary_type_id" not in osd_cols:
        _conn._exec("ALTER TABLE ontol_scene_dictionary ADD COLUMN dictionary_type_id TEXT")

    # ── 专项：attr_order ──
    oma_cols = [r["name"] for r in _conn._run("PRAGMA table_info('ontol_model_attr')")]
    if "attr_order" not in oma_cols:
        _conn._exec("ALTER TABLE ontol_model_attr ADD COLUMN attr_order INTEGER NOT NULL DEFAULT 0")

    # ── 专项：llm_model ──
    olc_cols = [r["name"] for r in _conn._run("PRAGMA table_info('ontol_llm_config')")]
    if "llm_model" not in olc_cols:
        _conn._exec("ALTER TABLE ontol_llm_config ADD COLUMN llm_model TEXT")

    # ── 专项：关联表 name/code ──
    for tbl in ["ontol_scene_dictionary_relation"]:
        cols = [r["name"] for r in _conn._run(f"PRAGMA table_info('{tbl}')")]
        if "name" not in cols:
            _conn._exec(f"ALTER TABLE {tbl} ADD COLUMN name TEXT NOT NULL DEFAULT ''")
        if "code" not in cols:
            _conn._exec(f"ALTER TABLE {tbl} ADD COLUMN code TEXT NOT NULL DEFAULT ''")

    # ── 专项：ontol_cope_version 补充字段 ──
    ocvr_cols = [r["name"] for r in _conn._run("PRAGMA table_info('ontol_cope_version')")]
    if "description" not in ocvr_cols:
        _conn._exec("ALTER TABLE ontol_cope_version ADD COLUMN description TEXT NOT NULL DEFAULT ''")
    if "init_note_id" not in ocvr_cols:
        _conn._exec("ALTER TABLE ontol_cope_version ADD COLUMN init_note_id TEXT NOT NULL DEFAULT ''")
    if "init_note_name" not in ocvr_cols:
        _conn._exec("ALTER TABLE ontol_cope_version ADD COLUMN init_note_name TEXT NOT NULL DEFAULT ''")
    if "name" not in ocvr_cols:
        _conn._exec("ALTER TABLE ontol_cope_version ADD COLUMN name TEXT NOT NULL DEFAULT ''")
    if "code" not in ocvr_cols:
        _conn._exec("ALTER TABLE ontol_cope_version ADD COLUMN code TEXT NOT NULL DEFAULT ''")
    if "confidence" not in ocvr_cols:
        _conn._exec("ALTER TABLE ontol_cope_version ADD COLUMN confidence REAL NOT NULL DEFAULT 0.8")

    # ═══════════════════════════════════════════════════════════
    # 索引
    # ═══════════════════════════════════════════════════════════
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_om_parent ON ontol_model(ontol_parent_id)",
        "CREATE INDEX IF NOT EXISTS idx_om_type   ON ontol_model(ontol_model_type)",
        "CREATE INDEX IF NOT EXISTS idx_om_del    ON ontol_model(delete_flag)",
        "CREATE INDEX IF NOT EXISTS idx_oma_mid   ON ontol_model_attr(ontol_model_id)",
        "CREATE INDEX IF NOT EXISTS idx_oma_del   ON ontol_model_attr(delete_flag)",
    ]:
        _conn._exec(idx_sql)

    _conn._exec(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_om_code_active "
        "ON ontol_model(code) WHERE delete_flag = '0'"
    )

    _conn._exec("""
        DELETE FROM ontol_model_attr WHERE rowid NOT IN (
            SELECT MIN(rowid) FROM ontol_model_attr
            WHERE delete_flag = '0' GROUP BY code
        ) AND delete_flag = '0'
    """)
    _conn._exec(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_oma_code_active "
        "ON ontol_model_attr(code) WHERE delete_flag = '0'"
    )

    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_oms_del ON ontol_model_scene(delete_flag)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_osc_code_active ON ontol_model_scene(code) WHERE delete_flag='0' AND code IS NOT NULL AND code != ''",
    ]:
        _conn._exec(idx_sql)

    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_osp_scene ON ontol_scene_prompt(scene_id)",
        "CREATE INDEX IF NOT EXISTS idx_osp_del   ON ontol_scene_prompt(delete_flag)",
    ]:
        _conn._exec(idx_sql)

    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_osd_scene ON ontol_scene_dictionary(scene_id)",
        "CREATE INDEX IF NOT EXISTS idx_osd_del   ON ontol_scene_dictionary(delete_flag)",
    ]:
        _conn._exec(idx_sql)
    _conn._exec(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_osd_code_active "
        "ON ontol_scene_dictionary(code) WHERE delete_flag='0' AND code IS NOT NULL AND code != ''"
    )

    _conn._exec("CREATE INDEX IF NOT EXISTS idx_odt_del ON ontol_dictionary_type(delete_flag)")

    _conn._exec("CREATE INDEX IF NOT EXISTS idx_odst_del ON ontol_datasource_type(delete_flag)")
    _conn._exec(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_odst_name_active "
        "ON ontol_datasource_type(name) WHERE delete_flag = '0'"
    )

    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_odsl_dsid ON ontol_datasource_log(ontol_datasource_id)",
        "CREATE INDEX IF NOT EXISTS idx_odsl_biz   ON ontol_datasource_log(biz_id)",
        "CREATE INDEX IF NOT EXISTS idx_odsl_batch ON ontol_datasource_log(batch_no)",
        "CREATE INDEX IF NOT EXISTS idx_odsl_time  ON ontol_datasource_log(create_time)",
    ]:
        _conn._exec(idx_sql)

    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_osdr_scene ON ontol_scene_dictionary_relation(scene_id)",
        "CREATE INDEX IF NOT EXISTS idx_osdr_dict  ON ontol_scene_dictionary_relation(ontol_scene_dictionary_id)",
        "CREATE INDEX IF NOT EXISTS idx_osdr_del   ON ontol_scene_dictionary_relation(delete_flag)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_osdr_code_active ON ontol_scene_dictionary_relation(code) WHERE delete_flag = 0",
    ]:
        _conn._exec(idx_sql)

    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_olc_type ON ontol_llm_config(llm_type_config_id)",
        "CREATE INDEX IF NOT EXISTS idx_olc_del  ON ontol_llm_config(delete_flag)",
    ]:
        _conn._exec(idx_sql)

    _conn._exec("CREATE INDEX IF NOT EXISTS idx_oltc_del ON ontol_llm_type_config(delete_flag)")

    _conn._exec(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ofunc_code_active "
        "ON ontol_function(code) WHERE delete_flag = '0'"
    )
    _conn._exec("CREATE INDEX IF NOT EXISTS idx_ofunc_del ON ontol_function(delete_flag)")
    _conn._exec("CREATE INDEX IF NOT EXISTS idx_ofunc_type ON ontol_function(function_type)")

    _conn._exec("CREATE INDEX IF NOT EXISTS idx_ocv_del ON ontol_cope_version(delete_flag)")

    _conn._exec("CREATE INDEX IF NOT EXISTS idx_occvr_chat ON ontol_chat_cope_version_relation(chat_id)")
    _conn._exec("CREATE INDEX IF NOT EXISTS idx_occvr_cope ON ontol_chat_cope_version_relation(cope_version_id)")
    _conn._exec("CREATE INDEX IF NOT EXISTS idx_occvr_del ON ontol_chat_cope_version_relation(delete_flag)")

    # ═══════════════════════════════════════════════════════════
    # 种子数据
    # ═══════════════════════════════════════════════════════════
    now = _now()
    models = [
        ("M_ROOT",        "M_ROOT",             None,       "基本本体", "M0", "0", "所有本体模型的根节点",           "system", now),
        ("M_ENTITY",      "M_ENTITY",           "M_ROOT",   "实体",       "M1", "0", "可独立存在的物理或逻辑实体",       "system", now),
        ("M_BEHAVIOR",    "M_BEHAVIOR",         "M_ROOT",   "行为",       "M2", "0", "实体可执行的动作或操作",           "system", now),
        ("M_RULE",        "M_RULE",             "M_ROOT",   "规则",       "M3", "0", "约束、推理规则与业务逻辑",         "system", now),
        ("M_SCENE",       "M_SCENE",            "M_ROOT",   "场景",       "M4", "0", "实体行为发生的时空上下文",         "system", now),
        ("M_AGENT",       "M_AGENT",            "M_ROOT",   "主体",       "M5", "0", "具有自主决策能力的智能体",         "system", now),
        ("M_EXCEPTION",   "M_EXCEPTION",        "M_ROOT",   "异常补偿",   "M6", "0", "异常处理与补偿回滚机制",           "system", now),
        ("M_QUALITY",     "M_QUALITY",          "M_ROOT",   "质量约束",   "M7", "0", "数据质量校验约束与度量",           "system", now),
        ("M_EVENT",       "M_EVENT",            "M_ROOT",   "事件",       "ME", "0", "本体中发生的状态变化事件",         "system", now),
        ("M_TEMPLATE",    "M_TEMPLATE",         "M_ROOT",   "模板",       "MT", "0", "可复用的本体模板定义",             "system", now),
    ]
    for m in models:
        _conn._exec(
            "INSERT OR IGNORE INTO ontol_model(id,code,ontol_parent_id,name,ontol_model_type,ontol_model_status,ontol_model_desc,create_id,create_time) VALUES(?,?,?,?,?,?,?,?,?)",
            m,
        )

    a0 = None
    a1 = 0
    attrs = [
        ("ATTR_M1_ID",  "M_ENTITY",        "主键ID","id",  "VARCHAR","32", a0,"1",a0,a0,a0,"1",a0,"0",a1,"实体唯一标识符",      "system",now),
        ("ATTR_M1_NAME","M_ENTITY",        "名称",  "name","VARCHAR","100",a0,"0",a0,a0,a0,"1",a0,"0",a1,"实体名称",            "system",now),
        ("ATTR_M1_CODE","M_ENTITY",        "编码",  "code","VARCHAR","50", a0,"0",a0,a0,a0,"0",a0,"0",a1,"实体业务编码",        "system",now),
        ("ATTR_M1_DESC","M_ENTITY",        "描述",  "desc","VARCHAR","255",a0,"0",a0,a0,a0,"0",a0,"0",a1,"实体描述",            "system",now),
        ("ATTR_M2_ID",  "M_BEHAVIOR",      "主键ID","id",  "VARCHAR","32", a0,"1",a0,a0,a0,"1",a0,"0",a1,"行为唯一标识符",      "system",now),
        ("ATTR_M2_NAME","M_BEHAVIOR",      "名称",  "name","VARCHAR","100",a0,"0",a0,a0,a0,"1",a0,"0",a1,"行为名称",            "system",now),
        ("ATTR_M2_CODE","M_BEHAVIOR",      "编码",  "code","VARCHAR","50", a0,"0",a0,a0,a0,"0",a0,"0",a1,"行为业务编码",        "system",now),
        ("ATTR_M2_DESC","M_BEHAVIOR",      "描述",  "desc","VARCHAR","255",a0,"0",a0,a0,a0,"0",a0,"0",a1,"行为描述",            "system",now),
        ("ATTR_M4_ID",  "M_SCENE",         "主键ID","id",  "VARCHAR","32", a0,"1",a0,a0,a0,"1",a0,"0",a1,"场景唯一标识符",      "system",now),
        ("ATTR_M4_NAME","M_SCENE",         "名称",  "name","VARCHAR","100",a0,"0",a0,a0,a0,"1",a0,"0",a1,"场景名称",            "system",now),
        ("ATTR_M4_CODE","M_SCENE",         "编码",  "code","VARCHAR","50", a0,"0",a0,a0,a0,"0",a0,"0",a1,"场景业务编码",        "system",now),
        ("ATTR_M4_DESC","M_SCENE",         "描述",  "desc","VARCHAR","255",a0,"0",a0,a0,a0,"0",a0,"0",a1,"场景描述",            "system",now),
        ("ATTR_M5_ID",  "M_AGENT",         "主键ID","id",  "VARCHAR","32", a0,"1",a0,a0,a0,"1",a0,"0",a1,"主体唯一标识符",      "system",now),
        ("ATTR_M5_NAME","M_AGENT",         "名称",  "name","VARCHAR","100",a0,"0",a0,a0,a0,"1",a0,"0",a1,"主体名称",            "system",now),
        ("ATTR_M5_CODE","M_AGENT",         "编码",  "code","VARCHAR","50", a0,"0",a0,a0,a0,"0",a0,"0",a1,"主体业务编码",        "system",now),
        ("ATTR_M5_DESC","M_AGENT",         "描述",  "desc","VARCHAR","255",a0,"0",a0,a0,a0,"0",a0,"0",a1,"主体描述",            "system",now),
    ]
    for a in attrs:
        _conn._exec(
            "INSERT OR IGNORE INTO ontol_model_attr(id,ontol_model_id,name,code,attr_data_type,attr_length,attr_digit,attr_is_only,attr_cascade_colum,attr_data_source_flag,attr_data_source,attr_required,attr_default_value,attr_is_system,attr_order,attr_desc,create_id,create_time) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
