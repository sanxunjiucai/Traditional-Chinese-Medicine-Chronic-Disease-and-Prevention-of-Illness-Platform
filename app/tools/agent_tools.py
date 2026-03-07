"""
Agent API:
  POST /tools/agent/execute  — 一次性执行，返回完整结果 JSON
  POST /tools/agent/stream   — SSE 流式执行，逐步推送事件
仅 ADMIN / PROFESSIONAL 角色可调用。
"""
import json
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import require_role
from app.models.enums import UserRole
from app.services.agent_service import run_agent, run_agent_stream
from app.tools.response import fail, ok

router = APIRouter(prefix="/agent", tags=["agent"])

_DOCTOR = require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)


class AgentRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="自然语言指令")


@router.post("/stream")
async def agent_stream(
    body: AgentRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_DOCTOR),
):
    """
    SSE 流式执行自然语言指令。
    响应 Content-Type: text/event-stream，每个事件格式：data: {JSON}\n\n
    事件类型: thinking / tool_call / tool_result / done / error
    """
    async def generate() -> AsyncIterator[str]:
        try:
            async for event in run_agent_stream(body.query, db, current_user):
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:
            import traceback
            traceback.print_exc()
            err = json.dumps({"type": "error", "message": f"流式执行出错：{exc}"}, ensure_ascii=False)
            yield f"data: {err}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/execute")
async def agent_execute(
    body: AgentRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_DOCTOR),
):
    """
    执行自然语言指令。

    返回：
    - message: 给用户的文字说明
    - data: 查询结果（可能为 null）
    - navigate_url: 若需跳转页面则返回目标 URL
    - execution_id: 审计追溯 ID
    """
    try:
        result = await run_agent(body.query, db, current_user)
        return ok(result)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return fail("AGENT_ERROR", f"执行出错：{exc}", status_code=500)
