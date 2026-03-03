from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import DiseaseType, FollowupStatus
from app.models.followup import CheckIn, FollowupPlan, FollowupTask
from app.services.audit_service import log_action
from app.services.followup_service import get_adherence, record_checkin, start_plan
from app.tools.response import fail, ok

router = APIRouter(prefix="/followup", tags=["followup-tools"])


class StartPlanRequest(BaseModel):
    disease_type: DiseaseType
    start_date: str | None = None  # YYYY-MM-DD


@router.post("/start")
async def start_followup_plan(
    body: StartPlanRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    start = date.fromisoformat(body.start_date) if body.start_date else None
    plan = await start_plan(db, current_user.id, body.disease_type, start)
    await log_action(
        db, action="START_FOLLOWUP_PLAN", resource_type="FollowupPlan",
        user_id=current_user.id, resource_id=str(plan.id),
        new_values={"disease_type": body.disease_type.value},
    )
    await db.commit()
    return ok({
        "plan_id": str(plan.id),
        "disease_type": body.disease_type.value,
        "start_date": str(plan.start_date),
        "end_date": str(plan.end_date),
    }, status_code=201)


@router.get("/today")
async def today_tasks(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    today = date.today()
    # 获取活跃计划的今日任务
    result = await db.execute(
        select(FollowupTask, CheckIn)
        .join(FollowupPlan, FollowupTask.plan_id == FollowupPlan.id)
        .join(CheckIn, and_(CheckIn.task_id == FollowupTask.id, CheckIn.user_id == current_user.id))
        .where(
            and_(
                FollowupPlan.user_id == current_user.id,
                FollowupPlan.status == FollowupStatus.ACTIVE,
                FollowupTask.scheduled_date == today,
            )
        )
    )
    rows = result.all()
    return ok([
        {
            "task_id": str(task.id),
            "plan_id": str(task.plan_id),
            "name": task.name,
            "task_type": task.task_type.value,
            "required": task.required,
            "meta": task.meta,
            "checkin_id": str(checkin.id),
            "checkin_status": checkin.status.value,
            "checked_at": checkin.checked_at.isoformat() if checkin.checked_at else None,
        }
        for task, checkin in rows
    ])


class CheckInRequest(BaseModel):
    task_id: str
    value: dict | None = None
    note: str | None = None


@router.post("/checkin")
async def do_checkin(
    body: CheckInRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    import uuid
    task_id = uuid.UUID(body.task_id)
    checkin = await record_checkin(db, task_id, current_user.id, body.value, body.note)
    await log_action(
        db, action="CHECKIN", resource_type="CheckIn",
        user_id=current_user.id, resource_id=str(checkin.id),
        new_values={"status": "DONE", "value": body.value},
    )
    await db.commit()
    return ok({
        "checkin_id": str(checkin.id),
        "status": checkin.status.value,
        "checked_at": checkin.checked_at.isoformat() if checkin.checked_at else None,
    })


@router.get("/adherence")
async def adherence(
    plan_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    import uuid
    pid = uuid.UUID(plan_id)
    # 校验计划归属
    result = await db.execute(
        select(FollowupPlan).where(
            and_(FollowupPlan.id == pid, FollowupPlan.user_id == current_user.id)
        )
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        return fail("NOT_FOUND", "随访计划不存在", status_code=404)

    rate = await get_adherence(db, pid)
    return ok({"plan_id": plan_id, "adherence_rate": rate})


@router.get("/plans")
async def list_plans(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    result = await db.execute(
        select(FollowupPlan)
        .where(FollowupPlan.user_id == current_user.id)
        .order_by(FollowupPlan.created_at.desc())
    )
    plans = result.scalars().all()
    return ok([
        {
            "id": str(p.id),
            "disease_type": p.disease_type.value,
            "status": p.status.value,
            "start_date": str(p.start_date),
            "end_date": str(p.end_date),
        }
        for p in plans
    ])
