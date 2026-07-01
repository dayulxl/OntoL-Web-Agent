"""
共享 Pydantic 数据模型
---------------------
定义 API 请求/响应的标准 Schema，供 Gateway、Orchestrator 等层共享使用。
"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# 请求 Schema
# ------------------------------------------------------------------

class RunRequest(BaseModel):
    """
    工作流执行请求。

    Example:
        {
            "workflow_name": "customer_service",
            "input": {"query": "我想退货"},
            "config": {"thread_id": "session-123", "user_id": "user-456"}
        }
    """
    workflow_name: str = Field(..., description="工作流名称")
    input: dict = Field(..., description="工作流输入数据")
    config: Optional[dict] = Field(None, description="运行时配置（thread_id, user_id 等）")


class BatchRunRequest(BaseModel):
    """批量执行请求。"""
    requests: list[RunRequest] = Field(..., description="批量请求列表")
    parallel: bool = Field(True, description="是否并行执行")


# ------------------------------------------------------------------
# 响应 Schema
# ------------------------------------------------------------------

class RunResponse(BaseModel):
    """工作流执行响应。"""
    run_id: str = Field(..., description="运行 ID")
    status: str = Field(..., description="运行状态: running / completed / failed / cancelled")
    output: Optional[dict] = Field(None, description="运行输出")


class RunStatusResponse(BaseModel):
    """运行状态查询响应。"""
    run_id: str
    workflow: str
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    current_step: Optional[str] = None
    error: Optional[str] = None


class StreamEvent(BaseModel):
    """流式事件。"""
    event: str = Field(..., description="事件类型: on_chat_model_stream / on_tool_start / on_tool_end / on_chain_end")
    name: str = Field("", description="事件来源名称（节点/Chain/Tool 名称）")
    data: Any = Field(None, description="事件数据")
    run_id: str = Field("", description="所属运行 ID")


# ------------------------------------------------------------------
# 通用错误响应
# ------------------------------------------------------------------

class ErrorResponse(BaseModel):
    """标准错误响应。"""
    error: str = Field(..., description="错误类型")
    detail: str = Field(..., description="错误详情")
    trace_id: Optional[str] = Field(None, description="追踪 ID（用于排查）")


# ------------------------------------------------------------------
# 健康检查
# ------------------------------------------------------------------

class HealthResponse(BaseModel):
    """健康检查响应。"""
    status: str
    timestamp: str


class ReadinessResponse(BaseModel):
    """就绪检查响应。"""
    ready: bool
    db: bool
    cache: bool
