"""
对话 API 路由
-----------
基于 LangGraph ReAct Agent 的多步推理管道：
意图解析 → 知识检索 → 推理校验 → 图遍历 → 步骤生成 → 自校验 → 方案输出
"""
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    messages: list[dict] = Field(..., description='对话历史 [{"role":"user","content":"..."}, ...]')
    model: str = Field("deepseek-v4-pro", description="模型名称")
    temperature: float = Field(0, description="生成温度")
    max_tokens: int = Field(4096, description="最大输出 token 数")


router = APIRouter(tags=["Chat"])


@router.post("/chat")
async def chat(request: ChatRequest):
    """流式对话接口 —— 多步推理管道 (SSE)。"""

    # 预检模型可用性
    try:
        from capabilities.models.factory import ModelFactory
        factory = ModelFactory()
        llm_iface = factory.create_llm(request.model)
        await llm_iface.get_llm()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"模型加载失败: {e}")

    async def event_generator():
        try:
            from capabilities.agents.chat_agent import run_chat_agent

            async for event in run_chat_agent(request.messages, request.model):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
