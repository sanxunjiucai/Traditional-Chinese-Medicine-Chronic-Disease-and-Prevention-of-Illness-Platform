"""
Assistant API: 计划-执行分离架构
POST /tools/assistant/plan - 意图识别 + 生成执行计划
POST /tools/assistant/execute - 执行计划并返回结果
"""
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import require_role
from app.models.enums import UserRole
from app.services.assistant_service import execute_plan, generate_plan
from app.tools.response import fail, ok

router = APIRouter(prefix="/assistant", tags=["assistant"])

_DOCTOR = require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)


class PlanRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="自然语言指令")
    context: dict = Field(default_factory=dict, description="上下文信息")


class ExecuteRequest(BaseModel):
    plan: dict = Field(..., description="执行计划")
    dry_run: bool = Field(default=False, description="是否为试运行")


@router.post("/plan")
async def assistant_plan(
    body: PlanRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_DOCTOR),
):
    """
    生成执行计划

    返回：
    {
      "intent": "CreateChildProfile",
      "arguments": {...},
      "missing_fields": [...],
      "steps": [...],
      "risk_level": "low|medium|high"
    }
    """
    try:
        plan = await generate_plan(body.query, db, current_user, body.context)
        if "error" in plan:
            return fail("PLAN_ERROR", plan["error"])
        return ok(plan)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return fail("PLAN_ERROR", f"生成计划失败：{exc}", status_code=500)


@router.post("/execute")
async def assistant_execute(
    body: ExecuteRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_DOCTOR),
):
    """
    执行计划

    返回：
    {
      "status": "success|failed",
      "executed_steps": [...],
      "created_entities": {...},
      "ui_actions": [...],
      "summary": "..."
    }
    """
    try:
        result = await execute_plan(body.plan, db, current_user, body.dry_run)
        return ok(result)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return fail("EXECUTE_ERROR", f"执行失败：{exc}", status_code=500)
