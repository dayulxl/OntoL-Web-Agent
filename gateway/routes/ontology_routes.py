"""
本体建模 API 路由
----------------
提供 Neo4j 知识图谱的节点/关系 CRUD、Schema 发现和图遍历接口。
"""
from typing import Optional
from pathlib import Path as _Path

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
    id: str = Field(..., max_length=32, description="模型ID（主键）")
    ontol_parent_id: Optional[str] = Field(None, max_length=32, description="父级模型ID")
    ontol_name: str = Field(..., max_length=50, description="本体名称")
    ontol_model_type: str = Field(..., max_length=2, description="本体类型：M1/M2/M3/M4/M5/M6/M7/ME/MT")
    ontol_model_status: str = Field("0", max_length=2, description="本体状态：0=启用中 1=已停用")
    ontol_model_desc: Optional[str] = Field(None, max_length=255, description="本体描述")

class OntolModelUpdateBody(BaseModel):
    ontol_parent_id: Optional[str] = Field(None, max_length=32)
    ontol_name: Optional[str] = Field(None, max_length=50)
    ontol_model_type: Optional[str] = Field(None, max_length=2)
    ontol_model_status: Optional[str] = Field(None, max_length=2)
    ontol_model_desc: Optional[str] = Field(None, max_length=255)

class OntolModelAttrCreateBody(BaseModel):
    id: str = Field(..., max_length=32, description="属性ID（主键）")
    ontol_model_id: Optional[str] = Field(None, max_length=32)
    attr_name: str = Field(..., max_length=50)
    attr_code: str = Field(..., max_length=50)
    attr_data_type: str = Field("0", max_length=2)
    attr_length: Optional[str] = Field(None, max_length=10)
    attr_digit: Optional[str] = Field(None, max_length=10)
    attr_is_only: Optional[str] = Field(None, max_length=2)
    attr_cascade_colum: Optional[str] = Field(None, max_length=50)
    attr_data_source_flag: Optional[str] = Field(None, max_length=2)
    attr_data_source: Optional[str] = Field(None, max_length=255)
    attr_required: Optional[str] = Field(None, max_length=2)
    attr_default_value: Optional[str] = Field(None, max_length=500)
    attr_relation_flag: Optional[str] = Field(None, max_length=2)
    attr_desc: Optional[str] = Field(None, max_length=50)

class OntolModelAttrUpdateBody(BaseModel):
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
    attr_relation_flag: Optional[str] = Field(None, max_length=2)
    attr_desc: Optional[str] = Field(None, max_length=50)


# =========================================================================
# 依赖注入
# =========================================================================

async def get_graph():
    """
    获取 GraphMemory 实例（惰性导入，避免启动时 Neo4j 未就绪而崩溃）。
    """
    from infrastructure.db.neo4j import get_driver
    from capabilities.memory.graph_memory import GraphMemory

    try:
        driver = await get_driver()
    except InfrastructureError:
        raise HTTPException(status_code=503, detail="Neo4j driver not initialized")
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
# Schema
# =========================================================================

@router.get("/ontology/schema")
async def ontology_schema(graph=Depends(get_graph)):
    """获取图 Schema：所有标签、关系类型、节点和边计数。"""
    try:
        return await graph.get_schema()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Neo4j query failed: {e}")


# =========================================================================
# Neighborhood — 图邻域查询
# =========================================================================

@router.get("/ontology/neighborhood/{node_id}")
async def get_neighborhood(node_id: int, depth: int = 1, graph=Depends(get_graph)):
    """获取节点的图邻域（关联节点 + 关系），支持 depth 1-3。"""
    try:
        return await graph.get_neighborhood(node_id, depth=depth)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Neo4j query failed: {e}")


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
        raise HTTPException(status_code=503, detail=f"Neo4j query failed: {e}")


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
        raise HTTPException(status_code=503, detail=f"Neo4j query failed: {e}")


@router.post("/ontology/nodes", status_code=201)
async def create_node(body: NodeCreate, graph=Depends(get_graph)):
    """创建节点。"""
    try:
        return await graph.create_node(body.label, body.properties)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Neo4j create failed: {e}")


@router.put("/ontology/nodes/{node_id}")
async def update_node(node_id: int, body: NodeUpdate, graph=Depends(get_graph)):
    """更新节点属性。"""
    try:
        node = await graph.update_node(node_id, body.properties)
        if node is None:
            raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
        return node
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Neo4j update failed: {e}")


