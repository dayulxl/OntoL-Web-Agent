"""
推理机 SSE 流式接口
-------------------
POST /api/v1/reasoning/run     → 启动推理（SSE 流式推送 4 步日志）
GET  /api/v1/reasoning/nodes   → 搜索起点节点
GET  /api/v1/reasoning/rules   → 获取可用推理规则列表
"""

import json as _json
from typing import AsyncIterator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/reasoning", tags=["Reasoning"])

# 引擎/注册表单例 — 懒初始化，避免启动时触发 business.__init__ → psycopg 链
_registry = None
_engine = None


def _get_registry():
    global _registry
    if _registry is None:
        from business.reasoning.rules import RuleRegistry
        _registry = RuleRegistry.with_defaults()
    return _registry


def _get_engine(confidence: float = 0.5):
    from business.reasoning.engine import ReasoningEngine
    return ReasoningEngine(registry=_get_registry(), confidence_threshold=confidence)


# ============================================================
# 请求模型
# ============================================================

class RunReasoningRequest(BaseModel):
    seed_node_id: int = Field(..., description="起点节点原生 ID")
    cope_version: str = Field(default="", description="副本版本号（空则自动生成）")
    confidence_threshold: float = Field(default=0.5, ge=0.01, le=1.0, description="置信度阈值")
    rules: list[str] = Field(default_factory=list, description="启用的规则名称列表（空=全部启用）")
    max_depth: int = Field(default=10, ge=1, le=50, description="最大推理深度")


# ============================================================
# SSE 流式推理
# ============================================================

async def _reasoning_sse_generator(request: RunReasoningRequest) -> AsyncIterator[str]:
    """SSE 流式生成推理事件。"""
    engine = _get_engine(request.confidence_threshold)
    try:
        async for event in engine.run(
            seed_node_id=request.seed_node_id,
            cope_version=request.cope_version,
            rules=request.rules or None,
        ):
            data = _json.dumps(
                {"step": event.step, "event": event.event,
                 "message": event.message, "data": event.data},
                ensure_ascii=False, default=str,
            )
            yield f"data: {data}\n\n"
    except Exception as e:
        yield f"data: {_json.dumps({'step': 0, 'event': 'error', 'message': str(e), 'data': {}})}\n\n"


@router.post("/run")
async def reasoning_run(body: RunReasoningRequest):
    """
    启动图推理机，SSE 流式推送推理日志。

    流式格式:
      data: {"step": 1, "event": "step_start", "message": "Step 1: ...", "data": {}}
      data: {"step": 1, "event": "log", "message": "克隆祖先: ...", "data": {}}
      ...
      data: {"step": 4, "event": "done", "message": "推理完成", "data": {...}}
    """
    return StreamingResponse(
        _reasoning_sse_generator(body),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


# ============================================================
# 节点搜索
# ============================================================

@router.get("/nodes")
async def reasoning_search_nodes(
    keyword: str = Query(default="", description="搜索关键词（code/name/ont_type）"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """
    搜索可用的推理起点节点。
    返回: [{id, labels, props}]
    """
    from business.reasoning.graph_ops import search_nodes
    nodes = await search_nodes(keyword, limit)
    return {"count": len(nodes), "nodes": nodes}


# ============================================================
# 规则列表
# ============================================================

@router.get("/rules")
async def reasoning_list_rules():
    """
    获取所有可用的推理规则。
    返回: [{name, description, enabled}]
    """
    reg = _get_registry()
    return {
        "rules": [
            {
                "name": r.name,
                "description": r.description,
                "enabled": r.enabled,
                "precondition_key": r.precondition_key,
                "effect_key": r.effect_key,
                "confidence_threshold": r.confidence_threshold,
            }
            for r in reg.rules.values()
        ]
    }
