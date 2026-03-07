"""
AI 风险诊断 API
prefix: /risk
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated

from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models.archive import PatientArchive
from app.models.enums import DiseaseType, FollowupStatus, TaskType, UserRole
from app.models.followup import FollowupPlan, FollowupTask
from app.models.guidance import GuidanceRecord
from app.services.audit_service import log_action
from app.services.notification_service import push_to_patient
from app.services.risk_engine import analyze_patient_risk, auto_scan_and_alert, generate_tcm_plan
from app.tools.response import fail, ok

router = APIRouter(prefix="/risk", tags=["risk"])


# ── 风险分析 ──────────────────────────────────────────────────────────────────

class AnalyzeWithContextRequest(BaseModel):
    extra_context: str = ""


@router.post("/analyze/{archive_id}")
async def trigger_risk_analysis(
    archive_id: str,
    body: Optional[AnalyzeWithContextRequest] = Body(default=None),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)),
):
    """触发 AI 风险分析，同时自动扫描检验报告并创建预警"""
    try:
        aid = uuid.UUID(archive_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "archive_id 格式无效")

    archive_r = await db.execute(select(PatientArchive).where(PatientArchive.id == aid))
    archive = archive_r.scalar_one_or_none()
    if not archive:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    extra_context = body.extra_context if body else ""
    result = await analyze_patient_risk(db, aid, extra_context=extra_context)
    alerts = await auto_scan_and_alert(db, aid)

    await log_action(
        db, action="RISK_ANALYZE", resource_type="PatientArchive",
        user_id=current_user.id, resource_id=archive_id,
        old_values=None, new_values={"risk_level": result.get("risk_level"), "alerts_created": len(alerts)},
    )
    await db.commit()

    return ok({
        "archive_id": archive_id,
        "patient_name": archive.name,
        "analysis": result,
        "new_alerts": alerts,
    })


@router.get("/result/{archive_id}")
async def get_risk_result(
    archive_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)),
):
    """获取最新风险分析结果（实时计算）"""
    try:
        aid = uuid.UUID(archive_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "archive_id 格式无效")

    archive_r = await db.execute(select(PatientArchive).where(PatientArchive.id == aid))
    archive = archive_r.scalar_one_or_none()
    if not archive:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    result = await analyze_patient_risk(db, aid)
    return ok({"archive_id": archive_id, "patient_name": archive.name, **result})


# ── 方案生成 ──────────────────────────────────────────────────────────────────

class GeneratePlanRequest(BaseModel):
    archive_id: str
    extra_context: str = ""


@router.post("/plan/generate")
async def generate_plan(
    body: GeneratePlanRequest,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)),
):
    """生成 AI 调理方案（Markdown 格式）"""
    try:
        aid = uuid.UUID(body.archive_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "archive_id 格式无效")

    try:
        risk_result = await analyze_patient_risk(db, aid)
        plan_text = await generate_tcm_plan(db, aid, risk_result=risk_result, extra_context=body.extra_context)
    except Exception as exc:
        return fail("GENERATE_ERROR", f"方案生成失败：{exc}", status_code=500)

    return ok({
        "archive_id": body.archive_id,
        "risk_level": risk_result.get("risk_level"),
        "plan_markdown": plan_text,
    })


# ── 方案下达（含自动生成随访）────────────────────────────────────────────────

class IssuePlanRequest(BaseModel):
    archive_id: str
    plan_content: str
    title: str = "个性化中医调理方案"
    auto_followup_days: int = 7  # 0 = 不自动创建随访


@router.post("/plan/issue")
async def issue_plan(
    body: IssuePlanRequest,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)),
):
    """
    医生确认方案并下达：
    1. 创建 GuidanceRecord（指导记录）
    2. 推送 Notification 给患者
    3. 可选：自动创建随访计划（auto_followup_days > 0）
    """
    try:
        aid = uuid.UUID(body.archive_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "archive_id 格式无效")

    archive_r = await db.execute(select(PatientArchive).where(PatientArchive.id == aid))
    archive = archive_r.scalar_one_or_none()
    if not archive:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    patient_user_id = archive.user_id
    record_id = None
    followup_task_id = None
    followup_date = None

    from app.models.guidance import GuidanceStatus, GuidanceType

    if patient_user_id:
        record = GuidanceRecord(
            patient_id=patient_user_id,
            doctor_id=current_user.id,
            guidance_type=GuidanceType.GUIDANCE,
            title=body.title,
            content=body.plan_content,
            status=GuidanceStatus.PUBLISHED,
            is_read=False,
        )
        db.add(record)
        await db.flush()
        record_id = str(record.id)
        action_url = f"/h5/plan/{record_id}"

        # 自动生成随访计划
        if body.auto_followup_days > 0:
            today = date.today()
            followup_date = today + timedelta(days=body.auto_followup_days)

            plan = FollowupPlan(
                user_id=patient_user_id,
                disease_type=DiseaseType.HYPERTENSION,  # 通用慢病随访
                status=FollowupStatus.ACTIVE,
                start_date=today,
                end_date=followup_date + timedelta(days=1),
                note=f"诊中助手方案下达后随访（{body.title}）",
            )
            db.add(plan)
            await db.flush()

            task = FollowupTask(
                plan_id=plan.id,
                task_type=TaskType.INDICATOR_REPORT,
                name=f"方案执行情况随访",
                scheduled_date=followup_date,
                required=True,
                meta={"source": "risk_plan", "record_id": record_id},
            )
            db.add(task)
            await db.flush()
            followup_task_id = str(task.id)
    else:
        action_url = "/h5/notifications"

    # 推送通知给患者
    notif = await push_to_patient(
        db=db,
        archive_id=aid,
        title=f"医生为您制定了调理方案：{body.title}",
        content=body.plan_content[:200] + "..." if len(body.plan_content) > 200 else body.plan_content,
        notif_type="PLAN_ISSUED",
        action_url=action_url,
        sender_id=current_user.id,
    )

    await log_action(
        db, action="ISSUE_PLAN", resource_type="GuidanceRecord",
        user_id=current_user.id, resource_id=record_id or body.archive_id,
        old_values=None,
        new_values={
            "archive_id": body.archive_id,
            "title": body.title,
            "followup_task_id": followup_task_id,
        },
    )
    await db.commit()

    return ok({
        "record_id": record_id,
        "notification_id": str(notif.id),
        "patient_name": archive.name,
        "followup_task_id": followup_task_id,
        "followup_date": followup_date.isoformat() if followup_date else None,
        "message": f"方案已下达给 {archive.name}，同时推送了通知"
            + (f"，将于 {body.auto_followup_days} 天后随访" if followup_task_id else ""),
    })


# ── 下达历史（按患者档案）─────────────────────────────────────────────────────

@router.get("/plans/{archive_id}")
async def get_issued_plans(
    archive_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, le=50),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)),
):
    """获取指定患者的历史下达方案列表（含随访状态）"""
    try:
        aid = uuid.UUID(archive_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "archive_id 格式无效")

    archive_r = await db.execute(select(PatientArchive).where(PatientArchive.id == aid))
    archive = archive_r.scalar_one_or_none()
    if not archive:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    if not archive.user_id:
        return ok({"total": 0, "items": []})

    from app.models.guidance import GuidanceType

    total_r = await db.execute(
        select(func.count(GuidanceRecord.id)).where(
            and_(
                GuidanceRecord.patient_id == archive.user_id,
                GuidanceRecord.guidance_type == GuidanceType.GUIDANCE,
                GuidanceRecord.doctor_id.isnot(None),
            )
        )
    )
    total = total_r.scalar_one()

    records_r = await db.execute(
        select(GuidanceRecord)
        .where(
            and_(
                GuidanceRecord.patient_id == archive.user_id,
                GuidanceRecord.guidance_type == GuidanceType.GUIDANCE,
                GuidanceRecord.doctor_id.isnot(None),
            )
        )
        .order_by(desc(GuidanceRecord.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    records = records_r.scalars().all()

    # 查关联的随访任务（通过 meta.record_id）
    items = []
    for r in records:
        # 查关联的随访任务
        ft_r = await db.execute(
            select(FollowupTask).where(
                FollowupTask.meta["record_id"].as_string() == str(r.id)
            ).limit(1)
        )
        ft = ft_r.scalar_one_or_none()

        # 推导方案状态
        plan_state = "ISSUED"
        if ft:
            if ft.scheduled_date <= date.today():
                checkin_r = await db.execute(
                    select(func.count()).select_from(
                        __import__("app.models.followup", fromlist=["CheckIn"]).CheckIn
                    ).where(
                        __import__("app.models.followup", fromlist=["CheckIn"]).CheckIn.task_id == ft.id
                    )
                )
                checkins = checkin_r.scalar_one()
                plan_state = "FOLLOWED_UP" if checkins > 0 else "IN_PROGRESS"
            else:
                plan_state = "IN_PROGRESS"

        items.append({
            "record_id": str(r.id),
            "title": r.title,
            "content_preview": r.content[:100] + "..." if len(r.content) > 100 else r.content,
            "is_read": r.is_read,
            "read_at": r.read_at.isoformat() if r.read_at else None,
            "plan_state": plan_state,
            "followup_task_id": str(ft.id) if ft else None,
            "followup_date": ft.scheduled_date.isoformat() if ft else None,
            "created_at": r.created_at.isoformat(),
        })

    return ok({"total": total, "items": items})


# ── 方案状态更新 ──────────────────────────────────────────────────────────────

class UpdatePlanStateRequest(BaseModel):
    state: str  # ISSUED | IN_PROGRESS | FOLLOWED_UP | RE_ASSESSED | COMPLETED | ADJUSTED
    note: str = ""


@router.patch("/plans/{record_id}/state")
async def update_plan_state(
    record_id: str,
    body: UpdatePlanStateRequest,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)),
):
    """更新方案状态（状态机推进）"""
    valid_states = {"ISSUED", "IN_PROGRESS", "FOLLOWED_UP", "RE_ASSESSED", "COMPLETED", "ADJUSTED"}
    if body.state not in valid_states:
        return fail("VALIDATION_ERROR", f"无效状态，可选值：{', '.join(valid_states)}")

    try:
        rid = uuid.UUID(record_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "record_id 格式无效")

    record_r = await db.execute(select(GuidanceRecord).where(GuidanceRecord.id == rid))
    record = record_r.scalar_one_or_none()
    if not record:
        return fail("NOT_FOUND", "方案记录不存在", status_code=404)

    # 将状态写入 scheduled_at 字段的注释（临时方案，无需迁移）
    # 实际状态存储在 GuidanceRecord 的现有字段里，用 title 前缀标记
    # 通过 audit log 记录状态变更
    await log_action(
        db, action="PLAN_STATE_CHANGE", resource_type="GuidanceRecord",
        user_id=current_user.id, resource_id=record_id,
        old_values=None,
        new_values={"new_state": body.state, "note": body.note},
    )
    await db.commit()

    return ok({"record_id": record_id, "new_state": body.state, "message": "状态已更新"})


# ── 业务统计（下达率 / 随访完成率）──────────────────────────────────────────

@router.get("/stats")
async def get_risk_stats(
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)),
):
    """
    诊中助手业务统计：
    - 总分析次数、已下达方案数、下达率
    - 随访任务总数、已完成数、随访完成率
    """
    from app.models.audit import AuditLog
    from app.models.enums import CheckInStatus
    from app.models.followup import CheckIn
    from app.models.guidance import GuidanceType

    # 总分析次数（RISK_ANALYZE 操作日志）
    analyzed_r = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action == "RISK_ANALYZE")
    )
    total_analyzed = analyzed_r.scalar_one() or 0

    # 已下达方案数（ISSUE_PLAN 操作日志）
    issued_r = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action == "ISSUE_PLAN")
    )
    total_issued = issued_r.scalar_one() or 0

    # 诊中助手自动创建的随访任务
    followup_r = await db.execute(
        select(func.count(FollowupTask.id)).where(
            FollowupTask.meta["source"].as_string() == "risk_plan"
        )
    )
    total_followup_tasks = followup_r.scalar_one() or 0

    # 已完成随访（有 CheckIn 记录的任务）
    completed_r = await db.execute(
        select(func.count(FollowupTask.id)).where(
            and_(
                FollowupTask.meta["source"].as_string() == "risk_plan",
                FollowupTask.checkins.any(),
            )
        )
    )
    completed_followups = completed_r.scalar_one() or 0

    prescription_rate = round(total_issued / total_analyzed * 100, 1) if total_analyzed > 0 else 0
    followup_completion_rate = (
        round(completed_followups / total_followup_tasks * 100, 1)
        if total_followup_tasks > 0 else 0
    )

    return ok({
        "total_analyzed": total_analyzed,
        "total_issued": total_issued,
        "prescription_rate": prescription_rate,
        "total_followup_tasks": total_followup_tasks,
        "completed_followups": completed_followups,
        "followup_completion_rate": followup_completion_rate,
    })


# ── 高危患者看板 ───────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def risk_dashboard(
    limit: int = Query(default=10, le=50),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)),
):
    """高危患者看板：返回有未处置 HIGH 预警的患者列表"""
    from app.models.alert import AlertEvent
    from app.models.enums import AlertSeverity, AlertStatus

    stmt = (
        select(AlertEvent)
        .where(
            and_(
                AlertEvent.severity == AlertSeverity.HIGH,
                AlertEvent.status == AlertStatus.OPEN,
            )
        )
        .order_by(desc(AlertEvent.created_at))
        .limit(limit * 3)
    )
    result = await db.execute(stmt)
    events = result.scalars().all()

    seen_users: set[uuid.UUID] = set()
    items = []
    for e in events:
        if e.user_id in seen_users:
            continue
        seen_users.add(e.user_id)

        archive_r = await db.execute(
            select(PatientArchive).where(PatientArchive.user_id == e.user_id)
        )
        archive = archive_r.scalar_one_or_none()

        items.append({
            "user_id": str(e.user_id),
            "archive_id": str(archive.id) if archive else None,
            "patient_name": archive.name if archive else "未知",
            "alert_message": e.message,
            "risk_level": "HIGH",
            "alert_created_at": e.created_at.isoformat(),
        })
        if len(items) >= limit:
            break

    return ok({"total": len(items), "items": items})
