"""
数据管理 API 路由
----------------
数据源配置 + 数据源类型 的 CRUD。
"""
import json
from typing import Optional
from pathlib import Path as _Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["DataManage"])

DB_PATH = _Path("infrastructure/db/ontol.db")

# =========================================================================
# 通用 SQLite 查询辅助
# =========================================================================

def _q(sql: str, params: tuple = ()) -> list[dict]:
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _exec(sql: str, params: tuple = ()) -> int:
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    try:
        c = conn.execute(sql, params)
        conn.commit()
        return c.lastrowid or 0
    finally:
        conn.close()


# =========================================================================
# 数据源配置 CRUD
# =========================================================================

class DatasourceCreate(BaseModel):
    name: str = Field(..., description="数据源名称")
    ontol_datasource_type_id: str = Field("", description="数据源类型ID (关联 ontol_datasource_type)")
    driver_class: str = Field("", description="JDBC 驱动类名")
    jdbc_url: str = Field("", description="连接字符串")
    username: str = Field("", description="用户名")
    password_cipher: str = Field("", description="加密后的密码")
    config_extra: str = Field("{}", description="额外配置 JSON")
    status: int = Field(1, description="状态 0-禁用 1-启用")
    created_by: str = Field("", description="创建人")


class DatasourceUpdate(BaseModel):
    name: Optional[str] = None
    ontol_datasource_type_id: Optional[str] = None
    driver_class: Optional[str] = None
    jdbc_url: Optional[str] = None
    username: Optional[str] = None
    password_cipher: Optional[str] = None
    config_extra: Optional[str] = None
    status: Optional[int] = None


@router.get("/datamanage/datasources")
async def list_datasources():
    return _q("SELECT * FROM ontol_datasource ORDER BY create_time DESC")


