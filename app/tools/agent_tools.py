"""
Agent API: POST /tools/agent/execute
接收医生的自然语言指令，调用 AgentService 执行，返回结构化结果。
仅 ADMIN / PROFESSIONAL 角色可调用。
"""
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import require_role
from app.models.enums import UserRole
from app.services.agent_service import run_agent
from app.tools.response import fail, ok

router = APIRouter(prefix="/agent", tags=["agent"])

_DOCTOR = require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)


class AgentRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="自然语言指令")


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
        return fail("AGENT_ERROR", f"执行出错：{exc}", status_code=500)
