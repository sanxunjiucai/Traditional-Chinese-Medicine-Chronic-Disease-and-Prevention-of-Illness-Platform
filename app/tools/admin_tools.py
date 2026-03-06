"""
管理端专属 API：患者管理、用户管理、随访质控、统计概览。
所有接口均需 ADMIN 或 PROFESSIONAL 角色。
"""
import uuid as uuid_lib
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import require_role
from app.models.alert import AlertEvent
from app.models.archive import PatientArchive
from app.models.constitution import ConstitutionAssessment
from app.models.enums import (
    AlertStatus, AssessmentStatus, BodyType, CheckInStatus,
    FollowupStatus, UserRole,
)
from app.models.followup import CheckIn, FollowupPlan, FollowupTask
from app.models.health import HealthProfile
from app.models.user import User
from app.services.audit_service import log_action
from app.services.auth_service import hash_password
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


# ══════════════════════════════════════════════
# 体质评估管理（管理端列表）
# ══════════════════════════════════════════════

@router.get("/assessments")
async def list_assessments(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    status: AssessmentStatus | None = Query(default=None),
    body_type: BodyType | None = Query(default=None),
    q: str | None = Query(default=None, description="按患者姓名搜索"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """返回所有患者的体质评估记录（管理视图）。"""
    # 先过滤评估
    assess_filters = []
    if status:
        assess_filters.append(ConstitutionAssessment.status == status)
    if body_type:
        assess_filters.append(ConstitutionAssessment.main_type == body_type)

    total_r = await db.execute(
        select(func.count()).select_from(ConstitutionAssessment)
        .where(and_(*assess_filters) if assess_filters else True)
    )
    total = total_r.scalar_one()

    offset = (page - 1) * page_size
    assess_result = await db.execute(
        select(ConstitutionAssessment)
        .where(and_(*assess_filters) if assess_filters else True)
        .order_by(ConstitutionAssessment.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    assessments = assess_result.scalars().all()

    items = []
    for a in assessments:
        user_r = await db.execute(select(User).where(User.id == a.user_id))
        user = user_r.scalar_one_or_none()
        # 患者名搜索过滤
        if q and user and q not in user.name:
            continue
        items.append({
            "id": str(a.id),
            "user_id": str(a.user_id),
            "user_name": user.name if user else "未知",
            "user_phone": user.phone if user else "",
            "status": a.status.value,
            "main_type": a.main_type.value if a.main_type else None,
            "secondary_types": a.secondary_types or [],
            "created_at": a.created_at.isoformat(),
            "scored_at": a.scored_at.isoformat() if a.scored_at else None,
        })

    return ok({"total": total, "page": page, "page_size": page_size, "items": items})


# ══════════════════════════════════════════════
# 健康量表评估管理（管理端列表 / 详情）
# ══════════════════════════════════════════════

@router.get("/health-assess")
async def list_health_assessments(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    q: str | None = Query(default=None, description="按患者姓名搜索"),
    status: str | None = Query(default=None, description="DRAFT/SUBMITTED/REPORTED"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """健康量表评估列表（ScaleRecord + PatientArchive + Scale）。"""
    from datetime import datetime as _dt
    import uuid as _uuid
    from app.models.scale import Scale, ScaleRecord
    from app.models.archive import PatientArchive

    filters = []
    if date_from:
        try:
            filters.append(ScaleRecord.created_at >= _dt.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            filters.append(ScaleRecord.created_at <= _dt.fromisoformat(date_to))
        except ValueError:
            pass

    where_clause = and_(*filters) if filters else True
    total_r = await db.execute(
        select(func.count()).select_from(ScaleRecord).where(where_clause)
    )
    total = total_r.scalar_one()

    offset = (page - 1) * page_size
    records_r = await db.execute(
        select(ScaleRecord)
        .where(where_clause)
        .order_by(ScaleRecord.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    records = records_r.scalars().all()

    items = []
    for r in records:
        patient_name = "未知患者"
        if r.patient_archive_id:
            try:
                pa_r = await db.execute(
                    select(PatientArchive).where(
                        PatientArchive.id == _uuid.UUID(str(r.patient_archive_id))
                    )
                )
                pa = pa_r.scalar_one_or_none()
                if pa:
                    patient_name = pa.name
            except Exception:
                pass
        if q and q not in patient_name:
            continue

        scale_name = "健康量表评估"
        scale_r = await db.execute(select(Scale).where(Scale.id == r.scale_id))
        scale = scale_r.scalar_one_or_none()
        if scale:
            scale_name = scale.name

        if r.completed_at is None:
            rec_status = "DRAFT"
        elif r.conclusion:
            rec_status = "REPORTED"
        else:
            rec_status = "SUBMITTED"

        if status and rec_status != status:
            continue

        items.append({
            "id": str(r.id),
            "patient_name": patient_name,
            "assess_type": scale_name,
            "status": rec_status,
            "total_score": r.total_score,
            "created_at": r.created_at.isoformat(),
        })

    return ok({"total": total, "page": page, "page_size": page_size, "items": items})


@router.get("/health-assess/{assess_id}")
async def get_health_assessment(
    assess_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
):
    """健康量表评估详情（ScaleRecord + PatientArchive + Scale）。"""
    import uuid as _uuid
    import json as _json
    from app.models.scale import Scale, ScaleRecord, ScaleQuestion
    from app.models.archive import PatientArchive

    try:
        rid = int(assess_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "assess_id 格式错误", status_code=400)

    r_result = await db.execute(select(ScaleRecord).where(ScaleRecord.id == rid))
    r = r_result.scalar_one_or_none()
    if r is None:
        return fail("NOT_FOUND", "评估记录不存在", status_code=404)

    patient_name, archive_id_str = "未知患者", None
    if r.patient_archive_id:
        try:
            pa_r = await db.execute(
                select(PatientArchive).where(
                    PatientArchive.id == _uuid.UUID(str(r.patient_archive_id))
                )
            )
            pa = pa_r.scalar_one_or_none()
            if pa:
                patient_name, archive_id_str = pa.name, str(pa.id)
        except Exception:
            pass

    scale_name, scale_total = "健康量表评估", None
    scale_r = await db.execute(select(Scale).where(Scale.id == r.scale_id))
    scale = scale_r.scalar_one_or_none()
    if scale:
        scale_name, scale_total = scale.name, scale.total_score

    if r.completed_at is None:
        rec_status = "DRAFT"
    elif r.conclusion:
        rec_status = "REPORTED"
    else:
        rec_status = "SUBMITTED"

    answers = {}
    if r.answers:
        try:
            answers = _json.loads(r.answers) if isinstance(r.answers, str) else r.answers
        except Exception:
            pass

    questions_r = await db.execute(
        select(ScaleQuestion)
        .where(ScaleQuestion.scale_id == r.scale_id)
        .order_by(ScaleQuestion.question_no)
    )
    questions = questions_r.scalars().all()

    items = []
    for sq in questions:
        val = answers.get(str(sq.id), answers.get(f"q{sq.question_no}"))
        if val is not None:
            items.append({
                "name": sq.question_text[:30],
                "score": val,
                "note": sq.dimension or "",
            })

    return ok({
        "id": str(r.id),
        "patient_name": patient_name,
        "archive_id": archive_id_str,
        "scale_name": scale_name,
        "status": rec_status,
        "total_score": r.total_score,
        "score_range": f"满分{scale_total}分" if scale_total else "",
        "level": r.level,
        "risk": None,
        "conclusion": r.conclusion,
        "suggestions": [],
        "items": items,
        "created_at": r.created_at.isoformat(),
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
    })


@router.patch("/health-assess/{assess_id}/report")
async def update_health_assessment_report(
    assess_id: str,
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
):
    """保存健康量表评估报告（更新 ScaleRecord 的 conclusion/level 字段）。"""
    from datetime import datetime as _dt, timezone
    from app.models.scale import ScaleRecord

    try:
        rid = int(assess_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "assess_id 格式错误", status_code=400)

    r_result = await db.execute(select(ScaleRecord).where(ScaleRecord.id == rid))
    r = r_result.scalar_one_or_none()
    if r is None:
        return fail("NOT_FOUND", "评估记录不存在", status_code=404)

    if "conclusion" in body:
        r.conclusion = body["conclusion"]
    if "level" in body:
        r.level = body["level"]

    report_status = body.get("report_status")
    if report_status in ("APPROVED", "REPORTED"):
        r.completed_at = _dt.now(timezone.utc)

    await db.commit()
    return ok({"id": str(r.id)})


# ══════════════════════════════════════════════
# 医生工作台聚合数据
# ══════════════════════════════════════════════

@router.get("/workbench")
async def workbench_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
):
    """医生工作台：今日任务、预警摘要、个人工作量统计。"""
    from datetime import date, datetime, timezone

    today = date.today()

    # ── 今日到期随访计划（按开始/结束日期）──
    active_plans_r = await db.execute(
        select(FollowupPlan)
        .where(
            and_(
                FollowupPlan.status == FollowupStatus.ACTIVE,
                FollowupPlan.start_date <= today,
                FollowupPlan.end_date >= today,
            )
        )
        .limit(5)
    )
    active_plans = active_plans_r.scalars().all()
    followup_today = []
    for plan in active_plans:
        user_r = await db.execute(select(User).where(User.id == plan.user_id))
        user = user_r.scalar_one_or_none()
        followup_today.append({
            "plan_id": str(plan.id),
            "user_name": user.name if user else "未知",
            "disease_type": plan.disease_type.value,
            "end_date": str(plan.end_date),
        })

    # ── 开放预警（OPEN）──
    open_alerts_r = await db.execute(
        select(func.count()).select_from(AlertEvent)
        .where(AlertEvent.status == AlertStatus.OPEN)
    )
    open_alerts = open_alerts_r.scalar_one()

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

    # ── 待审评估（SUBMITTED 或 SCORED）──
    pending_assess_r = await db.execute(
        select(func.count()).select_from(ConstitutionAssessment)
        .where(ConstitutionAssessment.status.in_([AssessmentStatus.SUBMITTED, AssessmentStatus.SCORED]))
    )
    pending_assess = pending_assess_r.scalar_one()

    # ── 本月随访完成量 ──
    month_start = datetime(today.year, today.month, 1, tzinfo=timezone.utc)
    done_r = await db.execute(
        select(func.count()).select_from(CheckIn)
        .where(
            and_(
                CheckIn.status == CheckInStatus.DONE,
                CheckIn.checked_at >= month_start,
            )
        )
    )
    monthly_done = done_r.scalar_one()

    # ── 总患者数 ──
    total_patients_r = await db.execute(
        select(func.count()).select_from(User).where(User.role == UserRole.PATIENT)
    )
    total_patients = total_patients_r.scalar_one()

    # ── 体质分布（最近 REPORTED 评估）──
    body_dist_r = await db.execute(
        select(ConstitutionAssessment.main_type, func.count())
        .where(ConstitutionAssessment.status == AssessmentStatus.REPORTED)
        .group_by(ConstitutionAssessment.main_type)
    )
    body_distribution = {
        row[0].value: row[1]
        for row in body_dist_r.all()
        if row[0] is not None
    }

    return ok({
        "followup_today": followup_today,
        "open_alerts": open_alerts,
        "high_severity_alerts": high_alerts,
        "pending_assessments": pending_assess,
        "monthly_done_checkins": monthly_done,
        "total_patients": total_patients,
        "body_distribution": body_distribution,
    })


# ══════════════════════════════════════════════
# 系统用户管理（ADMIN 专属）
# ══════════════════════════════════════════════

_ROLE_MAP = {
    "ADMIN": UserRole.ADMIN,
    "PROFESSIONAL": UserRole.PROFESSIONAL,
    "PATIENT": UserRole.PATIENT,
}

_ADMIN_ONLY = require_role(UserRole.ADMIN)


class UserCreateRequest(BaseModel):
    name: str
    phone: str
    email: str | None = None
    password: str
    roles: list[str] = []          # 取第一个有效角色
    is_active: bool = True
    # 以下字段模型暂不持久化，仅接受避免 422
    emp_no: str | None = None
    gender: str | None = None
    account: str | None = None
    expire_at: str | None = None
    org_id: str | None = None
    dept: str | None = None
    is_doctor: bool = False
    title: str | None = None
    specialty: str | None = None


class UserUpdateRequest(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    password: str | None = None
    roles: list[str] | None = None
    is_active: bool | None = None
    emp_no: str | None = None
    gender: str | None = None
    account: str | None = None
    expire_at: str | None = None
    org_id: str | None = None
    dept: str | None = None
    is_doctor: bool | None = None
    title: str | None = None
    specialty: str | None = None


def _user_dict(u: User) -> dict:
    return {
        "id": str(u.id),
        "name": u.name,
        "phone": u.phone,
        "email": u.email,
        "role": u.role.value,
        "roles": [u.role.value],
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat(),
        # 前端期望的可选字段（User 模型暂无，返回空）
        "emp_no": "",
        "gender": "",
        "title": "",
        "specialty": "",
        "org": "",
        "dept": "",
        "last_login": "",
    }


@router.get("/users")
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
    q: str | None = Query(default=None, description="按姓名/手机号搜索"),
    role: UserRole | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    filters = []
    if q:
        filters.append((User.name.contains(q)) | (User.phone.contains(q)))
    if role is not None:
        filters.append(User.role == role)
    if is_active is not None:
        filters.append(User.is_active == is_active)

    total_r = await db.execute(
        select(func.count()).select_from(User).where(and_(*filters) if filters else True)
    )
    total = total_r.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        select(User)
        .where(and_(*filters) if filters else True)
        .order_by(User.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    users = result.scalars().all()

    return ok({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_user_dict(u) for u in users],
    })


@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
):
    try:
        uid = uuid_lib.UUID(user_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "user_id 格式错误", status_code=400)

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None:
        return fail("NOT_FOUND", "用户不存在", status_code=404)
    return ok(_user_dict(user))


@router.post("/users")
async def create_user(
    body: UserCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
):
    # 手机号唯一性检查
    dup = await db.execute(select(User).where(User.phone == body.phone))
    if dup.scalar_one_or_none() is not None:
        return fail("VALIDATION_ERROR", "该手机号已被注册", status_code=400)

    # 解析角色（取第一个合法值，默认 PROFESSIONAL）
    role = UserRole.PROFESSIONAL
    for r in body.roles:
        if r in _ROLE_MAP:
            role = _ROLE_MAP[r]
            break

    if len(body.password) < 6:
        return fail("VALIDATION_ERROR", "密码不能少于 6 位", status_code=400)

    user = User(
        name=body.name,
        phone=body.phone,
        email=body.email or None,
        password_hash=hash_password(body.password),
        role=role,
        is_active=body.is_active,
    )
    db.add(user)
    await db.flush()
    await log_action(
        db, action="CREATE_USER", resource_type="User",
        user_id=current_user.id, resource_id=str(user.id),
        new_values={"name": body.name, "phone": body.phone, "role": role.value},
    )
    await db.commit()
    return ok({"user_id": str(user.id)}, status_code=201)


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
):
    try:
        uid = uuid_lib.UUID(user_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "user_id 格式错误", status_code=400)

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None:
        return fail("NOT_FOUND", "用户不存在", status_code=404)

    changed: dict = {}
    if body.name is not None:
        changed["name"] = body.name
        user.name = body.name
    if body.phone is not None and body.phone != user.phone:
        dup = await db.execute(select(User).where(User.phone == body.phone))
        if dup.scalar_one_or_none() is not None:
            return fail("VALIDATION_ERROR", "该手机号已被其他账号使用", status_code=400)
        changed["phone"] = body.phone
        user.phone = body.phone
    if body.email is not None:
        changed["email"] = body.email
        user.email = body.email or None
    if body.is_active is not None:
        changed["is_active"] = body.is_active
        user.is_active = body.is_active
    if body.roles is not None and body.roles:
        for r in body.roles:
            if r in _ROLE_MAP:
                changed["role"] = r
                user.role = _ROLE_MAP[r]
                break
    if body.password:
        if len(body.password) < 6:
            return fail("VALIDATION_ERROR", "密码不能少于 6 位", status_code=400)
        user.password_hash = hash_password(body.password)
        changed["password"] = "***"

    if changed:
        db.add(user)
        await log_action(
            db, action="UPDATE_USER", resource_type="User",
            user_id=current_user.id, resource_id=user_id,
            new_values=changed,
        )
        await db.commit()

    return ok(_user_dict(user))


# ══════════════════════════════════════════════
# 随访任务管理（管理端）
# ══════════════════════════════════════════════

@router.get("/followup/tasks")
async def list_followup_tasks(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    q: str | None = Query(default=None, description="患者姓名搜索"),
    status: str | None = Query(default=None, description="PENDING/DONE/MISSED"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """管理端随访任务列表（含患者姓名、档案ID、派生状态）。"""
    from datetime import date as _date
    offset = (page - 1) * page_size

    filters = []
    if q:
        filters.append(User.name.contains(q))

    where = and_(*filters) if filters else True

    total_r = await db.execute(
        select(func.count()).select_from(FollowupTask)
        .join(FollowupPlan, FollowupTask.plan_id == FollowupPlan.id)
        .join(User, FollowupPlan.user_id == User.id)
        .where(where)
    )
    total = total_r.scalar_one()

    rows_r = await db.execute(
        select(FollowupTask, FollowupPlan, User)
        .join(FollowupPlan, FollowupTask.plan_id == FollowupPlan.id)
        .join(User, FollowupPlan.user_id == User.id)
        .where(where)
        .order_by(FollowupTask.scheduled_date.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows = rows_r.all()

    items = []
    for task, plan, user in rows:
        ci_r = await db.execute(
            select(CheckIn)
            .where(CheckIn.task_id == task.id)
            .order_by(CheckIn.created_at.desc())
            .limit(1)
        )
        ci = ci_r.scalar_one_or_none()

        if ci:
            task_status = ci.status.value
        elif task.scheduled_date < _date.today():
            task_status = "MISSED"
        else:
            task_status = "PENDING"

        if status and task_status != status:
            continue

        arc_r = await db.execute(
            select(PatientArchive).where(PatientArchive.user_id == plan.user_id)
        )
        arc = arc_r.scalar_one_or_none()

        items.append({
            "id": str(task.id),
            "patient_name": user.name,
            "user_id": str(plan.user_id),
            "archive_id": str(arc.id) if arc else None,
            "plan_name": plan.disease_type.value,
            "task_name": task.name,
            "task_type": task.task_type.value,
            "method": (task.meta or {}).get("method", "PHONE"),
            "scheduled_at": str(task.scheduled_date),
            "status": task_status,
        })

    return ok({"total": total, "page": page, "page_size": page_size, "items": items})


@router.get("/followup/tasks/{task_id}")
async def get_followup_task(
    task_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
):
    """管理端随访任务详情（含患者信息和打卡历史）。"""
    import uuid as _uuid
    from datetime import date as _date
    try:
        tid = _uuid.UUID(task_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "task_id 格式错误", status_code=400)

    task_r = await db.execute(select(FollowupTask).where(FollowupTask.id == tid))
    task = task_r.scalar_one_or_none()
    if task is None:
        return fail("NOT_FOUND", "随访任务不存在", status_code=404)

    plan_r = await db.execute(select(FollowupPlan).where(FollowupPlan.id == task.plan_id))
    plan = plan_r.scalar_one_or_none()

    user = None
    arc = None
    if plan:
        user_r = await db.execute(select(User).where(User.id == plan.user_id))
        user = user_r.scalar_one_or_none()
        arc_r = await db.execute(
            select(PatientArchive).where(PatientArchive.user_id == plan.user_id)
        )
        arc = arc_r.scalar_one_or_none()

    checkins_r = await db.execute(
        select(CheckIn)
        .where(CheckIn.task_id == task.id)
        .order_by(CheckIn.created_at.desc())
        .limit(20)
    )
    checkins = checkins_r.scalars().all()

    latest_ci = checkins[0] if checkins else None
    if latest_ci:
        task_status = latest_ci.status.value
    elif task.scheduled_date < _date.today():
        task_status = "MISSED"
    else:
        task_status = "PENDING"

    return ok({
        "id": str(task.id),
        "patient_name": user.name if user else "未知患者",
        "user_id": str(plan.user_id) if plan else None,
        "archive_id": str(arc.id) if arc else None,
        "plan_name": plan.disease_type.value if plan else "",
        "task_name": task.name,
        "task_type": task.task_type.value,
        "scheduled_at": str(task.scheduled_date),
        "status": task_status,
        "created_at": task.created_at.isoformat(),
        "checkins": [
            {
                "id": str(ci.id),
                "status": ci.status.value,
                "value": ci.value,
                "note": ci.note,
                "checked_at": ci.checked_at.isoformat() if ci.checked_at else None,
            }
            for ci in checkins
        ],
    })