@router.delete("/ontology/nodes/{node_id}")
async def delete_node(node_id: int, graph=Depends(get_graph)):
    """删除节点及其所有关系。"""
    try:
        ok = await graph.delete_node(node_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
        return {"deleted": True, "node_id": node_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Neo4j delete failed: {e}")


# =========================================================================
# Edge CRUD
# =========================================================================

@router.post("/ontology/edges", status_code=201)
async def create_edge(body: EdgeCreate, graph=Depends(get_graph)):
    """创建关系。"""
    try:
        return await graph.create_edge(body.source_id, body.target_id, body.rel_type, body.properties)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Neo4j create edge failed: {e}")


@router.delete("/ontology/edges/{edge_id}")
async def delete_edge(edge_id: int, graph=Depends(get_graph)):
    """删除关系。"""
    try:
        ok = await graph.delete_edge(edge_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Edge {edge_id} not found")
        return {"deleted": True, "edge_id": edge_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Neo4j delete edge failed: {e}")


@router.get("/ontology/search")
async def search_nodes(keyword: str, limit: int = 20, graph=Depends(get_graph)):
    """按关键词搜索节点。"""
    try:
        return await graph.search_nodes(keyword, limit=min(limit, 100))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Neo4j search failed: {e}")


# =========================================================================
# Ontology Model CRUD (SQLite)
# =========================================================================

@router.get("/ontology-models")
async def list_ontology_models(
    keyword: Optional[str] = None,
    limit: int = 50,
    repo=Depends(get_ontology_repo),
):
    """获取本体模型树。"""
    try:
        if keyword:
            return await repo.search_models(keyword, limit=min(limit, 200))
        return await repo.get_full_tree_with_attrs()
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
    """获取单个本体模型及其属性。"""
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
    """创建本体模型。"""
    try:
        return await repo.model.create(body.model_dump())
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
async def list_model_attrs(model_id: str, relation_flag: Optional[str] = None, repo=Depends(get_ontology_repo)):
    """获取模型属性列表。"""
    try:
        return await repo.get_attrs_by_model(model_id, relation_flag=relation_flag)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database query failed: {e}")


@router.post("/ontology-models/{model_id}/attrs", status_code=201)
async def create_model_attr(model_id: str, body: OntolModelAttrCreateBody, repo=Depends(get_ontology_repo)):
    """创建模型属性。"""
    data = body.model_dump()
    data["ontol_model_id"] = model_id
    try:
        return await repo.attr.create(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Create attr failed: {e}")


@router.put("/ontology-models/{model_id}/attrs/{attr_id}")
async def update_model_attr(model_id: str, attr_id: str, body: OntolModelAttrUpdateBody, repo=Depends(get_ontology_repo)):
    """更新模型属性。"""
    try:
        result = await repo.attr.update(attr_id, body.model_dump(exclude_none=True))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update attr failed: {e}")


@router.delete("/ontology-models/{model_id}/attrs/{attr_id}")
async def delete_model_attr(model_id: str, attr_id: str, repo=Depends(get_ontology_repo)):
    """删除模型属性。"""
    try:
        await repo.attr.delete(attr_id)
        return {"deleted": True, "attr_id": attr_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete attr failed: {e}")


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
# 本体类型感知的实体解析 & Neo4j 导入
# =========================================================================

# ── 本体类型定义（从 SQLite 动态加载）──

_ONTOLOGY_TYPES_CACHE: Optional[dict] = None

def _load_ontology_types() -> dict:
    """从 SQLite 数据库加载所有本体类型及其字段定义。"""
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
                """SELECT attr_name, attr_code, attr_data_type, attr_length,
                          attr_required, attr_default_value, attr_desc
                   FROM ontol_model_attr
                   WHERE ontol_model_id=? AND delete_flag='0'
                   ORDER BY attr_code""",
                (md["id"],),
            ).fetchall()
            types[md["id"]] = {
                "id": md["id"],
                "name": md["ontol_name"],
                "type_code": md["ontol_model_type"],
                "desc": md["ontol_model_desc"] or "",
                "fields": [
                    {
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


def _build_ontology_prompt() -> str:
    """构建包含所有本体类型定义的 LLM 提示词。"""
    types = _load_ontology_types()
    lines = []
    lines.append("## 本体类型定义\n")
    lines.append("你需要将以下文本中的每个实体归类到以下本体类型之一，并填写对应的字段：\n")

    for tid, tdef in types.items():
        if tid in ("M_ROOT",):  # 跳过根节点，用具体类型替代
            continue
        lines.append(f"### {tdef['name']} (代码: {tdef['type_code']}, ID: {tid})")
        lines.append(f"描述: {tdef['desc']}")
        if tdef["fields"]:
            lines.append("字段:")
            for f in tdef["fields"]:
                req = "必填" if f["required"] == "1" else "可选"
                default = f"，默认值={f['default']}" if f["default"] else ""
                lines.append(f"  - {f['code']} ({f['name']}): {req}, 类型={f['data_type']}, 长度={f['length']}{default} — {f['desc']}")
        else:
            lines.append("字段: 无预定义字段，按文本内容自由填充 key-value")
        lines.append("")

    lines.append("""## 输出格式（严格 JSON）

请只输出以下 JSON 格式，不要输出任何其他内容：

```json
{
  "entities": [
    {
      "name": "实体名称",
      "ont_type": "M_ENTITY",
      "type_name": "实体",
      "properties": {
        "id": "唯一标识",
        "name": "名称",
        "code": "编码",
        "desc": "描述"
      }
    }
  ],
  "relationships": [
    {"subject": "实体A名称", "predicate": "关系类型", "object": "实体B名称"}
  ]
}
```

## 分类规则

- M_ENTITY (实体): 物理或逻辑对象，如飞机、舰船、导弹、设备
- M_BEHAVIOR (行为): 动作或操作，如发射、巡逻、攻击
- M_RULE (规则): 约束或推理规则，如交战规则、触发条件
- M_SCENE (场景): 时空上下文，如战斗区域、任务区域
- M_AGENT (主体): 自主决策智能体，如指挥官、AI系统
- M_EXCEPTION (异常补偿): 异常处理机制，如故障恢复、降级方案
- M_QUALITY (质量约束): 数据质量校验，如精度要求、时效性要求
- M_EVENT (事件): 状态变化事件，如检测到目标、任务开始/结束
- M_TEMPLATE (模板): 可复用模板定义

## 重要规则

1. 每个实体必须归类到一个 ont_type
2. 属性字段尽量填满（能从文本推断的值都填上）
3. 关系用竖线分隔: 主体 | 关系 | 客体
4. 只输出 JSON，不要输出任何解释""")
    return "\n".join(lines)


class ParseTriplesRequest(BaseModel):
    filename: str = Field(..., description="要解析的文件名")
    model: str = Field("deepseek-v4-pro", description="使用的 LLM 模型名")


class ImportEntitiesRequest(BaseModel):
    filename: str = Field(..., description="来源文件名")
    entities: list[dict] = Field(..., description="本体实体列表")
    relationships: list[dict] = Field(default_factory=list, description="关系列表")


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

    返回按本体类型分类的实体列表和关系列表，供用户审核后导入 Neo4j。
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
                s = (rel.get("subject") or "").strip()
                p = (rel.get("predicate") or "").strip()
                o = (rel.get("object") or "").strip()
                if not s or not o or not p:
                    continue
                key = f"{s}|{p}|{o}"
                if key not in seen_rels:
                    seen_rels.add(key)
                    all_relationships.append({"subject": s, "predicate": p, "object": o})

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
    将本体分类后的实体和关系导入 Neo4j 知识图谱。
    每个实体按 ont_type 打标签，属性完整写入。
    """
    from infrastructure.db.neo4j import get_driver

    try:
        driver = await get_driver()
    except InfrastructureError:
        raise HTTPException(status_code=503, detail="Neo4j driver not initialized")

    nodes_created = 0
    edges_created = 0

    async with driver.session() as session:
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
            subj = (rel.get("subject") or "").strip()
            pred = (rel.get("predicate") or "").strip()
            obj = (rel.get("object") or "").strip()
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
        nodes_created = (await node_result.single())["cnt"]

    return {
        "filename": body.filename,
        "nodes_created": nodes_created,
        "edges_created": edges_created,
        "entity_count": len(body.entities),
    }


# 保留旧的 import-triples 兼容接口
class ImportTriplesRequest(BaseModel):
    filename: str = Field(..., description="来源文件名")
    triples: list[dict] = Field(..., description="三元组列表")


@router.post("/upload/import-triples")
async def import_triples_to_neo4j(body: ImportTriplesRequest):
    """兼容旧接口: 将三元组导入 Neo4j。新代码请使用 /upload/import-entities。"""
    return await import_entities_to_neo4j(
        ImportEntitiesRequest(
            filename=body.filename,
            entities=[
                {"name": t["subject"], "ont_type": "M_ENTITY", "properties": {"name": t["subject"]}}
                for t in body.triples
            ]
            + [
                {"name": t["object"], "ont_type": "M_ENTITY", "properties": {"name": t["object"]}}
                for t in body.triples
            ],
            relationships=body.triples,
        )
    )