@router.get("/datamanage/datasources/{ds_id}")
async def get_datasource(ds_id: int):
    rows = _q("SELECT * FROM ontol_datasource WHERE id=?", (ds_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return rows[0]


@router.post("/datamanage/datasources", status_code=201)
async def create_datasource(body: DatasourceCreate):
    rid = _exec(
        "INSERT INTO ontol_datasource (name,ontol_datasource_type_id,driver_class,jdbc_url,username,password_cipher,config_extra,status,created_by) VALUES (?,?,?,?,?,?,?,?,?)",
        (body.name, body.ontol_datasource_type_id, body.driver_class, body.jdbc_url, body.username, body.password_cipher, body.config_extra, body.status, body.created_by),
    )
    return await get_datasource(rid)


@router.put("/datamanage/datasources/{ds_id}")
async def update_datasource(ds_id: int, body: DatasourceUpdate):
    rows = _q("SELECT id FROM ontol_datasource WHERE id=?", (ds_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="数据源不存在")
    sets, params = [], []
    for k, v in body.model_dump(exclude_none=True).items():
        if v is not None:
            sets.append(f"{k}=?")
            params.append(v)
    if sets:
        params.append(ds_id)
        _exec(f"UPDATE ontol_datasource SET {', '.join(sets)} WHERE id=?", tuple(params))
    return await get_datasource(ds_id)


@router.delete("/datamanage/datasources/{ds_id}")
async def delete_datasource(ds_id: int):
    _exec("DELETE FROM ontol_datasource WHERE id=?", (ds_id,))
    return {"deleted": True, "id": ds_id}


# =========================================================================
# 数据源类型 CRUD
# =========================================================================

class DatasourceTypeCreate(BaseModel):
    name: str = Field(..., description="类型名称")
    datasource_description: str = Field("", description="描述")
    is_system: str = Field("0", description="0=自定义 1=系统预设")


class DatasourceTypeUpdate(BaseModel):
    name: Optional[str] = None
    datasource_description: Optional[str] = None


@router.get("/datamanage/datasource-types")
async def list_datasource_types():
    return _q("SELECT * FROM ontol_datasource_type WHERE delete_flag='0' ORDER BY is_system DESC, create_time ASC")


@router.get("/datamanage/datasource-types/{id}")
async def get_datasource_type(id: str):
    rows = _q("SELECT * FROM ontol_datasource_type WHERE id=? AND delete_flag='0'", (id,))
    if not rows:
        raise HTTPException(status_code=404, detail="数据源类型不存在")
    return rows[0]


@router.post("/datamanage/datasource-types", status_code=201)
async def create_datasource_type(body: DatasourceTypeCreate):
    import uuid as _uuid
    tid = _uuid.uuid4().hex[:16]
    _exec(
        "INSERT INTO ontol_datasource_type (id,name,datasource_description,is_system) VALUES (?,?,?,?)",
        (tid, body.name, body.datasource_description, body.is_system),
    )
    return await get_datasource_type(tid)


@router.put("/datamanage/datasource-types/{id}")
async def update_datasource_type(id: str, body: DatasourceTypeUpdate):
    rows = _q("SELECT id,is_system FROM ontol_datasource_type WHERE id=? AND delete_flag='0'", (id,))
    if not rows:
        raise HTTPException(status_code=404, detail="数据源类型不存在")
    if rows[0]["is_system"] == "1":
        raise HTTPException(status_code=403, detail="系统预设类型不可修改")
    sets, params = [], []
    for k, v in body.model_dump(exclude_none=True).items():
        if v is not None:
            sets.append(f"{k}=?")
            params.append(v)
    if sets:
        params.append(id)
        _exec(f"UPDATE ontol_datasource_type SET {', '.join(sets)} WHERE id=?", tuple(params))
    return await get_datasource_type(id)


@router.delete("/datamanage/datasource-types/{id}")
async def delete_datasource_type(id: str):
    rows = _q("SELECT is_system FROM ontol_datasource_type WHERE id=? AND delete_flag='0'", (id,))
    if not rows:
        raise HTTPException(status_code=404, detail="数据源类型不存在")
    if rows[0]["is_system"] == "1":
        raise HTTPException(status_code=403, detail="系统预设类型不可删除")
    _exec("UPDATE ontol_datasource_type SET delete_flag='1' WHERE id=?", (id,))
    return {"deleted": True, "id": id}


# =========================================================================
# 数据源日志查询
# =========================================================================


@router.get("/datamanage/datasource-logs")
async def list_datasource_logs(
    datasource_id: str = "",
    biz_id: str = "",
    batch_no: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    page_size: int = 50,
):
    """查询 ontol_datasource_log，关联数据源名称，支持筛选 + 分页。"""
    where = []
    params: list = []

    if datasource_id:
        where.append("l.ontol_datasource_id = ?")
        params.append(datasource_id)
    if biz_id:
        where.append("l.biz_id LIKE ?")
        params.append(f"%{biz_id}%")
    if batch_no:
        where.append("l.batch_no LIKE ?")
        params.append(f"%{batch_no}%")
    if date_from:
        where.append("l.create_time >= ?")
        params.append(date_from)
    if date_to:
        where.append("l.create_time <= ?")
        params.append(date_to + " 23:59:59.999")

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""

    # 总数
    count_row = _q(
        f"SELECT count(*) as cnt FROM ontol_datasource_log l {where_clause}",
        tuple(params),
    )
    total = count_row[0]["cnt"] if count_row else 0

    # 分页数据（LEFT JOIN 关联数据源名称）
    offset = (page - 1) * page_size
    rows = _q(
        f"""SELECT l.*, d.name as datasource_name
            FROM ontol_datasource_log l
            LEFT JOIN ontol_datasource d ON CAST(d.id AS TEXT) = l.ontol_datasource_id
            {where_clause}
            ORDER BY l.create_time DESC
            LIMIT ? OFFSET ?""",
        tuple(params) + (page_size, offset),
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size) if total else 0,
        "data": rows,
    }


@router.get("/datamanage/datasource-logs/stats")
async def datasource_log_stats():
    """日志概览统计。"""
    total = _q("SELECT count(*) as cnt FROM ontol_datasource_log")[0]["cnt"]
    today = _q(
        "SELECT count(*) as cnt FROM ontol_datasource_log WHERE date(create_time) = date('now')"
    )[0]["cnt"]
    return {"total": total, "today": today}


# =========================================================================
# 总览统计
# =========================================================================

@router.get("/datamanage/stats")
async def datamanage_stats():
    def _safe_stat(sql):
        rows = _q(sql)
        return (rows[0]["cnt"] if rows else 0)
    ds = _safe_stat("SELECT count(*) as cnt FROM ontol_datasource")
    tp = _safe_stat("SELECT count(*) as cnt FROM ontol_datasource_type WHERE delete_flag='0'")
    return {"datasources": ds, "datasource_types": tp}
