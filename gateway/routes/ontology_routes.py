"""
本体建模 API 路由
----------------
提供图数据库（Memgraph/Neo4j）的节点/关系 CRUD、Schema 发现和图遍历接口。
"""
from typing import Optional
from pathlib import Path as _Path
import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from common.exceptions.base import InfrastructureError

router = APIRouter(tags=["Ontology"])


# =========================================================================
# Pydantic 模型
# =========================================================================

class NodeCreate(BaseModel):
    label: str = Field(..., description="节点标签", examples=["Entity"])
    properties: dict = Field(default_factory=dict, description="节点属性", examples=[{"name": "航母战斗群", "type": "海军编队"}])

class NodeUpdate(BaseModel):
    properties: dict = Field(..., description="要更新的属性")

class EdgeCreate(BaseModel):
    source_id: int = Field(..., description="起始节点 ID")
    target_id: int = Field(..., description="目标节点 ID")
    rel_type: str = Field(..., description="关系类型", examples=["DEPLOYED_TO"])
    properties: Optional[dict] = Field(default_factory=dict, description="关系属性")

class CypherQuery(BaseModel):
    query: str = Field(..., description="只读 Cypher 语句")
    params: Optional[dict] = Field(default_factory=dict, description="查询参数")


class ToolsCallBody(BaseModel):
    name: str = Field(..., description="工具名称（如 infer_forward）")
    arguments: dict = Field(default_factory=dict, description="工具参数")


# ── ontol_model / ontol_model_attr 请求体 ──

class OntolModelCreateBody(BaseModel):
    model_config = {"extra": "ignore"}

    ontol_code: str = Field(..., max_length=50, description="本体编码（唯一）")
    ontol_parent_id: Optional[str] = Field(None, max_length=32, description="父级模型ID")
    ontol_name: str = Field(..., max_length=50, description="本体名称")
    ontol_model_type: str = Field(..., max_length=2, description="本体类型：M1/M2/M3/M4/M5/M6/M7/ME/MT")
    ontol_model_status: str = Field("0", max_length=2, description="本体状态：0=启用中 1=已停用")
    ontol_model_desc: Optional[str] = Field(None, max_length=255, description="本体描述")

class OntolModelUpdateBody(BaseModel):
    model_config = {"extra": "ignore"}
    ontol_code: Optional[str] = Field(None, max_length=50)
    ontol_name: Optional[str] = Field(None, max_length=50)
    ontol_model_type: Optional[str] = Field(None, max_length=2)
    ontol_model_status: Optional[str] = Field(None, max_length=2)
    ontol_model_desc: Optional[str] = Field(None, max_length=255)

class OntolModelAttrCreateBody(BaseModel):
    model_config = {"extra": "ignore"}

    id: str = Field(..., max_length=32, description="属性ID（主键）")
    ontol_model_id: Optional[str] = Field(None, max_length=32)
    attr_name: str = Field(..., max_length=50)
    attr_code: str = Field(..., max_length=50)
    attr_data_type: str = Field("0", max_length=2)
    attr_length: Optional[str] = Field(None, max_length=10)
    attr_digit: Optional[str] = Field(None, max_length=10)
    attr_is_only: Optional[str] = Field("0", max_length=2)
    attr_cascade_colum: Optional[str] = Field(None, max_length=50)
    attr_data_source_flag: Optional[str] = Field(None, max_length=2)
    attr_data_source: Optional[str] = Field(None, max_length=255)
    attr_required: Optional[str] = Field("0", max_length=2)
    attr_default_value: Optional[str] = Field(None, max_length=500)
    attr_is_system: Optional[str] = Field("0", max_length=2)
    attr_desc: Optional[str] = Field(None, max_length=50)

class OntolModelAttrUpdateBody(BaseModel):
    model_config = {"extra": "ignore"}

    attr_name: Optional[str] = Field(None, max_length=50)
    attr_code: Optional[str] = Field(None, max_length=50)
    attr_data_type: Optional[str] = Field(None, max_length=2)
    attr_length: Optional[str] = Field(None, max_length=10)
    attr_digit: Optional[str] = Field(None, max_length=10)
    attr_is_only: Optional[str] = Field(None, max_length=2)
    attr_cascade_colum: Optional[str] = Field(None, max_length=50)
    attr_data_source_flag: Optional[str] = Field(None, max_length=2)
    attr_data_source: Optional[str] = Field(None, max_length=255)
    attr_required: Optional[str] = Field(None, max_length=2)
    attr_default_value: Optional[str] = Field(None, max_length=500)
    attr_is_system: Optional[str] = Field(None, max_length=2)
    attr_desc: Optional[str] = Field(None, max_length=50)


# =========================================================================
# 依赖注入
# =========================================================================

async def get_graph():
    """
    获取 GraphMemory 实例（惰性导入，避免启动时图数据库未就绪而崩溃）。
    """
    from infrastructure.db.neo4j import get_driver
    from capabilities.memory.graph_memory import GraphMemory

    try:
        driver = await get_driver()
    except InfrastructureError:
        raise HTTPException(status_code=503, detail="Graph DB driver not initialized")
    return GraphMemory(driver)

async def get_ontology_repo():
    """获取 OntologyRepo 实例。"""
    from infrastructure.db.sqlite_db import get_sqlite_pool
    from infrastructure.db.ontology_repo import OntologyRepo
    try:
        pool = get_sqlite_pool()
        return OntologyRepo(pool)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database not available: {e}")


# =========================================================================
# 历史记录辅助
# =========================================================================

async def _record_history(node_id: str, action: str, context: dict, create_id: str = ""):
    """将图数据变更写入 ontol_data_his 历史表。"""
    import uuid as _uuid
    record = {
        "id": _uuid.uuid4().hex[:16],
        "node_id": str(node_id),
        "action": action,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        **context,
    }
    try:
        await _execute_scene(
            "INSERT INTO ontol_data_his (id, node_id, context, create_id) VALUES (?,?,?,?)",
            (record["id"], str(node_id), json.dumps(record, ensure_ascii=False), create_id),
        )
    except Exception:
        pass  # 历史记录失败不影响主流程


async def _bump_node_version(graph, node_id: int, node_name: str = ""):
    """递增图节点版本号。"""
    try:
        from infrastructure.db.neo4j import get_driver
        driver = await get_driver()
        async with driver.session() as session:
            # 读取当前版本号
            result = await session.run(
                "MATCH (n) WHERE id(n) = $node_id "
                "RETURN coalesce(n.version, '0') AS ver, n.name AS name",
                node_id=node_id,
            )
            rec = await result.single()
            if rec:
                old_ver = int(rec["ver"]) if rec["ver"] and str(rec["ver"]).isdigit() else 0
                new_ver = str(old_ver + 1)
                await session.run(
                    "MATCH (n) WHERE id(n) = $node_id SET n.version = $ver",
                    node_id=node_id, ver=new_ver,
                )
    except Exception:
        pass  # 版本号失败不影响主流程


# =========================================================================
# Schema
# =========================================================================

@router.get("/ontology/schema")
async def ontology_schema(graph=Depends(get_graph)):
    """获取图 Schema：所有标签、关系类型、节点和边计数。"""
    try:
        return await graph.get_schema()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Graph DB query failed: {e}")


# =========================================================================
# Neighborhood — 图邻域查询
# =========================================================================

@router.get("/ontology/neighborhood/{node_id}")
async def get_neighborhood(node_id: int, depth: int = 1, graph=Depends(get_graph)):
    """获取节点的图邻域（关联节点 + 关系），支持 depth 1-3。"""
    try:
        return await graph.get_neighborhood(node_id, depth=depth)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Graph DB query failed: {e}")


# =========================================================================
# Node CRUD
# =========================================================================

@router.get("/ontology/nodes")
async def list_nodes(
    label: Optional[str] = None,
    limit: int = 100,
    keyword: Optional[str] = None,
    graph=Depends(get_graph),
):
    """列出节点，支持按标签和关键词过滤。"""
    try:
        return await graph.list_nodes(label=label, limit=min(limit, 500), keyword=keyword)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Graph DB query failed: {e}")


@router.get("/ontology/nodes/{node_id}/history")
async def get_node_history(node_id: int):
    """获取图节点的历史变更记录（ontol_data_his）。"""
    try:
        rows = await _query_scene(
            "SELECT * FROM ontol_data_his WHERE node_id=? AND delete_flag='0' ORDER BY create_time DESC LIMIT 50",
            (str(node_id),),
        )
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"History query failed: {e}")


