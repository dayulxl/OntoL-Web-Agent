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

# 业务层导入 — 路由只做参数解析 + 调用 + 格式化响应
from business.ontology import load_ontology_types as _load_ontology_types, get_inherited_fields as _get_inherited_fields
from business.tool.snowflake import SnowflakeGenerator as _SnowflakeGenerator
from business.upload.auto_import.step2_validate import validate_entities as _validate_entities_for_import

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

    code: str = Field(..., max_length=50, description="本体编码（唯一）")
    ontol_parent_id: Optional[str] = Field(None, max_length=32, description="父级模型ID")
    name: str = Field(..., max_length=50, description="本体名称")
    ontol_data_type: str = Field(..., max_length=4, description="本体类型：M1实体/M2行为/M3规则/M4场景/M5主体/M6异常/M7质量/ME事件/MT模板 边的类型")
    ontol_model_type: Optional[str] = Field(None, max_length=50, description="英文简写（不可重复）")
    ontol_model_status: str = Field("0", max_length=2, description="本体状态：0=启用中 1=已停用")
    ontol_model_desc: Optional[str] = Field(None, max_length=255, description="本体描述")

class OntolModelUpdateBody(BaseModel):
    model_config = {"extra": "ignore"}
    code: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, max_length=50)
    ontol_data_type: Optional[str] = Field(None, max_length=4)
    ontol_model_type: Optional[str] = Field(None, max_length=50)
    ontol_model_status: Optional[str] = Field(None, max_length=2)
    ontol_model_desc: Optional[str] = Field(None, max_length=255)

class OntolModelAttrCreateBody(BaseModel):
    model_config = {"extra": "ignore"}

    id: str = Field(..., max_length=32, description="属性ID（主键）")
    ontol_model_id: Optional[str] = Field(None, max_length=32)
    name: str = Field(..., max_length=50)
    code: str = Field(..., max_length=50)
    attr_data_type: str = Field("VARCHAR", max_length=20)
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

    name: Optional[str] = Field(None, max_length=50)
    code: Optional[str] = Field(None, max_length=50)
    attr_data_type: Optional[str] = Field(None, max_length=20)
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
    """创建节点，自动生成雪花 ID（64 位纯数字）。"""
    try:
        # 生成雪花 ID（去重）
        import time as _time
        sf = _SnowflakeGenerator(
            worker_id=(int(_time.time() * 1000) & 0x1F),
            datacenter_id=1,
        )
        # 查询已存在的节点 ID，避免冲突
        existing = await graph.execute_readonly_cypher("MATCH (n) WHERE n.id IS NOT NULL RETURN n.id AS id LIMIT 5000")
        existing_ids = {r["id"] for r in existing if isinstance(r.get("id"), int)}
        snowflake_id = sf.next_id()
        while snowflake_id in existing_ids:
            snowflake_id = sf.next_id()

        props = dict(body.properties)
        # 雪花 ID：如果前端没传 id 或 id 为空/占位符，自动生成
        if not props.get("id") or props.get("id") == "大模型随机生成":
            props["id"] = snowflake_id

        result = await graph.create_node(body.label, props)
        # 记录历史
        await _record_history(str(result.get("id", "")), "create", {"label": body.label, "new_props": props})
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


class EdgeUpdate(BaseModel):
    properties: dict = Field(default_factory=dict, description="边的属性（完整替换）")


@router.put("/ontology/edges/{edge_id}")
async def update_edge(edge_id: int, body: EdgeUpdate, graph=Depends(get_graph)):
    """更新边的属性。"""
    try:
        result = await graph.update_edge(edge_id, body.properties or {})
        if not result:
            raise HTTPException(status_code=404, detail=f"Edge {edge_id} not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Graph DB update edge failed: {e}")


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


class InferOnNodesBody(BaseModel):
    node_ids: list[str] = Field(default_factory=list, description="节点内置ID列表")
    confidence: float = Field(default=0.8, description="置信度")
    copy_version: str = Field(default="", alias="cope_version", description="副本版本号")

    class Config:
        populate_by_name = True


