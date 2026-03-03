"""
管理端专属 API：患者管理、随访质控、统计概览。
所有接口均需 ADMIN 或 PROFESSIONAL 角色。
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import require_role
from app.models.alert import AlertEvent
from app.models.constitution import ConstitutionAssessment
from app.models.enums import (
    AlertStatus, AssessmentStatus, BodyType, CheckInStatus,
    FollowupStatus, UserRole,
)
from app.models.followup import CheckIn, FollowupPlan, FollowupTask
from app.models.health import HealthProfile
from app.models.user import User
from app.services.audit_service import log_action
from app.tools.response import fail, ok

router = APIRouter(prefix="/admin", tags=["admin-tools"])

_ADMIN_OR_PRO = require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)


# ══════════════════════════════════════════════
# 患者管理
# ══════════════════════════════════════════════

@router.get("/patients")
async def list_patients(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    q: str | None = Query(default=None, description="按姓名/手机号搜索"),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    filters = [User.role == UserRole.PATIENT]
    if is_active is not None:
        filters.append(User.is_active == is_active)
    if q:
        filters.append(
            (User.name.contains(q)) | (User.phone.contains(q))
        )

    total_result = await db.execute(
        select(func.count()).select_from(User).where(and_(*filters))
    )
    total = total_result.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        select(User)
        .where(and_(*filters))
        .order_by(User.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    users = result.scalars().all()

    return ok({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": str(u.id),
                "name": u.name,
                "phone": u.phone,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat(),
            }
            for u in users
        ],
    })


@router.patch("/patients/{patient_id}/toggle-active")
async def toggle_patient_active(
    patient_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    import uuid
    result = await db.execute(
        select(User).where(
            and_(User.id == uuid.UUID(patient_id), User.role == UserRole.PATIENT)
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        return fail("NOT_FOUND", "患者不存在", status_code=404)

    old_active = user.is_active
    user.is_active = not user.is_active
    db.add(user)
    await log_action(
        db, action="TOGGLE_USER_ACTIVE", resource_type="User",
        user_id=current_user.id, resource_id=patient_id,
        old_values={"is_active": old_active},
        new_values={"is_active": user.is_active},
    )
    await db.commit()
    return ok({"patient_id": patient_id, "is_active": user.is_active})


# ══════════════════════════════════════════════
# 随访质控
# ══════════════════════════════════════════════

@router.get("/followup")
async def followup_quality_control(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """返回所有患者的随访计划依从性汇总，按依从率升序（最差的排最前）。"""
    # 获取所有活跃随访计划（join 用户名）
    offset = (page - 1) * page_size

    total_result = await db.execute(
        select(func.count()).select_from(FollowupPlan)
        .where(FollowupPlan.status == FollowupStatus.ACTIVE)
    )
    total = total_result.scalar_one()

    plans_result = await db.execute(
        select(FollowupPlan)
        .where(FollowupPlan.status == FollowupStatus.ACTIVE)
        .order_by(FollowupPlan.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    plans = plans_result.scalars().all()

    items = []
    for plan in plans:
        # 总任务数 / 已完成 / 漏打
        total_tasks_r = await db.execute(
            select(func.count()).select_from(CheckIn)
            .where(CheckIn.task_id.in_(
                select(FollowupTask.id).where(FollowupTask.plan_id == plan.id)
            ))
        )
        total_tasks = total_tasks_r.scalar_one()

        done_r = await db.execute(
            select(func.count()).select_from(CheckIn)
            .where(
                and_(
                    CheckIn.task_id.in_(
                        select(FollowupTask.id).where(FollowupTask.plan_id == plan.id)
                    ),
                    CheckIn.status == CheckInStatus.DONE,
                )
            )
        )
        done = done_r.scalar_one()

        missed_r = await db.execute(
            select(func.count()).select_from(CheckIn)
            .where(
                and_(
                    CheckIn.task_id.in_(
                        select(FollowupTask.id).where(FollowupTask.plan_id == plan.id)
                    ),
                    CheckIn.status == CheckInStatus.MISSED,
                )
            )
        )
        missed = missed_r.scalar_one()

        adherence = round(done / total_tasks, 3) if total_tasks > 0 else 0.0

        # 患者姓名
        user_r = await db.execute(select(User).where(User.id == plan.user_id))
        user = user_r.scalar_one_or_none()

        items.append({
            "plan_id": str(plan.id),
            "user_id": str(plan.user_id),
            "user_name": user.name if user else "未知",
            "user_phone": user.phone if user else "",
            "disease_type": plan.disease_type.value,
            "start_date": str(plan.start_date),
            "end_date": str(plan.end_date),
            "total_tasks": total_tasks,
            "done": done,
            "missed": missed,
            "adherence_rate": adherence,
        })

    # 按依从率升序（最差排前）
    items.sort(key=lambda x: x["adherence_rate"])

    return ok({"total": total, "page": page, "page_size": page_size, "items": items})


# ══════════════════════════════════════════════
# 统计概览
# ══════════════════════════════════════════════

@router.get("/stats/overview")
async def stats_overview(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
):
    """管理端首页统计：患者总数、在管患者、开放预警、体质分布。"""
    # 患者总数
    total_patients_r = await db.execute(
        select(func.count()).select_from(User).where(User.role == UserRole.PATIENT)
    )
    total_patients = total_patients_r.scalar_one()

    # 活跃患者（有活跃随访计划）
    active_patients_r = await db.execute(
        select(func.count(FollowupPlan.user_id.distinct()))
        .where(FollowupPlan.status == FollowupStatus.ACTIVE)
    )
    active_patients = active_patients_r.scalar_one()

    # 开放预警数
    open_alerts_r = await db.execute(
        select(func.count()).select_from(AlertEvent)
        .where(AlertEvent.status == AlertStatus.OPEN)
    )
    open_alerts = open_alerts_r.scalar_one()

    # 高危预警数（HIGH severity + OPEN）
    from app.models.enums import AlertSeverity
    high_alerts_r = await db.execute(
        select(func.count()).select_from(AlertEvent)
        .where(
            and_(
                AlertEvent.status == AlertStatus.OPEN,
                AlertEvent.severity == AlertSeverity.HIGH,
            )
        )
    )
    high_alerts = high_alerts_r.scalar_one()

    # 体质分布（最新评估，只取 REPORTED）
    body_type_result = await db.execute(
        select(ConstitutionAssessment.main_type, func.count())
        .where(ConstitutionAssessment.status == AssessmentStatus.REPORTED)
        .group_by(ConstitutionAssessment.main_type)
    )
    body_type_dist = {
        row[0].value: row[1]
        for row in body_type_result.all()
        if row[0] is not None
    }

    # 随访依从性整体均值
    done_r = await db.execute(
        select(func.count()).select_from(CheckIn)
        .where(CheckIn.status == CheckInStatus.DONE)
    )
    done_count = done_r.scalar_one()

    total_checkins_r = await db.execute(
        select(func.count()).select_from(CheckIn)
        .where(CheckIn.status != CheckInStatus.PENDING)
    )
    total_checkins = total_checkins_r.scalar_one()

    overall_adherence = round(done_count / total_checkins, 3) if total_checkins > 0 else None

    return ok({
        "total_patients": total_patients,
        "active_patients": active_patients,
        "open_alerts": open_alerts,
        "high_severity_alerts": high_alerts,
        "body_type_distribution": body_type_dist,
        "overall_adherence_rate": overall_adherence,
    })