@router.get("/ontology/nodes/{node_id}")
async def get_node(node_id: int, graph=Depends(get_graph)):
    """获取节点详情及邻接关系。"""
    try:
        node = await graph.get_node(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
        return node
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Graph DB query failed: {e}")


@router.post("/ontology/nodes", status_code=201)
async def create_node(body: NodeCreate, graph=Depends(get_graph)):
    """创建节点。"""
    try:
        result = await graph.create_node(body.label, body.properties)
        # 记录历史
        await _record_history(str(result.get("id", "")), "create", {"label": body.label, "new_props": body.properties})
        return result
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Graph DB create failed: {e}")


@router.put("/ontology/nodes/{node_id}")
async def update_node(node_id: int, body: NodeUpdate, graph=Depends(get_graph)):
    """更新节点属性。自动记录历史并递增版本号。删除的属性会被移除。"""
    try:
        # 先获取旧状态
        old_node = await graph.get_node(node_id)
        old_props = old_node["properties"] if old_node else {}
        new_props = body.properties

        # 找出被删除的 key（旧有但新无）
        removed_keys = [k for k in old_props if k not in new_props]
        node = await graph.update_node(node_id, new_props, remove_keys=removed_keys or None)
        if node is None:
            raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

        # 记录历史（变更前后的差异）
        await _record_history(str(node_id), "update", {
            "old_props": old_props,
            "new_props": new_props,
            "removed_keys": removed_keys,
        })
        # 递增版本号
        await _bump_node_version(graph, node_id)
        return node
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Graph DB update failed: {e}")


@router.delete("/ontology/nodes/{node_id}")
async def delete_node(node_id: int, graph=Depends(get_graph)):
    """删除节点及其所有关系。删除前记录历史快照。"""
    try:
        # 删除前获取快照
        snapshot = await graph.get_node(node_id)
        if snapshot:
            await _record_history(str(node_id), "delete", {
                "snapshot": {"labels": snapshot["labels"], "properties": snapshot["properties"]},
            })
        ok = await graph.delete_node(node_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
        return {"deleted": True, "node_id": node_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Graph DB delete failed: {e}")


# =========================================================================
# Edge CRUD
# =========================================================================

@router.post("/ontology/edges", status_code=201)
async def create_edge(body: EdgeCreate, graph=Depends(get_graph)):
    """创建关系。记录历史并递增源/目标节点版本号。"""
    try:
        result = await graph.create_edge(body.source_id, body.target_id, body.rel_type, body.properties)
        # 记录历史
        await _record_history(str(result.get("source_id", "")), "edge_create", {
            "target_id": body.target_id,
            "rel_type": body.rel_type,
            "edge_props": body.properties or {},
            "edge_id": result.get("id", ""),
        })
        # 递增双方版本号
        await _bump_node_version(graph, body.source_id)
        await _bump_node_version(graph, body.target_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Graph DB create edge failed: {e}")


@router.delete("/ontology/edges/{edge_id}")
async def delete_edge(edge_id: int, graph=Depends(get_graph)):
    """删除关系。记录历史快照并递增版本号。"""
    try:
        # 删除前获取边信息用于记录
        from infrastructure.db.neo4j import get_driver
        source_id = 0; target_id = 0
        try:
            driver = await get_driver()
            async with driver.session() as session:
                r = await session.run(
                    "MATCH ()-[e]->() WHERE id(e) = $eid "
                    "RETURN type(e) AS rel_type, id(startNode(e)) AS src, id(endNode(e)) AS tgt",
                    eid=edge_id,
                )
                rec = await r.single()
                if rec:
                    source_id = rec["src"]
                    target_id = rec["tgt"]
                    await _record_history(str(source_id), "edge_delete", {
                        "target_id": target_id,
                        "rel_type": rec["rel_type"],
                        "edge_id": edge_id,
                    })
        except Exception:
            pass  # 记录失败不影响删除

        ok = await graph.delete_edge(edge_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Edge {edge_id} not found")

        # 递增版本号
        if source_id: await _bump_node_version(graph, source_id)
        if target_id: await _bump_node_version(graph, target_id)
        return {"deleted": True, "edge_id": edge_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Graph DB delete edge failed: {e}")


@router.get("/ontology/edges")
async def list_edges(limit: int = 2000, graph=Depends(get_graph)):
    """列出所有关系（边）。"""
    try:
        return await graph.list_all_edges(limit=min(limit, 5000))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Graph DB query failed: {e}")


@router.post("/tools/call")
async def tools_call(body: ToolsCallBody):
    """代理转发到 KG 推理机的 /tools/call。"""
    import json, requests as req
    from common.config.settings import get_settings

    kg_url = get_settings().kg_server_url
    try:
        resp = req.post(
            f"{kg_url}/tools/call",
            json={"name": body.name, "arguments": body.arguments},
            timeout=120,
        )
        # 把 KG 服务端的响应原样返回，状态码也透传
        try:
            data = resp.json()
        except json.JSONDecodeError:
            data = {"raw": resp.text}
        from fastapi.responses import JSONResponse
        return JSONResponse(content=data, status_code=resp.status_code)
    except req.RequestException as e:
        raise HTTPException(status_code=503, detail=f"KG reasoning server unreachable: {e}")


@router.get("/ontology/search")
async def search_nodes(keyword: str, limit: int = 20, graph=Depends(get_graph)):
    """按关键词搜索节点。"""
    try:
        return await graph.search_nodes(keyword, limit=min(limit, 100))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Graph DB search failed: {e}")


# =========================================================================
# Ontology Model CRUD (SQLite)
# =========================================================================

@router.get("/ontology-models")
async def list_ontology_models(
    keyword: Optional[str] = None,
    limit: int = 50,
    repo=Depends(get_ontology_repo),
):
    """获取本体模型树（含继承字段数）。"""
    try:
        if keyword:
            return await repo.search_models(keyword, limit=min(limit, 200))
        tree = await repo.get_full_tree_with_attrs()
        # 补全继承字段数：子模型 badge 显示完整字段数而非 0
        for node in tree:
            if not node.get("attributes"):
                inherited = _get_inherited_fields(node["id"])
                node["_inherited_count"] = len(inherited)
        return tree
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database query failed: {e}")


@router.get("/ontology-models/stats")
async def ontology_models_stats(repo=Depends(get_ontology_repo)):
    """获取本体模型统计。"""
    try:
        return await repo.get_stats()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database query failed: {e}")


@router.get("/ontology-models/search")
async def search_ontology_models(
    keyword: str,
    model_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    repo=Depends(get_ontology_repo),
):
    """搜索本体模型。"""
    try:
        if not model_type and not status:
            return await repo.search_models(keyword, limit=min(limit, 1000))
        from infrastructure.db.base_repo import BaseRepository
        pool = get_sqlite_pool()
        temp = BaseRepository(pool, "ontol_model", pk="id", soft_delete=True)
        where = {}
        if model_type:
            where["ontol_model_type"] = model_type
        if status:
            where["ontol_model_status"] = status
        return await temp.search(keyword, columns=["ontol_name", "ontol_model_desc"], where=where, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Search failed: {e}")


@router.get("/ontology-models/{model_id}")
async def get_ontology_model(model_id: str, repo=Depends(get_ontology_repo)):
    """获取单个本体模型及其属性（含继承链）。"""
    try:
        if model_id != "tree":
            model = await repo.get_model_with_attrs(model_id)
        else:
            return await repo.get_full_tree_with_attrs()
        if model is None:
            model = await repo.model.get_by_id(model_id)
        return model
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database query failed: {e}")


@router.post("/ontology-models", status_code=201)
async def create_ontology_model(body: OntolModelCreateBody, repo=Depends(get_ontology_repo)):
    """创建本体模型（后端生成 UUID 主键，ontol_code 由用户指定并唯一校验）。"""
    import uuid as _uuid
    data = body.model_dump()
    data["id"] = _uuid.uuid4().hex[:16]  # 主键自动 UUID
    try:
        return await repo.model.insert(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Create failed: {e}")


@router.put("/ontology-models/{model_id}")
async def update_ontology_model(model_id: str, body: OntolModelUpdateBody, repo=Depends(get_ontology_repo)):
    """更新本体模型。"""
    try:
        result = await repo.model.update(model_id, body.model_dump(exclude_none=True))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {e}")


@router.delete("/ontology-models/{model_id}")
async def delete_ontology_model(model_id: str, soft: bool = True, repo=Depends(get_ontology_repo)):
    """删除本体模型（默认软删除）。"""
    try:
        deleted = await repo.model.delete(model_id, soft=soft)
        return {"deleted": True, "model_id": model_id, "soft": soft}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")


@router.get("/ontology-models/{model_id}/attrs")
async def list_model_attrs(model_id: str, is_system: Optional[str] = None, repo=Depends(get_ontology_repo)):
    """获取模型属性列表。"""
    try:
        return await repo.get_attrs_by_model(model_id, is_system=is_system)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database query failed: {e}")


@router.post("/ontology-models/{model_id}/attrs", status_code=201)
async def create_model_attr(model_id: str, body: OntolModelAttrCreateBody, repo=Depends(get_ontology_repo)):
    """创建模型属性（后端生成 UUID 主键，前端传的 id 会被忽略）。"""
    import uuid as _uuid
    data = body.model_dump()
    data["id"] = _uuid.uuid4().hex[:16]          # 用 UUID 覆盖前端传的 id
    data["ontol_model_id"] = model_id
    data.setdefault("create_time", datetime.utcnow())
    data.setdefault("delete_flag", "0")
    try:
        return await repo.attr.insert(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Create attr failed: {e}")


@router.put("/ontology-models/{model_id}/attrs/{attr_id}")
async def update_model_attr(model_id: str, attr_id: str, body: OntolModelAttrUpdateBody, repo=Depends(get_ontology_repo)):
    """更新模型属性。系统预设字段（attr_is_system='1'）不可修改。"""
    try:
        # 检查是否为系统预设字段
        existing = await repo.attr.get_by_id(attr_id)
        if existing and existing.get("attr_is_system") == "1":
            raise HTTPException(status_code=403, detail="系统预设字段不可修改")
        result = await repo.attr.update(attr_id, body.model_dump(exclude_none=True))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update attr failed: {e}")


@router.delete("/ontology-models/{model_id}/attrs/{attr_id}")
async def delete_model_attr(model_id: str, attr_id: str, repo=Depends(get_ontology_repo)):
    """删除模型属性。系统预设字段（attr_is_system='1'）不可删除。"""
    try:
        # 检查是否为系统预设字段
        existing = await repo.attr.get_by_id(attr_id)
        if existing and existing.get("attr_is_system") == "1":
            raise HTTPException(status_code=403, detail="系统预设字段不可删除")
        await repo.attr.delete(attr_id)
        return {"deleted": True, "attr_id": attr_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete attr failed: {e}")


# =========================================================================
# Upload & File Management
# =========================================================================
import os
import json as _json
import time
import threading
from datetime import datetime

class SnowflakeGenerator:
    """简化版雪花算法，生成 64 位整数 ID。

    结构: timestamp(42bit) | datacenter(5bit) | worker(5bit) | sequence(12bit)
    """

    EPOCH = 1577836800000  # 2020-01-01T00:00:00Z (ms)

    def __init__(self, worker_id: int = 1, datacenter_id: int = 1):
        self.worker_id = worker_id & 0x1F
        self.datacenter_id = datacenter_id & 0x1F
        self.sequence = 0
        self.last_timestamp = -1
        self._lock = threading.Lock()

    def next_id(self) -> int:
        with self._lock:
            timestamp = int(time.time() * 1000)
            if timestamp < self.last_timestamp:
                timestamp = self.last_timestamp

            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & 0xFFF
                if self.sequence == 0:
                    while timestamp <= self.last_timestamp:
                        timestamp = int(time.time() * 1000)
            else:
                self.sequence = 0

            self.last_timestamp = timestamp
            return (
                ((timestamp - self.EPOCH) << 22)
                | (self.datacenter_id << 17)
                | (self.worker_id << 12)
                | self.sequence
            )


def _generate_snowflake_ids(
    entities: list[dict],
    relationships: list[dict],
    existing_ids: set[int],
) -> dict[str, int]:
    """为实体中 LLM 随机生成的 id 分配雪花 ID，相同随机串 → 相同雪花 ID。

    Returns:
        {random_id_str: snowflake_int} 映射表
    """
    # 收集所有需要替换的随机 ID 字符串
    random_ids: set[str] = set()
    for ent in entities:
        eid = (ent.get("properties", {}).get("id") or "").strip()
        if not eid:
            continue
        # 跳过纯数字（可能已是雪花 ID）和提示词占位文本
        if eid.isdigit() or eid == "大模型随机生成":
            continue
        random_ids.add(eid)

    # 也检查关系的 start_node_id / end_node_id 是否引用了随机 ID
    for rel in relationships:
        for key in ("start_node_id", "end_node_id", "subject", "object"):
            val = (rel.get(key) or "").strip()
            if val and not val.isdigit():
                random_ids.add(val)

    if not random_ids:
        return {}

    # 为每个唯一的随机 ID 生成雪花 ID，确保不与已有 ID 冲突
    sf = SnowflakeGenerator(worker_id=1, datacenter_id=1)
    id_map: dict[str, int] = {}
    for rid in random_ids:
        while True:
            snowflake = sf.next_id()
            if snowflake not in existing_ids and snowflake not in id_map.values():
                id_map[rid] = snowflake
                existing_ids.add(snowflake)
                break

    return id_map


_UPLOAD_HISTORY_FILE = _Path("infrastructure/storage/uploads/.history.json")


def _read_history() -> list:
    if _UPLOAD_HISTORY_FILE.exists():
        try:
            return _json.loads(_UPLOAD_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _write_history(entries: list):
    _UPLOAD_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _UPLOAD_HISTORY_FILE.write_text(_json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_history(entry: dict):
    entries = _read_history()
    entries.insert(0, entry)
    # keep last 200
    _write_history(entries[:200])


@router.get("/upload/history")
async def upload_history():
    """返回历史上传记录。"""
    return _read_history()


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """接收文件上传，保存到 infrastructure/storage/ 目录。"""
    from pathlib import Path as _PathLocal

    upload_dir = _PathLocal("infrastructure/storage/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = os.path.basename(file.filename or "untitled")
    dest = upload_dir / safe_name

    try:
        content = await file.read()
        if len(content) > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File exceeds 50MB limit")

        dest.write_bytes(content)
        now_str = datetime.utcnow().isoformat() + "Z"

        entry = {
            "filename": safe_name,
            "size": len(content),
            "path": str(dest),
            "uploaded_at": now_str,
            "uploaded": True,
        }
        _append_history(entry)

        return entry
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/upload/preview/{filename:path}")
async def preview_file(filename: str):
    """在线预览上传的文件。文本文件返回内容，二进制文件返回 download URL。"""
    from fastapi.responses import FileResponse, PlainTextResponse

    upload_dir = _Path("infrastructure/storage/uploads")
    safe_name = os.path.basename(filename)
    file_path = upload_dir / safe_name

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{safe_name}' not found")

    # 文本类直接返回内容
    text_exts = {".txt", ".json", ".csv", ".xml", ".rdf", ".owl", ".ttl", ".nt", ".swrl"}
    if file_path.suffix.lower() in text_exts:
        try:
            content = file_path.read_text(encoding="utf-8")
            return {"type": "text", "filename": safe_name, "content": content}
        except UnicodeDecodeError:
            pass

    return FileResponse(str(file_path), filename=safe_name)


@router.delete("/upload/{filename:path}")
async def delete_file(filename: str):
    """删除上传的文件（同时清理历史记录）。"""
    upload_dir = _Path("infrastructure/storage/uploads")
    safe_name = os.path.basename(filename)
    file_path = upload_dir / safe_name

    file_deleted = False
    if file_path.exists():
        try:
            file_path.unlink()
            file_deleted = True
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # 无论文件是否存在，都从历史记录中移除该条目
    history = _read_history()
    remaining = [e for e in history if e.get("filename") != safe_name]
    if len(remaining) != len(history):
        _write_history(remaining)

    return {"deleted": True, "filename": safe_name, "file_on_disk": file_deleted}


# =========================================================================
# 本体类型感知的实体解析 & 图数据库导入
# =========================================================================

# ── 本体类型定义（从 SQLite 动态加载）──

_ONTOLOGY_TYPES_CACHE: Optional[dict] = None
_ONTOLOGY_TREE_CACHE: Optional[list] = None   # 树形结构（含层级关系）


def _load_ontology_types() -> dict:
    """从 SQLite 数据库加载所有本体类型及其字段定义（平铺）。"""
    global _ONTOLOGY_TYPES_CACHE
    if _ONTOLOGY_TYPES_CACHE is not None:
        return _ONTOLOGY_TYPES_CACHE

    import sqlite3
    from pathlib import Path

    db_path = Path("infrastructure/db/ontol.db")
    types = {}

    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        models = conn.execute(
            "SELECT * FROM ontol_model WHERE delete_flag='0' ORDER BY ontol_model_type, id"
        ).fetchall()
        for m in models:
            md = dict(m)
            attrs = conn.execute(
                """SELECT id, attr_name, attr_code, attr_data_type, attr_length,
                          attr_required, attr_default_value, attr_desc
                   FROM ontol_model_attr
                   WHERE ontol_model_id=? AND delete_flag='0'
                   ORDER BY attr_code""",
                (md["id"],),
            ).fetchall()
            types[md["id"]] = {
                "id": md["id"],
                "name": md["ontol_name"],
                "parent_id": md.get("ontol_parent_id") or None,
                "type_code": md["ontol_model_type"],
                "desc": md["ontol_model_desc"] or "",
                "fields": [
                    {
                        "id": a["id"],
                        "name": a["attr_name"],
                        "code": a["attr_code"],
                        "data_type": a["attr_data_type"],
                        "length": a["attr_length"],
                        "required": a["attr_required"],
                        "default": a["attr_default_value"],
                        "desc": a["attr_desc"] or "",
                    }
                    for a in attrs
                ],
            }
        conn.close()

    _ONTOLOGY_TYPES_CACHE = types
    return types


def _get_inherited_fields(ont_type: str) -> dict[str, dict]:
    """
    获取指定本体类型的完整字段列表（含继承链）。

    规则：
    - M_ROOT 的字段是所有类型共用的（L0 全局字段）
    - 沿父链向上递归收集，直到 M_ROOT
    - 子类型字段覆盖父类型同名字段
    - 返回 {field_code: field_info} 字典
    """
    types = _load_ontology_types()
    if not types or ont_type not in types:
        return {}

    fields: dict[str, dict] = {}
    current_id = ont_type
    visited = set()

    while current_id and current_id in types and current_id not in visited:
        visited.add(current_id)
        t = types[current_id]
        for f in t.get("fields", []):
            code = f.get("code", "")
            if code not in fields:
                fields[code] = {**f, "source_model": current_id, "source_name": t.get("name", "")}
        current_id = t.get("parent_id")

    return fields


def _validate_entities_for_import(entities: list[dict]) -> dict:
    """
    校验解析后的实体，检查本体模板匹配 + 计算缺失字段。

    返回:
        {
            "valid": bool,
            "type_counts": {ont_type: count},
            "unknown_types": [{ont_type, type_name, entity_names: [...]}],
            "missing_fields": [{entity_name, ont_type, missing: [{code, name, required, default}]}],
            "summary": "校验摘要",
        }
    """
    types = _load_ontology_types()
    all_type_ids = set(types.keys()) if types else set()

    type_counts: dict[str, int] = {}
    unknown_types_map: dict[str, dict] = {}  # ont_type -> {ont_type, type_name, entity_names}
    missing_fields_list: list[dict] = []

    for ent in entities:
        ont_type = (ent.get("ont_type") or "").strip()
        name = (ent.get("name") or "").strip()
        type_name = (ent.get("type_name") or "").strip()
        props = ent.get("properties") or {}

        # 统计
        type_counts[ont_type] = type_counts.get(ont_type, 0) + 1

        # 检查模板是否存在
        if ont_type not in all_type_ids:
            key = ont_type
            if key not in unknown_types_map:
                unknown_types_map[key] = {"ont_type": ont_type, "type_name": type_name, "entity_names": []}
            if name and name not in unknown_types_map[key]["entity_names"]:
                unknown_types_map[key]["entity_names"].append(name)
            continue

        # 模板存在 → 计算缺失字段
        inherited = _get_inherited_fields(ont_type)
        missing = []
        for code, finfo in inherited.items():
            if code not in props or not props.get(code):
                missing.append({
                    "code": code,
                    "name": finfo.get("name", ""),
                    "required": finfo.get("required", "0") == "1",
                    "default": finfo.get("default") or "",
                    "source_model": finfo.get("source_model", ""),
                    "source_name": finfo.get("source_name", ""),
                })
        if missing:
            missing_fields_list.append({
                "entity_name": name,
                "ont_type": ont_type,
                "type_name": type_name,
                "missing": missing,
                "has_existing_props": list(props.keys()),
            })

    unknown_types = list(unknown_types_map.values())
    has_unknown = len(unknown_types) > 0
    has_missing = len(missing_fields_list) > 0
    valid = not has_unknown

    summary_parts = []
    if has_unknown:
        unknown_names = ", ".join(f"{u['ont_type']}({len(u['entity_names'])}个实体)" for u in unknown_types[:5])
        summary_parts.append(f"⚠️ {len(unknown_types)} 个类型无匹配模板: {unknown_names}")
    if has_missing:
        summary_parts.append(f"📋 {len(missing_fields_list)} 个实体可补全字段")
    if not summary_parts:
        summary_parts.append("✅ 所有实体类型均有匹配模板")

    return {
        "valid": valid,
        "type_counts": type_counts,
        "unknown_types": unknown_types,
        "missing_fields": missing_fields_list,
        "summary": " | ".join(summary_parts),
    }


def _build_ontology_prompt() -> str:
    """构建包含所有本体类型定义的 LLM 提示词。

    规则：
    - 排除 M_ROOT 自身，不参与分类
    - 根节点字段是全局字段，所有本体类型继承
    - 每个本体类型额外拥有自己的专属字段
    - 关系语义使用 OWL2 DL，推理使用 SWRL
    """
    types = _load_ontology_types()
    root_type = types.get("M_ROOT", {})
    root_fields = root_type.get("fields", [])
    non_root = {tid: td for tid, td in types.items() if tid != "M_ROOT"}

    lines = []
    lines.append("你是一个本体建模专家。请解析文本，识别实体并归类到以下本体类型，填写所有字段。\n")

    # ─── 1. 全局字段（继承自根节点）───
    if root_fields:
        la = "L0 全局字段" if root_type.get("name") else "全局公共字段"
        lines.append(f"# {la}（所有本体类型共有）\n")
        for f in root_fields:
            lines.append(_fmt_field(f))
        lines.append("")

    # ─── 2. 各本体类型 + 专属字段 ──
    lines.append("# 本体类型定义\n")
    for tid, tdef in non_root.items():
        lines.append(f"## {tdef.get('name','')} (ont_type={tid}, 类型代码={tdef.get('type_code','')})")
        lines.append(f"描述: {tdef.get('desc','')}")

        own = tdef.get("fields", [])
        lines.append(f"专属字段 ({len(own)} 个):")
        if own:
            for f in own:
                lines.append(_fmt_field(f))
        else:
            lines.append("  无专属字段，仅使用 L0 全局字段")
        lines.append("")

    # ─── 3. 字段汇总表 ──
    lines.append("# 字段汇总\n")
    lines.append("每个实体需要填写的字段 = L0 全局字段 + 该本体类型的专属字段。\n")
    if root_fields:
        rf_codes = [f.get("code", "") for f in root_fields]
        lines.append(f"L0 全局字段（所有类型共有）: {', '.join(rf_codes)}")
    for tid, tdef in non_root.items():
        own = tdef.get("fields", [])
        all_codes = (root_fields or []) + own
        codes = [f.get("code", "") for f in all_codes]
        lines.append(f"{tdef['name']}: {', '.join(codes)}")
    lines.append("")

    # ─── 3.5. 本体类型枚举说明 ───
    lines.append("""# 本体类型（Ontology Types）枚举说明

在解析文本时，请根据实体的核心业务特征，将其归类为以下 7 种本体类型之一。注意：输出 JSON 时，`type` 字段的值必须严格使用以下指定的代码（如 M1、M2 等）：
- **M1 实体 (M_ENTITY)**：描述客观存在的物理对象、数字资产或核心业务概念。例如：设备、传感器、产品、文档、数据表等。
- **M2 行为 (M_ACTION)**：描述主体执行的动作、操作、流程节点或状态变更。例如：启动、校验、清洗、审批、计算等。
- **M3 规则 (M_RULE)**：描述业务逻辑、约束条件、算法策略、触发条件或计算公式。例如：阈值告警规则、权限校验规则、调度策略等。
- **M4 场景 (M_SCENE)**：描述业务发生的上下文、环境、时间段或特定业务模式。例如：夜间巡检、高并发交易、设备离线状态等。
- **M5 主体 (M_SUBJECT)**：描述执行行为的发起者、责任方、参与角色或组织。例如：操作员、系统服务、部门、外部供应商等。
- **M6 异常 (M_EXCEPTION)**：描述偏离正常状态的故障、错误、风险或告警事件。例如：网络超时、数据缺失、设备过热、越权访问等。
- **M7 质量 (M_QUALITY)**：描述衡量业务、数据或系统表现的标准、指标或评估维度。例如：准确率、响应时间、完整性、合规性等。

""")

    # ─── 5. 语义规范: OWL2 DL + SWRL + SHACL ──
    lines.append("""# 语义规范

## 前缀约定

| 序号 | 名称 | 编码前缀 | 格式示例 | 备注 |
|------|------|----------|----------|------|
| 1 | RDFS语言 | `rdfs:` | | RDFS语言 |
| 2 | OWL2 DL语言 | `owl2:` | | OWL2 DL语言为主 |
| 3 | SWRL语言 | `swrl:` | | SWRL语法 |
| 4 | SHACL语言 | `sh:` | | |
| 5 | 规则设定 | `rule:` | `rule:forwardChain`<br>`rule:backwardChain` | 默认就是前链推理 |
| 6 | 自定义动作接口 | `action:` | `action:中文动作描述` | 后面写汉字，由大模型自主判断执行什么动作 |
| 7 | 自定义函数 | `function:` | `{"id":"图ID","func"："函数名"}` | 对接大模型，用JSON实现 |

## RDFS 核心词汇
RDFS（RDF Schema）为 RDF 数据模型提供基础的类型系统和词汇描述能力：
- **rdfs:subClassOf** — 子类关系（A 是 B 的子类型）
- **rdfs:subPropertyOf** — 子属性关系
- **rdfs:domain** — 属性定义域（该属性适用于哪类主体）
- **rdfs:range** — 属性值域（该属性的值属于哪类客体）
- **rdfs:label** — 人类可读标签
- **rdfs:comment** — 注释说明
- **rdfs:type** — 实例类型声明
- **rdfs:Class** — 类
- **rdfs:Property** — 属性

## 关系（predicate）— 使用 OWL2 DL 语义
实体之间的关系遵循 OWL2 DL（Description Logic）标准，所有关系类型使用 `owl2:` 前缀：
- **owl2:subClassOf** — 子类关系（A 是 B 的子类型）
- **owl2:equivalentClass** — 等价类关系
- **owl2:disjointWith** — 互斥关系（A 和 B 不能同时成立）
- **owl2:objectProperty** — 对象属性（A 指向 B 的语义关联）
- **owl2:dataProperty** — 数据属性（A 拥有某个数据值）
- **owl2:sameAs / owl2:differentFrom** — 个体等价/不等价
- **owl2:inverseOf** — 逆关系（A→B 和 B→A 互为逆）
- **owl2:domain / owl2:range** — 定义域的约束

关系 type 优先使用 OWL2 标准词汇（带 owl2: 前缀），如需要自定义，使用驼峰命名（如 hasPart、isLocatedAt）。

## 推理规则（SWRL）
如文本中包含推理规则，用 SWRL（Semantic Web Rule Language）表达，示例：
  - swrl:Antecedent(body) → swrl:Consequent(head)
  - Entity(?x) ^ hasProperty(?x, ?v) ^ swrlb:greaterThan(?v, 100) → HighValue(?x)

## 校验规则（SHACL）
如文本中包含数据校验约束，用 SHACL（Shapes Constraint Language）表达，常用词汇：
  - **sh:property** — 属性约束声明
  - **sh:class** — 节点类型约束
  - **sh:datatype** — 数据类型约束（如 xsd:string、xsd:integer）
  - **sh:minCount / sh:maxCount** — 最小/最大出现次数
  - **sh:pattern** — 正则表达式匹配
  - **sh:in** — 枚举值约束

## 推理规则设定（rule:）
如文本中包含推理方向或策略设定，使用 `rule:` 前缀表达：
  - `rule:forwardChain` — 前链推理（从已知事实推导新结论），**默认模式**
  - `rule:backwardChain` — 后链推理（从目标反向寻找支撑条件）

## 自定义动作接口（action:）
`action:` 前缀后面写汉字描述，由大模型自主判断要执行什么动作。
格式：`action:中文动作描述`
示例：`action:查询最近的敌情报告`、`action:调取防空火力单元`

如果文本中没有明确指定动作类型，默认使用 `action:` 前缀，由大模型自主填充动作描述。

## 自定义函数（function:）
如文本中需要执行自定义计算或处理逻辑，使用 `function:` 前缀，通过 JSON 传递参数对接大模型：
  - 格式：`{"id": "图节点ID", "func"："函数名"}`
  - 函数参数根据具体业务需求扩展

## 字段填写规则
1. 每个字段尽量从原文中推断填充，无法推断则留空字符串 ""
2. 字段值保持原文语义，不要臆造
3. 日期/时间字段使用 openCypher 标准时间格式（如 LocalDateTime），到秒即可
4. 编码字段使用英文驼峰或下划线命名
5. 置信度字段如未明确指定，默认填 80%

## 输出格式（严格 JSON）
只输出以下 JSON，不得包含任何解释文字：

```json
{
  "entities": [
    {
      "name": "实体名称",
      "ont_type": "M_ENTITY",
      "type_name": "实体",
      "properties": {
        "id": "大模型随机生成",
        "unit_id": "",
        "graph_id": "",
        "domain": "",
        "leven": "",
        "code": "业务编码(必填)，字符串100",
        "name": "名称(必填)，字符串200",
        "type": "本体类型代码，严格使用枚举值：M1 / M2 / M3 / M4 / M5 / M6 / M7，字符串4",
        "update_time": "更新时间，openCypher 标准时间格式(如 LocalDateTime)，到秒即可",
        "create_time": "创建时间，openCypher 标准时间格式(如 LocalDateTime)，到秒即可",
        "confidence": "置信度，百分数，默认80%",
        "description": "描述，字符串500",
        "status": "状态，枚举值：有效/无效，字符串4",
        "version": "数据版本，示例v1.0，提交更新大版本，保存更新小版本，字符串32",
        "cope_version": "副本版本，推演环境的副本版本，字符串32",
        "source": "来源，字符串50",
        "owner": "维护人员/所属人/责任人，字符串50",
        "hasPrecondition": "前置条件，使用SHACL语言，可为空",
        "hasEffect": "执行效果描述",
        "hasCost": "消耗，JSON格式如 {\\"name\\": \\"电\\", \\"type\\": \\"M1\\", \\"amount\\": 500, \\"unit\\": \\"kWh\\"}",
        "hasDuration": "持续时间(秒)，用于时序执行排序，整数",
        "hasPriority": "优先级，0-10级，10级最高，未写默认0",
        "isComposedOf": "组合关系，可多个，用分号区分",
        "synonym": "同义词，增加检索准确性，用分号隔离",
        "queryVariant": "错意词，容易输错或拼写错误的词，用分号隔离"
      }
    }
  ],
  "relationships": [
    {
      "type": "关系类型(如 owl2:subClassOf)",
      "start_node_id": "起始节点名称",
      "end_node_id": "目标节点名称",
      "properties": {
        "note": "Memgraph 属性图模型支持在关系上挂载属性，按需填写"
      }
    }
  ]
}
```

## 重要规则
1. 每个实体必须归类到一个 ont_type（从上面定义的本体类型中选择）
2. 每个实体的 properties 中 `type` 字段必须填写 M1~M7 枚举值
3. properties 必须包含 L0 全局字段 + 该类型专属字段，尽量从文本中提取
4. 关系 type 遵循 OWL2 DL 语义规范（带 owl2: 前缀）
5. 如有推理规则，使用 SWRL 格式填入 hasPrecondition 或单独关系
6. 如有校验约束，使用 SHACL 格式
7. 只输出 JSON，不要输出任何解释""")
    return "\n".join(lines)


def _fmt_field(f: dict) -> str:
    """格式化一个字段为提示词中的一行。"""
    req = "必填" if f.get("required", "0") == "1" else "可选"
    default = f"，默认值={f.get('default')}" if f.get("default") else ""
    dtype = f.get("data_type", "0")
    dtype_name = {"0": "字符串", "1": "数字", "2": "浮点数"}.get(dtype, dtype)
    return f"  - {f.get('code','')} ({f.get('name','')}): {req}, {dtype_name}, 长度={f.get('length','—')}{default} — {f.get('desc','')}"


class ParseTriplesRequest(BaseModel):
    filename: str = Field(..., description="要解析的文件名")
    model: str = Field("", description="使用的 LLM 模型名 (DB config_id 或 provider::name)")


class ImportEntitiesRequest(BaseModel):
    filename: str = Field(..., description="来源文件名")
    entities: list[dict] = Field(..., description="本体实体列表")
    relationships: list[dict] = Field(default_factory=list, description="关系列表")
    scene_ids: list[str] = Field(default_factory=list, description="关联的场景ID列表")


class ValidateEntitiesRequest(BaseModel):
    entities: list[dict] = Field(..., description="待校验的实体列表")


@router.post("/upload/validate-entities")
async def validate_entities_for_import(body: ValidateEntitiesRequest):
    """
    校验解析后的实体，检测本体模板匹配情况。

    返回:
    - unknown_types: 无匹配模板的类型及其实体（需用户确认）
    - missing_fields: 有模板但缺失字段的实体（需补全）
    """
    from pathlib import Path as _PathLocal
    return _validate_entities_for_import(body.entities)


def _parse_entities_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON 格式的实体和关系（多级降级策略）。"""
    import re, json

    text = text.strip()

    # 1. 直接 JSON 解析
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. 提取 markdown 代码围栏（各种变体）
    fence_patterns = [
        r'```json\s*\n(.*?)\n\s*```',
        r'```\s*\n(.*?)\n\s*```',
        r'```json\s*(.*?)\s*```',
        r'```\s*(.*?)\s*```',
    ]
    for pattern in fence_patterns:
        for m in re.finditer(pattern, text, re.DOTALL | re.IGNORECASE):
            try:
                result = json.loads(m.group(1).strip())
                if isinstance(result, dict):
                    return result
            except (json.JSONDecodeError, TypeError):
                continue

    # 3. 按大括号平衡匹配，逐个尝试每个顶层 JSON 对象
    brace_depth = 0
    start = -1
    candidates = []
    for i, ch in enumerate(text):
        if ch == '{':
            if brace_depth == 0:
                start = i
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
            if brace_depth == 0 and start >= 0:
                candidates.append(text[start:i+1])
                start = -1

    for candidate in candidates:
        try:
            result = json.loads(candidate)
            if isinstance(result, dict) and ('entities' in result or 'relationships' in result):
                return result
        except (json.JSONDecodeError, TypeError):
            continue

    # 4. 最终降级：处理常见 LLM 附加文本后重试贪婪匹配
    cleaned = re.sub(r'\*\*[^*]+\*\*', '', text)       # 去加粗
    cleaned = re.sub(r'`[^`]+`', '', cleaned)           # 去行内代码
    m = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except (json.JSONDecodeError, TypeError):
            pass

    # 全失败：返回空结果 + 错误上下文
    return {
        "entities": [],
        "relationships": [],
        "_parse_error": True,
        "_raw_snippet": text[:500],
    }


@router.post("/upload/parse")
async def parse_file_to_entities(body: ParseTriplesRequest):
    """
    用大模型解析上传文件，识别本体类型并填充字段。

    返回按本体类型分类的实体列表和关系列表，供用户审核后导入图数据库。
    """
    upload_dir = _Path("infrastructure/storage/uploads")
    safe_name = os.path.basename(body.filename)
    file_path = upload_dir / safe_name

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{safe_name}' not found")

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="无法读取二进制文件，请上传文本格式文件")

    from capabilities.models.factory import ModelFactory
    from langchain_core.messages import HumanMessage

    factory = ModelFactory()
    llm_iface = factory.create_llm(body.model)
    llm = await llm_iface.get_llm()

    # ── 分块 ──
    CHUNK_SIZE = 3000
    chunks: list[str] = []
    start = 0
    while start < len(content):
        end = min(start + CHUNK_SIZE, len(content))
        if end < len(content):
            for sep in ("\n\n", "\n", "。", "；", ". "):
                pos = content.rfind(sep, start, end)
                if pos > start + 500:
                    end = pos + len(sep)
                    break
        chunks.append(content[start:end].strip())
        start = end

    all_entities: dict[str, dict] = {}  # name -> entity dict
    all_relationships: list[dict] = []
    seen_rels = set()
    chunk_errors: list[dict] = []       # 记录每块的错误，反馈到前端
    total_chunks = sum(1 for c in chunks if c and len(c) >= 10)

    onto_prompt = _build_ontology_prompt()

    for i, chunk in enumerate(chunks):
        if not chunk or len(chunk) < 10:
            continue

        try:
            response = await llm.ainvoke([
                HumanMessage(content=onto_prompt),
                HumanMessage(content=f"请解析以下文本（第{i+1}/{len(chunks)}块）：\n\n{chunk}"),
            ])
            text = response.content if hasattr(response, "content") else str(response)
            result = _parse_entities_json(text)

            # 检查是否解析失败（_parse_error 标记）
            if result.pop("_parse_error", None):
                chunk_errors.append({
                    "chunk_index": i + 1,
                    "reason": "JSON提取失败 — LLM 返回无法解析为 JSON",
                    "raw_snippet": result.pop("_raw_snippet", "")[:300],
                })
                continue

            # Merge entities
            for ent in result.get("entities", []):
                name = (ent.get("name") or "").strip()
                if not name:
                    continue
                if name not in all_entities:
                    all_entities[name] = {
                        "name": name,
                        "ont_type": ent.get("ont_type", "M_ENTITY"),
                        "type_name": ent.get("type_name", ""),
                        "properties": ent.get("properties", {}),
                    }
                else:
                    # Merge properties from duplicate
                    existing = all_entities[name]
                    for k, v in (ent.get("properties") or {}).items():
                        if k not in existing["properties"] or not existing["properties"][k]:
                            existing["properties"][k] = v

            # Merge relationships
            for rel in result.get("relationships", []):
                s = (rel.get("start_node_id") or rel.get("subject") or "").strip()
                p = (rel.get("type") or rel.get("predicate") or "").strip()
                o = (rel.get("end_node_id") or rel.get("object") or "").strip()
                if not s or not o or not p:
                    continue
                key = f"{s}|{p}|{o}"
                if key not in seen_rels:
                    seen_rels.add(key)
                    all_relationships.append({
                        "start_node_id": s, "type": p, "end_node_id": o,
                        "properties": rel.get("properties", {}),
                    })

        except Exception as e:
            chunk_errors.append({
                "chunk_index": i + 1,
                "reason": f"LLM 调用失败: {str(e)}",
            })

    entities_list = list(all_entities.values())

    # ── 按本体类型分组统计 ──
    type_counts = {}
    for e in entities_list:
        t = e.get("ont_type", "M_ENTITY")
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "filename": safe_name,
        "entity_count": len(entities_list),
        "relationship_count": len(all_relationships),
        "type_counts": type_counts,
        "entities": entities_list,
        "relationships": all_relationships,
        "chunks_total": total_chunks,
        "chunks_ok": total_chunks - len(chunk_errors),
        "chunks_failed": len(chunk_errors),
        "chunk_errors": chunk_errors[:10],  # 最多返回前 10 条错误
    }


@router.post("/upload/import-entities")
async def import_entities_to_neo4j(body: ImportEntitiesRequest):
    """
    将本体分类后的实体和关系导入图数据库（Memgraph/Neo4j）。
    每个实体按 ont_type 打标签，自动补全继承链上的缺失字段。
    """
    from infrastructure.db.neo4j import get_driver

    try:
        driver = await get_driver()
    except InfrastructureError:
        raise HTTPException(status_code=503, detail="Graph DB driver not initialized")

    nodes_created = 0
    edges_created = 0
    filled_fields_count = 0  # 记录补全的字段数

    async with driver.session() as session:
        # ── 查询图中已有的所有 ID（节点 + 边），用于雪花 ID 去重 ──
        existing_ids: set[int] = set()
        try:
            node_result = await session.run("MATCH (n) WHERE n.id IS NOT NULL RETURN DISTINCT n.id AS nid")
            async for rec in node_result:
                val = rec.get("nid")
                if val is not None:
                    try:
                        existing_ids.add(int(val))
                    except (ValueError, TypeError):
                        pass
            edge_result = await session.run(
                "MATCH ()-[r]->() WHERE r.id IS NOT NULL RETURN DISTINCT r.id AS rid"
            )
            async for rec in edge_result:
                val = rec.get("rid")
                if val is not None:
                    try:
                        existing_ids.add(int(val))
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass  # 查询失败不阻断导入

        # ── 为 LLM 随机生成的 id 分配雪花 ID ──
        id_map = _generate_snowflake_ids(body.entities, body.relationships, existing_ids)

        # ── 替换实体 properties.id（纯数字 int64，不转字符串）──
        for ent in body.entities:
            props = ent.get("properties") or {}
            eid = (props.get("id") or "").strip()
            if eid in id_map:
                props["id"] = id_map[eid]

        # ── 替换关系中的 start_node_id / end_node_id ──
        for rel in body.relationships:
            for key in ("start_node_id", "end_node_id", "subject", "object"):
                val = (rel.get(key) or "").strip()
                if val in id_map:
                    rel[key] = id_map[val]

        # ── 创建实体节点（按本体类型打标签）──
        for ent in body.entities:
            name = (ent.get("name") or "").strip()
            ont_type = (ent.get("ont_type") or "M_ENTITY").strip()
            props = ent.get("properties") or {}

            if not name:
                continue

            # 确保 name 在属性中
            if "name" not in props:
                props["name"] = name

            # ── 补全缺失字段 ──
            # 沿继承链（M_ROOT → … → ont_type）获取所有字段定义
            inherited = _get_inherited_fields(ont_type)
            if inherited:
                for code, finfo in inherited.items():
                    if code not in props or not props.get(code):
                        default_val = finfo.get("default") or ""
                        if default_val:
                            props[code] = default_val
                            filled_fields_count += 1
                        elif finfo.get("required", "0") == "1":
                            # 必填字段无默认值时，填入空字符串占位
                            props[code] = ""
                            filled_fields_count += 1

            # 清理 None 值
            clean_props = {k: v for k, v in props.items() if v is not None and v != ""}

            # Build dynamic label from ont_type (e.g. M_ENTITY -> Entity)
            type_to_label = {
                "M_ENTITY": "Entity",
                "M_BEHAVIOR": "Behavior",
                "M_RULE": "Rule",
                "M_SCENE": "Scene",
                "M_AGENT": "Agent",
                "M_EXCEPTION": "Exception",
                "M_QUALITY": "Quality",
                "M_EVENT": "Event",
                "M_TEMPLATE": "Template",
                "M_ROOT": "Entity",
                "M_BASE_ONTOLOGY": "Entity",
            }
            node_label = type_to_label.get(ont_type, "Entity")

            # 用 name 作为 merge key，创建带标签的节点
            await session.run(
                f"""
                MERGE (n:{node_label} {{name: $name}})
                SET n += $props
                SET n.ont_type = $ont_type
                """,
                name=name,
                props=clean_props,
                ont_type=ont_type,
            )

        # ── 创建关系 ──
        for rel in body.relationships:
            subj = (rel.get("start_node_id") or rel.get("subject") or "").strip()
            pred = (rel.get("type") or rel.get("predicate") or "").strip()
            obj = (rel.get("end_node_id") or rel.get("object") or "").strip()
            if not subj or not pred or not obj:
                continue

            safe_pred = pred.replace("`", "").replace(" ", "_")
            await session.run(
                f"""
                MATCH (a {{name: $subj}})
                MATCH (b {{name: $obj}})
                MERGE (a)-[r:RELATES {{type: $pred}}]->(b)
                SET r.predicate = $pred
                """,
                subj=subj, obj=obj, pred=pred,
            )
            edges_created += 1

        # ── 统计 ──
        node_result = await session.run("MATCH (n) RETURN count(n) AS cnt")
        node_rec = await node_result.single()
        nodes_created = node_rec["cnt"] if node_rec else 0

    # ── 绑定场景：实体名 ↔ 场景ID 写入 ontol_node_scene_relation ──
    scene_bind_count = 0
    if body.scene_ids:
        import uuid as _uuid
        for ent in body.entities:
            entity_name = (ent.get("name") or "").strip()
            if not entity_name:
                continue
            for sid in body.scene_ids:
                try:
                    await _execute_scene(
                        "INSERT INTO ontol_node_scene_relation (id, scene_id, scene_desc) VALUES (?,?,?)",
                        (_uuid.uuid4().hex[:16], sid, entity_name),
                    )
                    scene_bind_count += 1
                except Exception:
                    pass

    return {
        "filename": body.filename,
        "nodes_created": nodes_created,
        "edges_created": edges_created,
        "entity_count": len(body.entities),
        "filled_fields": filled_fields_count,
        "scene_bind_count": scene_bind_count,
    }


# 保留旧的 import-triples 兼容接口
class ImportTriplesRequest(BaseModel):
    filename: str = Field(..., description="来源文件名")
    triples: list[dict] = Field(..., description="三元组列表")


@router.post("/upload/import-triples")
async def import_triples_to_neo4j(body: ImportTriplesRequest):
    """兼容旧接口: 将三元组导入图数据库。新代码请使用 /upload/import-entities。"""
    return await import_entities_to_neo4j(
        ImportEntitiesRequest(
            filename=body.filename,
            entities=[
                {"name": t.get("subject", ""), "ont_type": "M_ENTITY", "properties": {"name": t.get("subject", "")}}
                for t in body.triples
            ]
            + [
                {"name": t.get("object", ""), "ont_type": "M_ENTITY", "properties": {"name": t.get("object", "")}}
                for t in body.triples
            ],
            relationships=body.triples,
        )
    )


# =========================================================================
# 场景管理 CRUD (ontol_model_scene)
# =========================================================================

class SceneCreate(BaseModel):
    id: str = Field(default="", max_length=32, description="场景ID，留空自动生成UUID")
    scene_name: str = Field(..., max_length=100, description="场景名称")
    scene_code: Optional[str] = Field(None, max_length=50, description="场景编码（唯一）")
    scene_desc: Optional[str] = Field(None, max_length=500, description="场景描述")
    parent_scene_id: Optional[str] = Field(None, max_length=32, description="父场景ID")
    create_id: Optional[str] = Field(None, max_length=32, description="创建人ID")

class SceneUpdate(BaseModel):
    scene_name: Optional[str] = Field(None, max_length=100, description="场景名称")
    scene_code: Optional[str] = Field(None, max_length=50, description="场景编码")
    scene_desc: Optional[str] = Field(None, max_length=500, description="场景描述")
    parent_scene_id: Optional[str] = Field(None, max_length=32, description="父场景ID")
    delete_flag: Optional[str] = Field(None, max_length=2, description="删除标志")


async def _query_scene(sql: str, params: tuple = ()) -> list[dict]:
    """执行场景表查询。"""
    import sqlite3
    db_path = _Path("infrastructure/db/ontol.db")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


async def _execute_scene(sql: str, params: tuple = ()) -> None:
    """执行场景表写操作。"""
    import sqlite3
    db_path = _Path("infrastructure/db/ontol.db")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


@router.get("/scenes")
async def list_scenes(keyword: Optional[str] = None):
    """列出所有场景，支持关键词搜索。"""
    try:
        if keyword:
            rows = await _query_scene(
                "SELECT * FROM ontol_model_scene WHERE delete_flag='0' AND (scene_name LIKE ? OR scene_desc LIKE ?) ORDER BY create_time DESC",
                (f"%{keyword}%", f"%{keyword}%"),
            )
        else:
            rows = await _query_scene(
                "SELECT * FROM ontol_model_scene WHERE delete_flag='0' ORDER BY create_time DESC"
            )
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scene query failed: {e}")


@router.get("/scenes/{scene_id}")
async def get_scene(scene_id: str):
    """获取单个场景详情。"""
    try:
        rows = await _query_scene(
            "SELECT * FROM ontol_model_scene WHERE id=? AND delete_flag='0'",
            (scene_id,),
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"Scene '{scene_id}' not found")
        return rows[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scene query failed: {e}")


@router.post("/scenes", status_code=201)
async def create_scene(body: SceneCreate):
    """创建场景。id 留空时自动生成 UUID。"""
    import uuid as _uuid
    try:
        scene_id = body.id.strip() if body.id else _uuid.uuid4().hex[:16]
        existing = await _query_scene(
            "SELECT id FROM ontol_model_scene WHERE id=? AND delete_flag='0'",
            (scene_id,),
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"Scene ID '{scene_id}' already exists")

        # 检查 scene_code 唯一性
        if body.scene_code:
            dup = await _query_scene(
                "SELECT id FROM ontol_model_scene WHERE scene_code=? AND delete_flag='0'",
                (body.scene_code,),
            )
            if dup:
                raise HTTPException(status_code=409, detail=f"场景编码 '{body.scene_code}' 已被使用")

        await _execute_scene(
            "INSERT INTO ontol_model_scene (id, scene_name, scene_code, scene_desc, parent_scene_id, create_id) VALUES (?,?,?,?,?,?)",
            (scene_id, body.scene_name, body.scene_code or None, body.scene_desc or "", body.parent_scene_id or None, body.create_id or ""),
        )
        return await get_scene(scene_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scene create failed: {e}")


@router.put("/scenes/{scene_id}")
async def update_scene(scene_id: str, body: SceneUpdate):
    """更新场景。系统预设场景（scene_is_system='1'）不可修改。"""
    try:
        rows = await _query_scene(
            "SELECT id, scene_is_system FROM ontol_model_scene WHERE id=? AND delete_flag='0'",
            (scene_id,),
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"Scene '{scene_id}' not found")
        if rows[0].get("scene_is_system") == "1":
            raise HTTPException(status_code=403, detail="系统预设场景不可修改")

        # 构建动态 UPDATE
        sets, params = [], []
        if body.scene_name is not None:
            sets.append("scene_name=?")
            params.append(body.scene_name)
        if body.scene_desc is not None:
            sets.append("scene_desc=?")
            params.append(body.scene_desc)
        if body.scene_code is not None:
            if body.scene_code:
                dup = await _query_scene(
                    "SELECT id FROM ontol_model_scene WHERE scene_code=? AND delete_flag='0' AND id!=?",
                    (body.scene_code, scene_id),
                )
                if dup:
                    raise HTTPException(status_code=409, detail=f"场景编码 '{body.scene_code}' 已被使用")
            sets.append("scene_code=?")
            params.append(body.scene_code)
        if body.parent_scene_id is not None:
            sets.append("parent_scene_id=?")
            params.append(body.parent_scene_id if body.parent_scene_id else None)
        if body.delete_flag is not None:
            sets.append("delete_flag=?")
            params.append(body.delete_flag)
        if not sets:
            return await get_scene(scene_id)

        params.append(scene_id)
        await _execute_scene(
            f"UPDATE ontol_model_scene SET {', '.join(sets)} WHERE id=?",
            tuple(params),
        )
        return await get_scene(scene_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scene update failed: {e}")


@router.delete("/scenes/{scene_id}")
async def delete_scene(scene_id: str, soft: bool = True):
    """删除场景（默认软删除）。系统预设场景（scene_is_system='1'）不可删除。"""
    try:
        # 检查是否为系统预设
        rows = await _query_scene(
            "SELECT scene_is_system FROM ontol_model_scene WHERE id=? AND delete_flag='0'",
            (scene_id,),
        )
        if rows and rows[0].get("scene_is_system") == "1":
            raise HTTPException(status_code=403, detail="系统预设场景不可删除")
        if soft:
            await _execute_scene(
                "UPDATE ontol_model_scene SET delete_flag='1' WHERE id=?",
                (scene_id,),
            )
        else:
            await _execute_scene(
                "DELETE FROM ontol_model_scene WHERE id=?",
                (scene_id,),
            )
        return {"deleted": True, "scene_id": scene_id, "soft": soft}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scene delete failed: {e}")


# =========================================================================
# 对话-场景关系 CRUD (ontol_char_scene_relation)
# =========================================================================

class ChatSceneBind(BaseModel):
    chart_id: str = Field(..., description="对话UUID")
    scene_ids: list[str] = Field(..., description="场景ID列表")


@router.post("/chat-scenes/bind")
async def bind_chat_scenes(body: ChatSceneBind):
    """将对话绑定到多个场景（先删旧绑定，再批量插入）。"""
    try:
        # 先清理旧绑定
        await _execute_scene(
            "UPDATE ontol_char_scene_relation SET delete_flag='1' WHERE chart_id=?",
            (body.chart_id,),
        )
        # 批量插入新绑定
        import uuid as _uuid
        for sid in body.scene_ids:
            rid = _uuid.uuid4().hex[:16]
            await _execute_scene(
                "INSERT INTO ontol_char_scene_relation (id, chart_id, scene_id) VALUES (?,?,?)",
                (rid, body.chart_id, sid),
            )
        return await get_chat_scenes(body.chart_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bind chat scenes failed: {e}")


@router.get("/chat-scenes/{chart_id}")
async def get_chat_scenes(chart_id: str):
    """获取对话绑定的场景列表（带场景名称）。"""
    try:
        rows = await _query_scene(
            """SELECT r.id, r.chart_id, r.scene_id, s.scene_name, s.scene_desc
               FROM ontol_char_scene_relation r
               LEFT JOIN ontol_model_scene s ON r.scene_id = s.id
               WHERE r.chart_id=? AND r.delete_flag='0'
               ORDER BY r.create_time""",
            (chart_id,),
        )
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query chat scenes failed: {e}")


@router.delete("/chat-scenes/{relation_id}")
async def unbind_chat_scene(relation_id: str):
    """删除对话-场景绑定（软删除）。"""
    try:
        await _execute_scene(
            "UPDATE ontol_char_scene_relation SET delete_flag='1' WHERE id=?",
            (relation_id,),
        )
        return {"deleted": True, "relation_id": relation_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unbind chat scene failed: {e}")


# =========================================================================
# 提示词管理 CRUD (ontol_scene_prompt)
# =========================================================================

class ScenePromptCreate(BaseModel):
    id: str = Field(..., max_length=32, description="提示词ID（主键）")
    scene_id: str = Field(..., max_length=32, description="所属场景ID")
    prompt_name: str = Field(..., max_length=100, description="提示词名称")
    prompt_content: str = Field(default="", description="提示词文本内容")
    prompt_desc: Optional[str] = Field(None, max_length=500, description="提示词描述")
    prompt_description: Optional[str] = Field(None, max_length=500, description="提示词调用时机说明")
    create_id: Optional[str] = Field(None, max_length=32, description="创建人ID")

class ScenePromptUpdate(BaseModel):
    prompt_name: Optional[str] = Field(None, max_length=100)
    prompt_content: Optional[str] = None
    prompt_desc: Optional[str] = Field(None, max_length=500)
    prompt_description: Optional[str] = Field(None, max_length=500)
    delete_flag: Optional[str] = Field(None, max_length=2)


@router.get("/scenes/{scene_id}/prompts")
async def list_scene_prompts(scene_id: str):
    """列出场景下的所有提示词。"""
    try:
        rows = await _query_scene(
            "SELECT * FROM ontol_scene_prompt WHERE scene_id=? AND delete_flag='0' ORDER BY create_time DESC",
            (scene_id,),
        )
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query prompts failed: {e}")


@router.get("/prompts/{prompt_id}")
async def get_prompt(prompt_id: str):
    """获取单个提示词详情。"""
    try:
        rows = await _query_scene(
            "SELECT * FROM ontol_scene_prompt WHERE id=? AND delete_flag='0'",
            (prompt_id,),
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"Prompt {prompt_id} not found")
        return rows[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query prompt failed: {e}")


@router.post("/scenes/{scene_id}/prompts", status_code=201)
async def create_prompt(scene_id: str, body: ScenePromptCreate):
    """创建提示词。后端生成 UUID 主键。"""
    import uuid as _uuid
    try:
        prompt_id = body.id if body.id else _uuid.uuid4().hex[:16]
        existing = await _query_scene("SELECT id FROM ontol_scene_prompt WHERE id=?", (prompt_id,))
        if existing:
            raise HTTPException(status_code=409, detail=f"Prompt ID '{prompt_id}' already exists")
        await _execute_scene(
            "INSERT INTO ontol_scene_prompt (id, scene_id, prompt_name, prompt_content, prompt_desc, prompt_description, create_id) VALUES (?,?,?,?,?,?,?)",
            (prompt_id, scene_id, body.prompt_name, body.prompt_content or "", body.prompt_desc or "", body.prompt_description or "", body.create_id or ""),
        )
        rows = await _query_scene("SELECT * FROM ontol_scene_prompt WHERE id=?", (prompt_id,))
        return rows[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Create prompt failed: {e}")


@router.put("/prompts/{prompt_id}")
async def update_prompt(prompt_id: str, body: ScenePromptUpdate):
    """更新提示词。"""
    try:
        existing = await _query_scene("SELECT id FROM ontol_scene_prompt WHERE id=? AND delete_flag='0'", (prompt_id,))
        if not existing:
            raise HTTPException(status_code=404, detail=f"Prompt {prompt_id} not found")
        data = body.model_dump(exclude_none=True)
        if data:
            set_clause = ", ".join(f"{k}=?" for k in data)
            values = list(data.values()) + [prompt_id]
            await _execute_scene(f"UPDATE ontol_scene_prompt SET {set_clause} WHERE id=?", tuple(values))
        rows = await _query_scene("SELECT * FROM ontol_scene_prompt WHERE id=?", (prompt_id,))
        return rows[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update prompt failed: {e}")


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str, soft: bool = True):
    """删除提示词（默认软删除）。"""
    try:
        if soft:
            await _execute_scene("UPDATE ontol_scene_prompt SET delete_flag='1' WHERE id=?", (prompt_id,))
        else:
            await _execute_scene("DELETE FROM ontol_scene_prompt WHERE id=?", (prompt_id,))
        return {"deleted": True, "prompt_id": prompt_id, "soft": soft}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete prompt failed: {e}")


# =========================================================================
# 场景词典 CRUD (ontol_scene_dictionary)
# =========================================================================

class SceneDictCreate(BaseModel):
    id: str = Field(default="", max_length=32, description="词典ID，留空自动生成UUID")
    scene_id: str = Field(..., max_length=32, description="所属场景ID")
    dictionary_name: str = Field(..., max_length=200, description="词典名称")
    dictionary_type_id: Optional[str] = Field(None, max_length=32, description="词条分类ID")
    dictionary_content: Optional[str] = Field(None, description="词典内容")

class SceneDictUpdate(BaseModel):
    dictionary_name: Optional[str] = Field(None, max_length=200)
    dictionary_type_id: Optional[str] = Field(None, max_length=32)
    dictionary_content: Optional[str] = None
    delete_flag: Optional[str] = Field(None, max_length=2)


@router.get("/scenes/{scene_id}/dictionaries")
async def list_scene_dicts(scene_id: str):
    """列出场景下的所有词典，连带词条分类名。"""
    try:
        rows = await _query_scene(
            """SELECT d.*, dt.dictionary_type_name
               FROM ontol_scene_dictionary d
               LEFT JOIN ontol_dictionary_type dt ON d.dictionary_type_id = dt.id
               WHERE d.scene_id=? AND d.delete_flag='0'
               ORDER BY d.create_time DESC""",
            (scene_id,),
        )
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query dictionaries failed: {e}")


@router.get("/dictionaries")
async def list_all_dicts(dictionary_type_id: str = ""):
    """列出所有词典（可选的按词条分类筛选），带场景名和分类名。"""
    try:
        if dictionary_type_id:
            rows = await _query_scene(
                """SELECT d.*, s.scene_name, dt.dictionary_type_name
                   FROM ontol_scene_dictionary d
                   LEFT JOIN ontol_model_scene s ON d.scene_id = s.id
                   LEFT JOIN ontol_dictionary_type dt ON d.dictionary_type_id = dt.id
                   WHERE d.delete_flag='0' AND d.dictionary_type_id=?
                   ORDER BY d.create_time DESC""",
                (dictionary_type_id,),
            )
        else:
            rows = await _query_scene(
                """SELECT d.*, s.scene_name, dt.dictionary_type_name
                   FROM ontol_scene_dictionary d
                   LEFT JOIN ontol_model_scene s ON d.scene_id = s.id
                   LEFT JOIN ontol_dictionary_type dt ON d.dictionary_type_id = dt.id
                   WHERE d.delete_flag='0'
                   ORDER BY d.create_time DESC"""
            )
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query dictionaries failed: {e}")


@router.post("/dictionaries", status_code=201)
async def create_dict_direct(body: SceneDictCreate):
    """创建词典（直发接口，scene_id 从 body 传入）。"""
    import uuid as _uuid
    try:
        dict_id = body.id.strip() if body.id else _uuid.uuid4().hex[:16]
        existing = await _query_scene("SELECT id FROM ontol_scene_dictionary WHERE id=?", (dict_id,))
        if existing:
            raise HTTPException(status_code=409, detail=f"Dictionary ID '{dict_id}' already exists")
        await _execute_scene(
            "INSERT INTO ontol_scene_dictionary (id, scene_id, dictionary_name, dictionary_type_id, dictionary_content) VALUES (?,?,?,?,?)",
            (dict_id, body.scene_id, body.dictionary_name, body.dictionary_type_id or None, body.dictionary_content or ""),
        )
        rows = await _query_scene("SELECT * FROM ontol_scene_dictionary WHERE id=?", (dict_id,))
        return rows[0]
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=f"Create dictionary failed: {e}")


@router.get("/dictionaries/{dict_id}")
async def get_dict(dict_id: str):
    """获取单个词典详情。"""
    try:
        rows = await _query_scene(
            "SELECT * FROM ontol_scene_dictionary WHERE id=? AND delete_flag='0'",
            (dict_id,),
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"Dictionary {dict_id} not found")
        return rows[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query dictionary failed: {e}")


@router.post("/scenes/{scene_id}/dictionaries", status_code=201)
async def create_dict(scene_id: str, body: SceneDictCreate):
    """创建场景词典，id 留空自动生成 UUID。"""
    import uuid as _uuid
    try:
        dict_id = body.id.strip() if body.id else _uuid.uuid4().hex[:16]
        existing = await _query_scene("SELECT id FROM ontol_scene_dictionary WHERE id=?", (dict_id,))
        if existing:
            raise HTTPException(status_code=409, detail=f"Dictionary ID '{dict_id}' already exists")
        await _execute_scene(
            "INSERT INTO ontol_scene_dictionary (id, scene_id, dictionary_name, dictionary_type_id, dictionary_content) VALUES (?,?,?,?,?)",
            (dict_id, scene_id, body.dictionary_name, body.dictionary_type_id or None, body.dictionary_content or ""),
        )
        rows = await _query_scene("SELECT * FROM ontol_scene_dictionary WHERE id=?", (dict_id,))
        return rows[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Create dictionary failed: {e}")


@router.put("/dictionaries/{dict_id}")
async def update_dict(dict_id: str, body: SceneDictUpdate):
    """更新场景词典。"""
    try:
        existing = await _query_scene("SELECT id FROM ontol_scene_dictionary WHERE id=? AND delete_flag='0'", (dict_id,))
        if not existing:
            raise HTTPException(status_code=404, detail=f"Dictionary {dict_id} not found")
        data = body.model_dump(exclude_none=True)
        if data:
            set_clause = ", ".join(f"{k}=?" for k in data)
            values = list(data.values()) + [dict_id]
            await _execute_scene(f"UPDATE ontol_scene_dictionary SET {set_clause} WHERE id=?", tuple(values))
        rows = await _query_scene("SELECT * FROM ontol_scene_dictionary WHERE id=?", (dict_id,))
        return rows[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update dictionary failed: {e}")


@router.delete("/dictionaries/{dict_id}")
async def delete_dict(dict_id: str, soft: bool = True):
    """删除场景词典（默认软删除）。"""
    try:
        if soft:
            await _execute_scene("UPDATE ontol_scene_dictionary SET delete_flag='1' WHERE id=?", (dict_id,))
        else:
            await _execute_scene("DELETE FROM ontol_scene_dictionary WHERE id=?", (dict_id,))
        return {"deleted": True, "dict_id": dict_id, "soft": soft}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete dictionary failed: {e}")


# =========================================================================
# 词条分类 CRUD (ontol_dictionary_type)
# =========================================================================

class DictTypeCreate(BaseModel):
    id: str = Field(default="", max_length=32, description="UUID")
    dictionary_type_name: str = Field(..., max_length=200, description="分类名称")
    dictionary_description: Optional[str] = Field(None, max_length=500)
    is_system: str = Field(default="0", max_length=1, description="是否系统预设")

class DictTypeUpdate(BaseModel):
    dictionary_type_name: Optional[str] = Field(None, max_length=200)
    dictionary_description: Optional[str] = Field(None, max_length=500)
    delete_flag: Optional[str] = Field(None, max_length=2)


@router.get("/dictionary-types")
async def list_dict_types():
    """列出所有词条分类。"""
    try:
        rows = await _query_scene(
            "SELECT * FROM ontol_dictionary_type WHERE delete_flag='0' ORDER BY create_time DESC"
        )
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query dictionary types failed: {e}")


@router.get("/dictionary-types/{type_id}")
async def get_dict_type(type_id: str):
    """获取单个词条分类。"""
    try:
        rows = await _query_scene(
            "SELECT * FROM ontol_dictionary_type WHERE id=? AND delete_flag='0'", (type_id,),
        )
        if not rows: raise HTTPException(status_code=404, detail="Not found")
        return rows[0]
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=f"Query failed: {e}")


@router.post("/dictionary-types", status_code=201)
async def create_dict_type(body: DictTypeCreate):
    """创建词条分类。"""
    import uuid as _uuid
    try:
        tid = body.id.strip() if body.id else _uuid.uuid4().hex[:16]
        await _execute_scene(
            "INSERT INTO ontol_dictionary_type (id, dictionary_type_name, dictionary_description, is_system) VALUES (?,?,?,?)",
            (tid, body.dictionary_type_name, body.dictionary_description or "", body.is_system),
        )
        rows = await _query_scene("SELECT * FROM ontol_dictionary_type WHERE id=?", (tid,))
        return rows[0]
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=f"Create failed: {e}")


@router.put("/dictionary-types/{type_id}")
async def update_dict_type(type_id: str, body: DictTypeUpdate):
    """更新词条分类。系统预设不可修改。"""
    try:
        existing = await _query_scene("SELECT * FROM ontol_dictionary_type WHERE id=? AND delete_flag='0'", (type_id,))
        if not existing: raise HTTPException(status_code=404, detail="Not found")
        if existing[0].get("is_system") == "1":
            raise HTTPException(status_code=403, detail="系统预设分类不可修改")
        data = body.model_dump(exclude_none=True)
        if data:
            sets = ", ".join(f"{k}=?" for k in data)
            await _execute_scene(f"UPDATE ontol_dictionary_type SET {sets} WHERE id=?", tuple(data.values()) + (type_id,))
        rows = await _query_scene("SELECT * FROM ontol_dictionary_type WHERE id=?", (type_id,))
        return rows[0]
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=f"Update failed: {e}")


@router.delete("/dictionary-types/{type_id}")
async def delete_dict_type(type_id: str, soft: bool = True):
    """删除词条分类。系统预设不可删除。"""
    try:
        existing = await _query_scene("SELECT is_system FROM ontol_dictionary_type WHERE id=? AND delete_flag='0'", (type_id,))
        if not existing: raise HTTPException(status_code=404, detail="Not found")
        if existing[0].get("is_system") == "1":
            raise HTTPException(status_code=403, detail="系统预设分类不可删除")
        if soft:
            await _execute_scene("UPDATE ontol_dictionary_type SET delete_flag='1' WHERE id=?", (type_id,))
        else:
            await _execute_scene("DELETE FROM ontol_dictionary_type WHERE id=?", (type_id,))
        return {"deleted": True, "type_id": type_id, "soft": soft}
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=f"Delete failed: {e}")


# =========================================================================
# LLM 类型配置 CRUD (ontol_llm_type_config)
# =========================================================================

class LLMTypeConfigCreate(BaseModel):
    id: str = Field(default="", max_length=32, description="UUID")
    llm_type_name: str = Field(..., max_length=200, description="类型名称")
    llm_description: Optional[str] = Field(None, max_length=500)
    is_system: str = Field(default="0", max_length=1, description="是否系统预设 0自定义/1系统")

class LLMTypeConfigUpdate(BaseModel):
    llm_type_name: Optional[str] = Field(None, max_length=200)
    llm_description: Optional[str] = Field(None, max_length=500)
    delete_flag: Optional[str] = Field(None, max_length=2)


@router.get("/llm-type-configs")
async def list_llm_type_configs():
    """列出所有 LLM 类型配置。"""
    try:
        rows = await _query_scene(
            "SELECT * FROM ontol_llm_type_config WHERE delete_flag='0' ORDER BY create_time DESC"
        )
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")


@router.get("/llm-type-configs/{config_id}")
async def get_llm_type_config(config_id: str):
    """获取单个类型配置。"""
    try:
        rows = await _query_scene(
            "SELECT * FROM ontol_llm_type_config WHERE id=? AND delete_flag='0'", (config_id,),
        )
        if not rows: raise HTTPException(status_code=404, detail=f"Not found")
        return rows[0]
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=f"Query failed: {e}")


@router.post("/llm-type-configs", status_code=201)
async def create_llm_type_config(body: LLMTypeConfigCreate):
    """创建 LLM 类型配置。"""
    import uuid as _uuid
    try:
        cid = body.id.strip() if body.id else _uuid.uuid4().hex[:16]
        await _execute_scene(
            "INSERT INTO ontol_llm_type_config (id, llm_type_name, llm_description, is_system) VALUES (?,?,?,?)",
            (cid, body.llm_type_name, body.llm_description or "", body.is_system),
        )
        rows = await _query_scene("SELECT * FROM ontol_llm_type_config WHERE id=?", (cid,))
        return rows[0]
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=f"Create failed: {e}")


@router.put("/llm-type-configs/{config_id}")
async def update_llm_type_config(config_id: str, body: LLMTypeConfigUpdate):
    """更新类型配置。系统预设（is_system='1'）不可修改。"""
    try:
        existing = await _query_scene("SELECT * FROM ontol_llm_type_config WHERE id=? AND delete_flag='0'", (config_id,))
        if not existing: raise HTTPException(status_code=404, detail=f"Not found")
        if existing[0].get("is_system") == "1":
            raise HTTPException(status_code=403, detail="系统预设分类不可修改")
        data = body.model_dump(exclude_none=True)
        if data:
            sets = ", ".join(f"{k}=?" for k in data)
            await _execute_scene(f"UPDATE ontol_llm_type_config SET {sets} WHERE id=?", tuple(data.values()) + (config_id,))
        rows = await _query_scene("SELECT * FROM ontol_llm_type_config WHERE id=?", (config_id,))
        return rows[0]
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=f"Update failed: {e}")


@router.delete("/llm-type-configs/{config_id}")
async def delete_llm_type_config(config_id: str, soft: bool = True):
    """删除类型配置。系统预设（is_system='1'）不可删除。"""
    try:
        existing = await _query_scene("SELECT is_system FROM ontol_llm_type_config WHERE id=? AND delete_flag='0'", (config_id,))
        if not existing: raise HTTPException(status_code=404, detail=f"Not found")
        if existing[0].get("is_system") == "1":
            raise HTTPException(status_code=403, detail="系统预设分类不可删除")
        if soft:
            await _execute_scene("UPDATE ontol_llm_type_config SET delete_flag='1' WHERE id=?", (config_id,))
        else:
            await _execute_scene("DELETE FROM ontol_llm_type_config WHERE id=?", (config_id,))
        return {"deleted": True, "config_id": config_id, "soft": soft}
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=f"Delete failed: {e}")


# =========================================================================
# LLM 模型配置 CRUD (ontol_llm_config)
# =========================================================================

class LLMConfigCreate(BaseModel):
    id: str = Field(default="", max_length=32, description="UUID")
    llm_type_config_id: Optional[str] = Field(None, max_length=32, description="所属类型配置ID")
    llm_name: str = Field(..., max_length=200, description="显示名")
    llm_model: Optional[str] = Field(None, max_length=200, description="API模型名（如 deepseek-v4-pro）")
    llm_url: Optional[str] = Field(None, max_length=500, description="调用地址")
    llm_key: Optional[str] = Field(None, max_length=500, description="调用Key")
    llm_description: Optional[str] = Field(None, max_length=500, description="描述说明")

class LLMConfigUpdate(BaseModel):
    llm_type_config_id: Optional[str] = Field(None, max_length=32)
    llm_name: Optional[str] = Field(None, max_length=200)
    llm_model: Optional[str] = Field(None, max_length=200)
    llm_url: Optional[str] = Field(None, max_length=500)
    llm_key: Optional[str] = Field(None, max_length=500)
    llm_description: Optional[str] = Field(None, max_length=500)
    delete_flag: Optional[str] = Field(None, max_length=2)


@router.get("/llm-configs")
async def list_llm_configs(type_config_id: Optional[str] = None):
    """列出 LLM 配置，可按类型配置ID筛选。"""
    try:
        if type_config_id:
            rows = await _query_scene(
                "SELECT * FROM ontol_llm_config WHERE delete_flag='0' AND llm_type_config_id=? ORDER BY create_time DESC",
                (type_config_id,),
            )
        else:
            rows = await _query_scene(
                "SELECT * FROM ontol_llm_config WHERE delete_flag='0' ORDER BY create_time DESC"
            )
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query llm configs failed: {e}")


@router.get("/llm-configs/{config_id}")
async def get_llm_config(config_id: str):
    """获取单个 LLM 配置详情。"""
    try:
        rows = await _query_scene(
            "SELECT * FROM ontol_llm_config WHERE id=? AND delete_flag='0'",
            (config_id,),
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"Config {config_id} not found")
        return rows[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query config failed: {e}")


@router.post("/llm-configs", status_code=201)
async def create_llm_config(body: LLMConfigCreate):
    """创建 LLM 配置，id 留空自动 UUID。"""
    import uuid as _uuid
    try:
        cfg_id = body.id.strip() if body.id else _uuid.uuid4().hex[:16]
        existing = await _query_scene("SELECT id FROM ontol_llm_config WHERE id=?", (cfg_id,))
        if existing:
            raise HTTPException(status_code=409, detail=f"Config ID '{cfg_id}' already exists")
        await _execute_scene(
            "INSERT INTO ontol_llm_config (id, llm_type_config_id, llm_name, llm_model, llm_url, llm_key, llm_description) VALUES (?,?,?,?,?,?,?)",
            (cfg_id, body.llm_type_config_id or None, body.llm_name, body.llm_model or None, body.llm_url or "", body.llm_key or "", body.llm_description or ""),
        )
        rows = await _query_scene("SELECT * FROM ontol_llm_config WHERE id=?", (cfg_id,))
        return rows[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Create config failed: {e}")


@router.put("/llm-configs/{config_id}")
async def update_llm_config(config_id: str, body: LLMConfigUpdate):
    """更新 LLM 配置。"""
    try:
        existing = await _query_scene("SELECT id FROM ontol_llm_config WHERE id=? AND delete_flag='0'", (config_id,))
        if not existing:
            raise HTTPException(status_code=404, detail=f"Config {config_id} not found")
        data = body.model_dump(exclude_none=True)
        if data:
            set_clause = ", ".join(f"{k}=?" for k in data)
            values = list(data.values()) + [config_id]
            await _execute_scene(f"UPDATE ontol_llm_config SET {set_clause} WHERE id=?", tuple(values))
        rows = await _query_scene("SELECT * FROM ontol_llm_config WHERE id=?", (config_id,))
        return rows[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update config failed: {e}")


@router.delete("/llm-configs/{config_id}")
async def delete_llm_config(config_id: str, soft: bool = True):
    """删除 LLM 配置（默认软删除）。"""
    try:
        if soft:
            await _execute_scene("UPDATE ontol_llm_config SET delete_flag='1' WHERE id=?", (config_id,))
        else:
            await _execute_scene("DELETE FROM ontol_llm_config WHERE id=?", (config_id,))
        return {"deleted": True, "config_id": config_id, "soft": soft}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete config failed: {e}")