@router.post("/infer-on-nodes")
async def infer_on_nodes(body: InferOnNodesBody):
    """调用内部图推理机 — 流式收集结果，返回 messages 数组给前端。"""
    from business.reasoning import run_reasoning

    # 解析 node_id：支持纯数字 Snowflake ID 或字符串 code
    async def _resolve_seed_id(raw: str) -> int | None:
        try:
            return int(raw)
        except ValueError:
            pass
        # 可能是 code 或名称
        try:
            from infrastructure.db.neo4j import get_driver
            driver = await get_driver()
            async with driver.session() as session:
                rec = await session.run(
                    "MATCH (n) WHERE n.code = $raw OR n.name = $raw "
                    "RETURN id(n) AS id LIMIT 1", raw=raw)
                row = await rec.single()
                return row["id"] if row else None
        except Exception:
            return None

    if not body.node_ids:
        return {"ok": False, "messages": ["❌ 未指定推理节点"]}

    # 取第一个节点作为种子
    seed_id = await _resolve_seed_id(body.node_ids[0])
    if seed_id is None:
        return {"ok": False, "messages": [f"❌ 无法找到节点: {body.node_ids[0]}"]}

    result = await run_reasoning(
        seed_node_id=seed_id,
        copy_version=body.copy_version,
        confidence_threshold=body.confidence,
    )

    return {
        "ok": result["error"] is None,
        "messages": result["log"],
        "copy_version": result["copy_version"],
        "clone_count": result["clone_count"],
        "edges_built": result["edges_built"],
    }


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
            where["ontol_data_type"] = model_type
        if status:
            where["ontol_model_status"] = status
        return await temp.search(keyword, columns=["name", "ontol_model_desc"], where=where, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Search failed: {e}")


@router.get("/ontology-models/types/flat")
async def list_ontology_types_flat():
    """获取所有本体类型扁平列表（供下拉框使用），含字段数。"""
    types = _load_ontology_types()
    result = []
    for tid, t in types.items():
        inherited = _get_inherited_fields(tid)
        result.append({
            "id": tid,
            "name": t["name"],
            "type_code": t["type_code"],
            "parent_id": t["parent_id"],
            "desc": t.get("desc", ""),
            "field_count": len(inherited),
        })
    result.sort(key=lambda x: (x["type_code"] or "", x["name"]))
    return result


@router.get("/ontology-models/{model_id}/inherited-fields")
async def get_model_inherited_fields(model_id: str):
    """获取指定本体模型的完整字段列表（含继承链：M_ROOT → ... → 当前模型）。

    子类型字段覆盖父类型同名字段，返回以 code 为键的字段列表。
    """
    from fastapi import HTTPException as _HTTPException
    types = _load_ontology_types()
    if model_id not in types:
        raise _HTTPException(status_code=404, detail=f"本体模型不存在: {model_id}")
    fields = _get_inherited_fields(model_id)
    # 按 source 分组排序（M_ROOT 的字段在前，当前模型的在后）
    sorted_fields = sorted(fields.values(), key=lambda f: (f.get("source_model", "") == model_id, f.get("order", 0), f.get("code", "")))
    return {
        "model_id": model_id,
        "model_name": types[model_id]["name"],
        "type_code": types[model_id]["type_code"],
        "field_count": len(sorted_fields),
        "fields": sorted_fields,
    }


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
    """创建本体模型（后端生成 UUID 主键，code 由用户指定并唯一校验）。"""
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
# Excel 批量导入/导出 — 业务逻辑在 business/upload/excel_service.py
# =========================================================================

_EXCEL_COLS = [
    {"key": "action",   "label": "操作",     "width": 10},
    {"key": "code",     "label": "字段编码",  "width": 18},
    {"key": "name",     "label": "字段名称",  "width": 16},
    {"key": "data_type","label": "数据类型",  "width": 12},
    {"key": "length",   "label": "长度",     "width": 8},
    {"key": "required", "label": "必填",      "width": 7},
    {"key": "is_only",  "label": "唯一",      "width": 7},
    {"key": "default",  "label": "默认值",    "width": 14},
    {"key": "desc",     "label": "描述",      "width": 24},
]


@router.get("/ontology-models/{model_id}/export-excel")
async def export_model_attrs_excel(model_id: str, attr_mapping: str = "00"):
    """导出模型字段为 Excel 模板。"""
    import tempfile
    from business.upload.excel_service import export_attrs
    from business.tool.excel_handler import write_excel, excel_response

    model_name, rows = export_attrs(model_id, attr_mapping)
    for _ in range(5):
        rows.append({c["key"]: "" for c in _EXCEL_COLS})
    tmp = tempfile.mktemp(suffix=".xlsx")
    write_excel(tmp, "字段模板", _EXCEL_COLS, rows, validations=[
        {"col": 1, "options": ["新增", "修改", "删除"], "prompt": "请选择操作类型"},
    ])
    return excel_response(tmp, f"{model_name}_{model_id}_字段模板.xlsx")


@router.post("/ontology-models/{model_id}/import-excel")
async def import_model_attrs_excel(
    model_id: str,
    file: UploadFile = File(...),
    attr_mapping: str = "00",
):
    """上传 Excel 批量处理字段 — 新增/修改/删除。"""
    import tempfile
    from business.tool.excel_handler import read_excel
    from business.upload.excel_service import import_attrs

    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx/.xls 文件")
    tmp = tempfile.mktemp(suffix=".xlsx")
    with open(tmp, "wb") as f:
        f.write(await file.read())
    try:
        headers, rows = read_excel(tmp)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Excel 解析失败: {e}")

    col_map = {"操作":"action","字段编码":"code","字段名称":"name","数据类型":"data_type",
               "长度":"length","必填":"required","唯一":"is_only","默认值":"default","描述":"desc"}
    normalized = []
    for row in rows:
        nr = {}
        for h, v in row.items():
            nr[col_map.get(h, h)] = v
        normalized.append(nr)

    return import_attrs(model_id, attr_mapping, normalized)


# =========================================================================
# Upload & File Management
# =========================================================================
import os
import json as _json
from datetime import datetime

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

_ONTOLOGY_TREE_CACHE: Optional[list] = None   # 树形结构（含层级关系）


# ── 上传解析/导入路由 — 业务逻辑已迁移至 business/upload/ ──


class ParseTriplesRequest(BaseModel):
    filename: str = Field(..., description="要解析的文件名")
    model: str = Field("", description="使用的 LLM 模型名")


class ImportEntitiesRequest(BaseModel):
    filename: str = Field(..., description="来源文件名")
    entities: list[dict] = Field(..., description="本体实体列表")
    relationships: list[dict] = Field(default_factory=list, description="关系列表")
    scene_ids: list[str] = Field(default_factory=list, description="关联的场景ID列表")


class ValidateEntitiesRequest(BaseModel):
    entities: list[dict] = Field(..., description="待校验的实体列表")


@router.post("/upload/validate-entities")
async def validate_entities_for_import(body: ValidateEntitiesRequest):
    """校验实体，检查本体模板匹配 + 缺失字段。业务逻辑在 business/upload/validation.py。"""
    return _validate_entities_for_import(body.entities)


# [FEAT] Step 3: 符号语言填充 & 推理机校验 — 唯一入口 business/api/
class EnrichEntitiesRequest(BaseModel):
    entities: list[dict] = Field(..., description="待富化的实体列表")
    relationships: list[dict] = Field(default_factory=list, description="关系列表")


@router.post("/upload/enrich-entities")
async def enrich_entities_for_import(body: EnrichEntitiesRequest):
    """Step 3 — 7种符号语言识别 → 填充标准边属性 → 结构校验。"""
    from business.api import enrich_entities as _enrich
    result = _enrich(body.entities, body.relationships)
    return {
        "entities": result.entities,
        "relationships": result.relationships,
        "symbol_stats": result.symbol_stats,
        "edge_props_filled": result.edge_props_filled,
        "node_symbols_found": result.node_symbols_found,
        "warnings": [
            {"level": w.level, "target": w.target, "message": w.message}
            for w in result.warnings
        ],
        "error_count": result.error_count,
        "warn_count": result.warn_count,
    }


@router.post("/upload/parse")
async def parse_file_to_entities(body: ParseTriplesRequest):
    """两阶段 AI 解析：分类 → 字段提取。业务逻辑在 business/upload/parser.py。"""
    from business.upload.auto_import.step1_parse import run_parse_pipeline
    return await run_parse_pipeline(body.filename, body.model)


@router.post("/upload/import-entities")
async def import_entities_to_neo4j(body: ImportEntitiesRequest):
    """导入实体和关系到图数据库。业务逻辑在 business/upload/import_service.py。"""
    from business.upload.auto_import.step4_import import import_to_graph
    import traceback, logging
    _logger = logging.getLogger(__name__)
    try:
        return await import_to_graph(
            body.entities, body.relationships, body.scene_ids, body.filename,
        )
    except Exception as e:
        _logger.error(f"实体导入失败: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"导入失败: {e}")


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
    name: str = Field(..., max_length=100, description="场景名称")
    code: Optional[str] = Field(None, max_length=50, description="场景编码（唯一）")
    scene_desc: Optional[str] = Field(None, max_length=500, description="场景描述")
    parent_scene_id: Optional[str] = Field(None, max_length=32, description="父场景ID")
    create_id: Optional[str] = Field(None, max_length=32, description="创建人ID")

class SceneUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100, description="场景名称")
    code: Optional[str] = Field(None, max_length=50, description="场景编码")
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
                "SELECT * FROM ontol_model_scene WHERE delete_flag='0' AND (name LIKE ? OR scene_desc LIKE ?) ORDER BY create_time DESC",
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

        # 检查 code 唯一性
        if body.code:
            dup = await _query_scene(
                "SELECT id FROM ontol_model_scene WHERE code=? AND delete_flag='0'",
                (body.code,),
            )
            if dup:
                raise HTTPException(status_code=409, detail=f"场景编码 '{body.code}' 已被使用")

        await _execute_scene(
            "INSERT INTO ontol_model_scene (id, name, code, scene_desc, parent_scene_id, create_id) VALUES (?,?,?,?,?,?)",
            (scene_id, body.name, body.code or None, body.scene_desc or "", body.parent_scene_id or None, body.create_id or ""),
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
        if body.name is not None:
            sets.append("name=?")
            params.append(body.name)
        if body.scene_desc is not None:
            sets.append("scene_desc=?")
            params.append(body.scene_desc)
        if body.code is not None:
            if body.code:
                dup = await _query_scene(
                    "SELECT id FROM ontol_model_scene WHERE code=? AND delete_flag='0' AND id!=?",
                    (body.code, scene_id),
                )
                if dup:
                    raise HTTPException(status_code=409, detail=f"场景编码 '{body.code}' 已被使用")
            sets.append("code=?")
            params.append(body.code)
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
# 对话主表 CRUD (ontol_char) — [FEAT] 对话元数据存 DB，消息内容仍存浏览器 localStorage
# 业务逻辑集中在 business/chat/chat_service.py，路由只做参数校验 + 调用 + 响应
# =========================================================================

class ChatCreate(BaseModel):
    id: str = Field(..., description="对话UUID (chart_id)")
    name: str = Field(default="新对话", description="对话名称")
    code: Optional[str] = Field(default="", description="编码")


class ChatUpdate(BaseModel):
    name: Optional[str] = Field(None, description="对话名称")


@router.post("/chats")
async def create_chat(body: ChatCreate):
    """创建对话记录。"""
    try:
        from business.chat import chat_service
        rid = chat_service.create_chat(body.id, body.name, body.code or "")
        return {"id": rid, "name": body.name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Create chat failed: {e}")


@router.get("/chats")
async def list_chats():
    """查询对话列表（按更新时间降序）。"""
    try:
        from business.chat import chat_service
        return chat_service.list_chats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"List chats failed: {e}")


@router.put("/chats/{chat_id}")
async def update_chat(chat_id: str, body: ChatUpdate):
    """更新对话名称。"""
    try:
        from business.chat import chat_service
        ok = chat_service.update_chat(chat_id, body.name)
        if not ok:
            raise HTTPException(status_code=404, detail="Chat not found")
        return {"updated": True, "id": chat_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update chat failed: {e}")


@router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str):
    """软删除对话记录。"""
    try:
        from business.chat import chat_service
        chat_service.delete_chat(chat_id)
        return {"deleted": True, "id": chat_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete chat failed: {e}")


# =========================================================================
# 对话-场景关系 CRUD (ontol_char_scene_relation)
# =========================================================================

class ChatSceneBind(BaseModel):
    chat_id: str = Field(..., description="对话UUID")
    scene_ids: list[str] = Field(..., description="场景ID列表")


@router.post("/chat-scenes/bind")
async def bind_chat_scenes(body: ChatSceneBind):
    """将对话绑定到多个场景（先删旧绑定，再批量插入）。"""
    try:
        # 先清理旧绑定
        await _execute_scene(
            "UPDATE ontol_char_scene_relation SET delete_flag='1' WHERE chat_id=?",
            (body.chat_id,),
        )
        # 批量插入新绑定
        import uuid as _uuid
        for sid in body.scene_ids:
            rid = _uuid.uuid4().hex[:16]
            await _execute_scene(
                "INSERT INTO ontol_char_scene_relation (id, scene_id) VALUES (?,?,?)",
                (rid, body.sid),
            )
        return await get_chat_scenes(body.chat_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bind chat scenes failed: {e}")


@router.get("/chat-scenes/{chat_id}")
async def get_chat_scenes(chat_id: str):
    """获取对话绑定的场景列表（带场景名称）。"""
    try:
        rows = await _query_scene(
            """SELECT r.id, r.r.scene_id, s.name, s.scene_desc
               FROM ontol_char_scene_relation r
               LEFT JOIN ontol_model_scene s ON r.scene_id = s.id
               WHERE r.chat_id=? AND r.delete_flag='0'
               ORDER BY r.create_time""",
            (chat_id,),
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
    name: str = Field(..., max_length=100, description="提示词名称")
    prompt_content: str = Field(default="", description="提示词文本内容")
    prompt_desc: Optional[str] = Field(None, max_length=500, description="提示词描述")
    prompt_description: Optional[str] = Field(None, max_length=500, description="提示词调用时机说明")
    create_id: Optional[str] = Field(None, max_length=32, description="创建人ID")

class ScenePromptUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
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
            "INSERT INTO ontol_scene_prompt (id, scene_id, name, prompt_content, prompt_desc, prompt_description, create_id) VALUES (?,?,?,?,?,?,?)",
            (prompt_id, scene_id, body.name, body.prompt_content or "", body.prompt_desc or "", body.prompt_description or "", body.create_id or ""),
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
    name: str = Field(..., max_length=200, description="词典名称")
    code: str = Field(..., max_length=100, description="词典编码（必填唯一）")
    dictionary_type_id: Optional[str] = Field(None, max_length=32, description="词条分类ID")
    dictionary_content: Optional[str] = Field(None, description="词典内容")

class SceneDictUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    code: Optional[str] = Field(None, max_length=100)
    dictionary_type_id: Optional[str] = Field(None, max_length=32)
    dictionary_content: Optional[str] = None
    delete_flag: Optional[str] = Field(None, max_length=2)


@router.get("/scenes/{scene_id}/dictionaries")
async def list_scene_dicts(scene_id: str):
    """列出场景下的所有词典，连带词条分类名。"""
    try:
        rows = await _query_scene(
            """SELECT d.*, dt.name
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
                """SELECT d.*, s.name, dt.name
                   FROM ontol_scene_dictionary d
                   LEFT JOIN ontol_model_scene s ON d.scene_id = s.id
                   LEFT JOIN ontol_dictionary_type dt ON d.dictionary_type_id = dt.id
                   WHERE d.delete_flag='0' AND d.dictionary_type_id=?
                   ORDER BY d.create_time DESC""",
                (dictionary_type_id,),
            )
        else:
            rows = await _query_scene(
                """SELECT d.*, s.name, dt.name
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
            "INSERT INTO ontol_scene_dictionary (id, scene_id, name, code, dictionary_type_id, dictionary_content) VALUES (?,?,?,?,?,?)",
            (dict_id, body.scene_id, body.name, body.code, body.dictionary_type_id or None, body.dictionary_content or ""),
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
            "INSERT INTO ontol_scene_dictionary (id, scene_id, name, code, dictionary_type_id, dictionary_content) VALUES (?,?,?,?,?,?)",
            (dict_id, scene_id, body.name, body.code, body.dictionary_type_id or None, body.dictionary_content or ""),
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
    name: str = Field(..., max_length=200, description="分类名称")
    dictionary_description: Optional[str] = Field(None, max_length=500)
    is_system: str = Field(default="0", max_length=1, description="是否系统预设")

class DictTypeUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
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
            "INSERT INTO ontol_dictionary_type (id, name, dictionary_description, is_system) VALUES (?,?,?,?)",
            (tid, body.name, body.dictionary_description or "", body.is_system),
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
    name: str = Field(..., max_length=200, description="类型名称")
    llm_description: Optional[str] = Field(None, max_length=500)
    is_system: str = Field(default="0", max_length=1, description="是否系统预设 0自定义/1系统")

class LLMTypeConfigUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
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
            "INSERT INTO ontol_llm_type_config (id, name, llm_description, is_system) VALUES (?,?,?,?)",
            (cid, body.name, body.llm_description or "", body.is_system),
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
    name: str = Field(..., max_length=200, description="显示名")
    llm_model: Optional[str] = Field(None, max_length=200, description="API模型名（如 deepseek-v4-pro）")
    llm_url: Optional[str] = Field(None, max_length=500, description="调用地址")
    llm_key: Optional[str] = Field(None, max_length=500, description="调用Key")
    llm_description: Optional[str] = Field(None, max_length=500, description="描述说明")

class LLMConfigUpdate(BaseModel):
    llm_type_config_id: Optional[str] = Field(None, max_length=32)
    name: Optional[str] = Field(None, max_length=200)
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
            "INSERT INTO ontol_llm_config (id, llm_type_config_id, name, llm_model, llm_url, llm_key, llm_description) VALUES (?,?,?,?,?,?,?)",
            (cfg_id, body.llm_type_config_id or None, body.name, body.llm_model or None, body.llm_url or "", body.llm_key or "", body.llm_description or ""),
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


# =========================================================================
# 动态函数类型 CRUD (ontol_function_type)
# =========================================================================

class FunctionTypeCreate(BaseModel):
    id: str = Field(default="", max_length=32)
    name: str = Field(..., max_length=200)
    function_description: Optional[str] = Field(None, max_length=500)
    is_system: Optional[str] = Field("0", max_length=2)

class FunctionTypeUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    function_description: Optional[str] = Field(None, max_length=500)
    is_system: Optional[str] = Field(None, max_length=2)
    delete_flag: Optional[str] = Field(None, max_length=2)


@router.get("/function-types")
async def list_function_types():
    try:
        rows = await _query_scene(
            "SELECT * FROM ontol_function_type WHERE delete_flag='0' ORDER BY create_time DESC"
        )
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")

@router.get("/function-types/{type_id}")
async def get_function_type(type_id: str):
    try:
        rows = await _query_scene("SELECT * FROM ontol_function_type WHERE id=? AND delete_flag='0'", (type_id,))
        if not rows: raise HTTPException(status_code=404, detail=f"Type {type_id} not found")
        return rows[0]
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=f"Query failed: {e}")

@router.post("/function-types", status_code=201)
async def create_function_type(body: FunctionTypeCreate):
    import uuid as _uuid
    try:
        tid = body.id.strip() if body.id else _uuid.uuid4().hex[:16]
        await _execute_scene(
            "INSERT INTO ontol_function_type (id, name, function_description, is_system) VALUES (?,?,?,?)",
            (tid, body.name, body.function_description or None, body.is_system or "0"),
        )
        rows = await _query_scene("SELECT * FROM ontol_function_type WHERE id=?", (tid,))
        return rows[0]
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=f"Create failed: {e}")

@router.put("/function-types/{type_id}")
async def update_function_type(type_id: str, body: FunctionTypeUpdate):
    try:
        existing = await _query_scene("SELECT id FROM ontol_function_type WHERE id=? AND delete_flag='0'", (type_id,))
        if not existing: raise HTTPException(status_code=404, detail=f"Type {type_id} not found")
        data = body.model_dump(exclude_none=True)
        if data:
            sets = ", ".join(f"{k}=?" for k in data)
            await _execute_scene(f"UPDATE ontol_function_type SET {sets} WHERE id=?", tuple(data.values()) + (type_id,))
        rows = await _query_scene("SELECT * FROM ontol_function_type WHERE id=?", (type_id,))
        return rows[0]
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=f"Update failed: {e}")

@router.delete("/function-types/{type_id}")
async def delete_function_type(type_id: str, soft: bool = True):
    try:
        if soft:
            await _execute_scene("UPDATE ontol_function_type SET delete_flag='1' WHERE id=?", (type_id,))
        else:
            await _execute_scene("DELETE FROM ontol_function_type WHERE id=?", (type_id,))
        return {"deleted": True, "type_id": type_id, "soft": soft}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")


# =========================================================================
# 动态函数 CRUD (ontol_function)
# =========================================================================

class FunctionCreate(BaseModel):
    id: str = Field(default="", max_length=32)
    function_type_id: Optional[str] = Field(None, max_length=32)
    code: str = Field(..., max_length=100, description="函数唯一标识")
    name: str = Field(..., max_length=100, description="函数名称简写")
    function_classpath: Optional[str] = Field(None, max_length=255)
    function_method: Optional[str] = Field(None, max_length=100)
    function_type: Optional[str] = Field("PYTHON", max_length=20)
    function_timeout_ms: Optional[int] = 30000
    function_max_retry: Optional[int] = 0
    status: Optional[int] = 1
    description: Optional[str] = None

class FunctionUpdate(BaseModel):
    function_type_id: Optional[str] = Field(None, max_length=32)
    code: Optional[str] = Field(None, max_length=100)
    name: Optional[str] = Field(None, max_length=100)
    function_classpath: Optional[str] = Field(None, max_length=255)
    function_method: Optional[str] = Field(None, max_length=100)
    function_type: Optional[str] = Field(None, max_length=20)
    function_timeout_ms: Optional[int] = None
    function_max_retry: Optional[int] = None
    status: Optional[int] = None
    description: Optional[str] = None
    delete_flag: Optional[str] = Field(None, max_length=2)


@router.get("/functions")
async def list_functions():
    try:
        rows = await _query_scene(
            "SELECT * FROM ontol_function WHERE delete_flag='0' ORDER BY create_time DESC"
        )
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")

@router.get("/functions/{func_id}")
async def get_function(func_id: str):
    try:
        rows = await _query_scene("SELECT * FROM ontol_function WHERE id=? AND delete_flag='0'", (func_id,))
        if not rows: raise HTTPException(status_code=404, detail=f"Function {func_id} not found")
        return rows[0]
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=f"Query failed: {e}")

@router.post("/functions", status_code=201)
async def create_function(body: FunctionCreate):
    import uuid as _uuid
    try:
        fid = body.id.strip() if body.id else _uuid.uuid4().hex[:16]
        await _execute_scene(
            "INSERT INTO ontol_function (id, function_type_id, code, name, function_classpath, function_method, function_type, function_timeout_ms, function_max_retry, status, description) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (fid, body.function_type_id or None, body.code, body.name, body.function_classpath or None, body.function_method or None, body.function_type or "PYTHON", body.function_timeout_ms or 30000, body.function_max_retry or 0, body.status or 1, body.description or None),
        )
        rows = await _query_scene("SELECT * FROM ontol_function WHERE id=?", (fid,))
        return rows[0]
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=f"Create failed: {e}")

@router.put("/functions/{func_id}")
async def update_function(func_id: str, body: FunctionUpdate):
    try:
        existing = await _query_scene("SELECT id FROM ontol_function WHERE id=? AND delete_flag='0'", (func_id,))
        if not existing: raise HTTPException(status_code=404, detail=f"Function {func_id} not found")
        data = body.model_dump(exclude_none=True)
        if data:
            sets = ", ".join(f"{k}=?" for k in data)
            await _execute_scene(f"UPDATE ontol_function SET {sets} WHERE id=?", tuple(data.values()) + (func_id,))
        rows = await _query_scene("SELECT * FROM ontol_function WHERE id=?", (func_id,))
        return rows[0]
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=f"Update failed: {e}")

