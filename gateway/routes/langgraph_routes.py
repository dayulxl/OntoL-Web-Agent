"""
LangGraph API 路由
-----------------
对外暴露 /run、/stream、/status 等端点，对接编排层执行引擎。

注意: GraphExecutor 导入放在函数内部（惰性加载），避免应用启动时
      触发 orchestrator → langgraph.checkpoint.postgres → psycopg → libpq
      的依赖链。没有 Postgres 时不影响 Chat 页面等不需要编排层的功能。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from common.models.schemas import (
    RunRequest,
    RunResponse,
    RunStatusResponse,
    StreamEvent,
)
from common.exceptions.base import AppException

router = APIRouter(tags=["LangGraph"])


def get_executor():
    """依赖注入：惰性加载 GraphExecutor（仅在调用 /run /stream 时触发）。"""
    from orchestrator.engine.executor import GraphExecutor
    from common.config.settings import get_settings
    settings = get_settings()
    return GraphExecutor(postgres_uri=settings.postgres_uri)


@router.post("/run", response_model=RunResponse)
async def run_workflow(request: RunRequest, executor=Depends(get_executor)):
    """
    同步执行工作流，返回最终状态。

    - **workflow_name**: 工作流名称（如 customer_service、risk_control）
    - **input**: 工作流输入数据
    - **config**: 运行时配置（可选，含 thread_id、user_id 等）
    """
    try:
        result = await executor.run(
            workflow_name=request.workflow_name,
            input_data=request.input,
            config=request.config,
        )
        return RunResponse(
            run_id=result["run_id"],
            status=result["status"],
            output=result["output"],
        )
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def stream_workflow(request: RunRequest, executor=Depends(get_executor)):
    """
    流式执行工作流，返回 SSE（Server-Sent Events）流。

    每个事件包含当前节点的输出，适用于需要实时反馈的场景。
    """
    async def event_generator():
        try:
            async for event in executor.stream(
                workflow_name=request.workflow_name,
                input_data=request.input,
                config=request.config,
            ):
                yield f"data: {event.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@router.get("/runs/{run_id}/status", response_model=RunStatusResponse)
async def get_run_status(run_id: str, executor=Depends(get_executor)):
    """
    查询运行状态。

    支持查看异步任务的执行进度和中间状态。
    """
    status = await executor.get_status(run_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return RunStatusResponse(**status)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, executor=Depends(get_executor)):
    """取消正在运行的任务。"""
    cancelled = await executor.cancel(run_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found or already completed")
    return {"run_id": run_id, "status": "cancelled"}


@router.get("/health")
async def health_check():
    """存活检查端点。"""
    from datetime import datetime, timezone
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/ready")
async def readiness_check():
    """就绪检查端点：验证 Postgres 和 Redis 连通性。"""
    from infrastructure.db.postgres import check_postgres
    from infrastructure.cache.redis import check_redis

    db_ok = await check_postgres()
    cache_ok = await check_redis()
    ready = db_ok and cache_ok
    return {"ready": ready, "db": db_ok, "cache": cache_ok}
