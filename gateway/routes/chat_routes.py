"""
对话 API 路由
-----------
基于 LangGraph ReAct Agent 的多步推理管道：
意图解析 → 知识检索 → 推理校验 → 图遍历 → 步骤生成 → 自校验 → 方案输出
模型来源优先级：DB 配置 (ontol_llm_config) → models.yaml → 报错
"""
import json
import sqlite3
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional


class ChatRequest(BaseModel):
    messages: list[dict] = Field(..., description='对话历史 [{"role":"user","content":"..."}, ...]')
    model: str = Field("", description="模型 config_id (ontol_llm_config.id)")
    temperature: float = Field(0, description="生成温度")
    max_tokens: int = Field(4096, description="最大输出 token 数")
    scene_ids: list[str] = Field(default_factory=list, description="对话绑定的场景 ID 列表")


router = APIRouter(tags=["Chat"])


from capabilities.models.resolver import resolve_llm


def _load_scene_prompts(scene_ids: list[str]) -> list[dict]:
    """加载场景下的所有提示词，返回 [{name, prompt_description, prompt_content}]。"""
    if not scene_ids:
        return []

    db_path = Path("infrastructure/db/ontol.db")
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(scene_ids))
    rows = conn.execute(
        f"SELECT name, prompt_description, prompt_content "
        f"FROM ontol_scene_prompt "
        f"WHERE scene_id IN ({placeholders}) AND delete_flag='0' "
        f"ORDER BY create_time",
        scene_ids,
    ).fetchall()
    conn.close()

    return [dict(r) for r in rows]


@router.get("/pipeline-steps")
async def pipeline_steps():
    """
    获取管道步骤定义（SSOT）。

    前端在初始化时调用此端点获取步骤列表，避免硬编码。
    返回: {"steps": [{"key": "intent_parse", "label": "意图解析"}, ...]}
    """
    from capabilities.prompts.pipeline_steps import step_label_kv, TOOL_TO_STEP
    return {
        "steps": step_label_kv(),
        "tool_step_map": {k: v for k, v in TOOL_TO_STEP.items()},
    }


@router.post("/chat")
async def chat(request: ChatRequest):
    """流式对话接口 —— 多步推理管道 (SSE)。

    提示词路由规则：
    - 未绑定场景 → 使用默认 SYSTEM_PROMPT
    - 绑定了场景 → 加载场景下所有提示词，由 Agent 动态匹配 prompt_description
    """

    # 解析并预检模型
    if not request.model:
        raise HTTPException(status_code=400, detail="未指定模型，请在下拉框中选择一个模型")
    try:
        llm_iface = resolve_llm(request.model)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    try:
        await llm_iface.get_llm()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"模型加载失败: {e}")

    # 加载场景提示词
    scene_prompts = _load_scene_prompts(request.scene_ids)

    async def event_generator():
        try:
            from capabilities.agents.chat_agent import run_chat_agent

            async for event in run_chat_agent(
                request.messages,
                request.model,
                scene_prompts=scene_prompts,
            ):
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