@router.delete("/functions/{func_id}")
async def delete_function(func_id: str, soft: bool = True):
    try:
        if soft:
            await _execute_scene("UPDATE ontol_function SET delete_flag='1' WHERE id=?", (func_id,))
        else:
            await _execute_scene("DELETE FROM ontol_function WHERE id=?", (func_id,))
        return {"deleted": True, "func_id": func_id, "soft": soft}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")


# =========================================================================
# 推演版本管理 CRUD (ontol_cope_version)
# =========================================================================

class CopeVersionCreate(BaseModel):
    name: str = Field(default="", description="副本名称")
    cope_version_status: str = Field(default="00", description="状态: 00待处理/01推理中/02推理完成/03已删除")
    init_note_id: str = Field(default="", description="初始节点ID")
    init_note_name: str = Field(default="", description="初始节点名称")
    description: str = Field(default="", description="描述")
    confidence: float = Field(default=0.8, ge=0.01, le=1.0, description="置信度 (0.01~1.00)")

class CopeVersionUpdate(BaseModel):
    name: Optional[str] = Field(None, description="副本名称")
    cope_version_status: Optional[str] = Field(None, description="状态")
    init_note_id: Optional[str] = Field(None, description="初始节点ID")
    init_note_name: Optional[str] = Field(None, description="初始节点名称")
    description: Optional[str] = Field(None, description="描述")
    confidence: Optional[float] = Field(None, ge=0.01, le=1.0, description="置信度 (0.01~1.00)")


@router.get("/cope-versions")
async def list_cope_versions():
    """查询 ontol_cope_version 所有有效记录。"""
    try:
        rows = await _query_scene(
            "SELECT * FROM ontol_cope_version WHERE delete_flag='0' ORDER BY create_time DESC"
        )
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query cope versions failed: {e}")


@router.post("/cope-versions")
async def create_cope_version(body: CopeVersionCreate):
    """新增副本版本记录。"""
    import uuid as _uuid
    from datetime import datetime as _dt
    rid = _uuid.uuid4().hex[:16]
    now = _dt.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    try:
        await _execute_scene(
            "INSERT INTO ontol_cope_version "
            "(id, name, code, cope_version_status, description, init_note_id, init_note_name, confidence, create_time) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (rid, body.name, rid, body.cope_version_status,
             body.description, body.init_note_id, body.init_note_name, body.confidence, now),
        )
        rows = await _query_scene("SELECT * FROM ontol_cope_version WHERE id=?", (rid,))
        return rows[0] if rows else {"id": rid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Create cope version failed: {e}")


@router.put("/cope-versions/{cope_id}")
async def update_cope_version(cope_id: str, body: CopeVersionUpdate):
    """更新副本版本记录。"""
    from datetime import datetime as _dt
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates["update_time"] = _dt.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    try:
        sets = ", ".join(f"{k}=?" for k in updates)
        params = tuple(updates.values()) + (cope_id,)
        await _execute_scene(
            f"UPDATE ontol_cope_version SET {sets} WHERE id=?",
            params,
        )
        rows = await _query_scene("SELECT * FROM ontol_cope_version WHERE id=?", (cope_id,))
        return rows[0] if rows else {"id": cope_id, "updated": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update cope version failed: {e}")


@router.delete("/cope-versions/{cope_id}")
async def delete_cope_version(cope_id: str):
    """软删除副本版本记录。"""
    from datetime import datetime as _dt
    try:
        now = _dt.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        await _execute_scene(
            "UPDATE ontol_cope_version SET delete_flag='1', update_time=? WHERE id=?",
            (now, cope_id),
        )
        return {"deleted": True, "cope_id": cope_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete cope version failed: {e}")


@router.delete("/cope-versions/{cope_id}/nodes")
async def delete_cope_version_nodes(cope_id: str):
    """批量删除图数据库中 copy_version 匹配该记录 ID 的节点。"""
    from infrastructure.db.neo4j import get_driver

    try:
        driver = await get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (n) WHERE n.copy_version = $cope_id DETACH DELETE n RETURN count(n) AS deleted",
                cope_id=cope_id,
            )
            record = await result.single()
            count = record["deleted"] if record else 0
        return {"deleted": True, "cope_id": cope_id, "node_count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete cope version nodes failed: {e}")


@router.get("/cope-versions/{cope_id}")
async def get_cope_version(cope_id: str):
    """查询单条副本版本记录。"""
    try:
        rows = await _query_scene(
            "SELECT * FROM ontol_cope_version WHERE id=? AND delete_flag='0'",
            (cope_id,),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Cope version not found")
        return rows[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query cope version failed: {e}")


@router.get("/cope-versions/{cope_id}/graph")
async def get_cope_graph(cope_id: str):
    """
    获取推演副本的图数据（节点+关系）。
    - status=00: 返回没有 copy_version 属性的节点
    - 其他状态: 返回 copy_version=cope_id 的节点
    """
    from infrastructure.db.neo4j import get_driver

    try:
        # 查副本状态
        rows = await _query_scene(
            "SELECT * FROM ontol_cope_version WHERE id=? AND delete_flag='0'",
            (cope_id,),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Cope version not found")
        cope = rows[0]
        status = cope.get("cope_version_status", "00")

        driver = await get_driver()
        async with driver.session() as session:
            if status == "00":
                cypher = """
                    MATCH (n)
                    WHERE n.copy_version IS NULL OR n.copy_version = ''
                    OPTIONAL MATCH (n)-[r]-(m)
                    WHERE m.copy_version IS NULL OR m.copy_version = ''
                    RETURN n, collect(DISTINCT {edge: r, node: m}) AS rels
                    LIMIT 500
                """
            else:
                cypher = """
                    MATCH (n)
                    WHERE n.copy_version = $cope_id
                    OPTIONAL MATCH (n)-[r]-(m)
                    WHERE m.copy_version = $cope_id
                    RETURN n, collect(DISTINCT {edge: r, node: m}) AS rels
                    LIMIT 500
                """
            result = await session.run(cypher, cope_id=cope_id)
            records = [record async for record in result]

        nodes = {}
        edges = {}
        for record in records:
            n = record["n"]
            nid = n.element_id
            if nid not in nodes:
                nodes[nid] = {
                    "id": n.element_id,
                    "labels": list(n.labels),
                    "properties": dict(n.items()),
                }
            rels_list = record.get("rels")
            if rels_list:
                for rel_item in rels_list:
                    r = rel_item.get("edge")
                    m = rel_item.get("node")
                    if r is None or m is None:
                        continue
                    mid = m.element_id
                    if mid not in nodes:
                        nodes[mid] = {
                            "id": m.element_id,
                            "labels": list(m.labels),
                            "properties": dict(m.items()),
                        }
                    ekey = str(r.element_id)
                    if ekey not in edges:
                        edges[ekey] = {
                            "edge_id": r.element_id,
                            "source_id": r.start_node.element_id,
                            "target_id": r.end_node.element_id,
                            "type": r.type,
                            "properties": dict(r.items()),
                        }

        return {
            "cope_id": cope_id,
            "cope_version_status": status,
            "cope_name": cope.get("name", ""),
            "init_note_id": cope.get("init_note_id", ""),
            "init_note_name": cope.get("init_note_name", ""),
            "confidence": float(cope.get("confidence", 0.8)),
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cope graph query failed: {e}")


# =========================================================================
# 对话-推演副本绑定 CRUD (ontol_chat_cope_version_relation)
# =========================================================================

class ChatCopeVersionBind(BaseModel):
    chat_id: str = Field(..., description="对话UUID")
    cope_version_id: str = Field(..., description="副本ID")


@router.post("/chat-cope-versions/bind")
async def bind_chat_cope_version(body: ChatCopeVersionBind):
    """将对话绑定到推演副本（先删旧绑定，再插入新绑定）。"""
    import uuid as _uuid
    rid = _uuid.uuid4().hex[:16]
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    try:
        # 先清理旧绑定
        await _execute_scene(
            "UPDATE ontol_chat_cope_version_relation SET delete_flag='1' WHERE chat_id=?",
            (body.chat_id,),
        )
        # 插入新绑定
        await _execute_scene(
            "INSERT INTO ontol_chat_cope_version_relation (id, name, code, chat_id, cope_version_id, create_time) "
            "VALUES (?,?,?,?,?,?)",
            (rid, '', rid, body.chat_id, body.cope_version_id, now),
        )
        return {"id": rid, "chat_id": body.chat_id, "cope_version_id": body.cope_version_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bind chat cope version failed: {e}")


@router.get("/chat-cope-versions/{chat_id}")
async def get_chat_cope_version(chat_id: str):
    """查询对话绑定的推演副本。"""
    try:
        rows = await _query_scene(
            "SELECT r.*, c.name AS cope_name, c.init_note_name, c.cope_version_status "
            "FROM ontol_chat_cope_version_relation r "
            "LEFT JOIN ontol_cope_version c ON r.cope_version_id = c.id "
            "WHERE r.chat_id=? AND r.delete_flag='0'",
            (chat_id,),
        )
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query chat cope version failed: {e}")


@router.delete("/chat-cope-versions/{relation_id}")
async def unbind_chat_cope_version(relation_id: str):
    """删除对话-副本绑定（软删除）。"""
    try:
        await _execute_scene(
            "UPDATE ontol_chat_cope_version_relation SET delete_flag='1' WHERE id=?",
            (relation_id,),
        )
        return {"deleted": True, "relation_id": relation_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unbind chat cope version failed: {e}")


# =========================================================================
# 审核记录 API — 薄路由，业务逻辑在 business/audit/audit_service.py
# 其他模块可直接 import 业务层函数，无需经过 HTTP
# =========================================================================


@router.get("/audit-logs")
async def list_audit_logs(
    audit_status: Optional[str] = None,
    trigger_source: Optional[str] = None,
    node_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
):
    """分页查询审核记录。"""
    from business.audit import list_audit_logs as _svc_list
    return _svc_list(
        audit_status=audit_status, trigger_source=trigger_source,
        node_id=node_id, batch_id=batch_id, keyword=keyword,
        limit=limit, offset=offset,
    )


@router.get("/audit-logs/{log_id}")
async def get_audit_log(log_id: str):
    """获取单条审核记录。"""
    from business.audit import get_audit_log as _svc_get
    result = _svc_get(log_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Audit log not found")
    return result


@router.post("/audit-logs")
async def create_audit_log(body: dict):
    """创建审核记录（通用 dict 入口，兼容外部调用）。"""
    from business.audit import create_audit_log as _svc_create, AuditLogCreate
    model = AuditLogCreate(**body)
    log_id = _svc_create(model)
    return {"id": log_id, "created": True}


@router.put("/audit-logs/{log_id}")
async def update_audit_log(log_id: str, body: dict):
    """更新审核记录（复核字段+状态）。"""
    from business.audit import update_audit_log as _svc_update, AuditLogUpdate
    model = AuditLogUpdate(**body)
    ok = _svc_update(log_id, model)
    if not ok:
        raise HTTPException(status_code=404, detail="Audit log not found")
    return {"updated": True, "id": log_id}


@router.delete("/audit-logs/{log_id}")
async def delete_audit_log(log_id: str):
    """软删除审核记录。"""
    from business.audit import delete_audit_log as _svc_delete
    _svc_delete(log_id)
    return {"deleted": True, "id": log_id}
