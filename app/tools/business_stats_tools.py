"""
商业运营统计 API
GET /stats/business        - 核心KPI指标
GET /stats/business/trend  - 月度趋势数据（近N个月）
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, date
from calendar import monthrange

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from sqlalchemy import func, select, and_, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.archive import PatientArchive
from app.models.alert import AlertEvent
from app.models.consultation import Consultation
from app.models.followup import CheckIn
from app.models.health import ChronicDiseaseRecord
from app.models.notification import Notification
from app.models.clinical import ClinicalDocument
from app.services.auth_service import decode_token
from app.tools.response import ok

router = APIRouter(prefix="/stats", tags=["business-stats"])


def _require_auth(access_token: str | None) -> dict:
    """校验 JWT Cookie，返回 payload；未登录则抛 401。"""
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    payload = decode_token(access_token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token 无效或已过期")
    if payload.get("role") not in ("ADMIN", "PROFESSIONAL"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
    return payload


def _month_range(year: int, month: int):
    """返回某月的 (start_datetime, end_datetime)，带UTC时区。"""
    first_day = datetime(year, month, 1, tzinfo=timezone.utc)
    last_day_num = monthrange(year, month)[1]
    last_day = datetime(year, month, last_day_num, 23, 59, 59, tzinfo=timezone.utc)
    return first_day, last_day


def _this_month_range():
    now = datetime.now(timezone.utc)
    return _month_range(now.year, now.month)


@router.get("/business")
async def get_business_stats(
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
):
    """核心商业KPI：复诊转化率/咨询收入/预警等"""
    _require_auth(access_token)
    start_of_month, end_of_month = _this_month_range()

    # ── 基础指标 ─────────────────────────────────────────────────────
    # 管理患者总数
    total_archives = (await db.execute(
        select(func.count()).select_from(PatientArchive)
    )).scalar_one()

    # 本月下达方案数（PLAN_ISSUED 通知）
    plans_this_month = (await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.notif_type == "PLAN_ISSUED",
            Notification.created_at >= start_of_month,
        )
    )).scalar_one()

    # 历史累计下达方案数
    plans_total = (await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.notif_type == "PLAN_ISSUED"
        )
    )).scalar_one()

    # 复诊转化率：收到方案通知的患者中，也发起了咨询的比例
    archives_with_plan = (await db.execute(
        select(func.count(distinct(Notification.archive_id))).select_from(Notification).where(
            Notification.notif_type == "PLAN_ISSUED"
        )
    )).scalar_one()

    archives_converted = (await db.execute(
        select(func.count(distinct(Consultation.archive_id))).select_from(Consultation)
    )).scalar_one()

    if archives_with_plan > 0:
        return_visit_rate = round(min(archives_converted / archives_with_plan, 1.0), 4)
    else:
        return_visit_rate = 0.0

    # 本月咨询数
    consultations_this_month = (await db.execute(
        select(func.count()).select_from(Consultation).where(
            Consultation.created_at >= start_of_month,
        )
    )).scalar_one()

    # 咨询收入估算（每次 50 元）
    consultation_revenue = consultations_this_month * 50

    # 随访完成率（所有打卡中已完成的比例）
    from app.models.followup import FollowupTask
    from sqlalchemy import join
    today = date.today()
    total_due_checkins = (await db.execute(
        select(func.count()).select_from(CheckIn)
        .join(FollowupTask, CheckIn.task_id == FollowupTask.id)
        .where(FollowupTask.scheduled_date <= today)
    )).scalar_one()

    done_checkins = (await db.execute(
        select(func.count()).select_from(CheckIn)
        .join(FollowupTask, CheckIn.task_id == FollowupTask.id)
        .where(
            FollowupTask.scheduled_date <= today,
            CheckIn.status == "DONE",
        )
    )).scalar_one()

    followup_completion_rate = (
        round(done_checkins / total_due_checkins, 4) if total_due_checkins > 0 else 0.0
    )

    # 高风险患者（OPEN + HIGH 预警）
    high_risk_patients = (await db.execute(
        select(func.count(distinct(AlertEvent.user_id))).select_from(AlertEvent).where(
            AlertEvent.severity == "HIGH",
            AlertEvent.status == "OPEN",
        )
    )).scalar_one()

    # 本月AI自动预警触发数
    auto_alerts_this_month = (await db.execute(
        select(func.count()).select_from(AlertEvent).where(
            AlertEvent.created_at >= start_of_month,
        )
    )).scalar_one()

    # 本月未复诊提醒发送数
    no_visit_sent = (await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.notif_type == "SYSTEM",
            Notification.title.like("%复诊%"),
            Notification.created_at >= start_of_month,
        )
    )).scalar_one()

    # 疾病类型统计
    disease_rows = (await db.execute(
        select(ChronicDiseaseRecord.disease_type, func.count().label("cnt"))
        .group_by(ChronicDiseaseRecord.disease_type)
    )).all()
    disease_stats = {r.disease_type: r.cnt for r in disease_rows}

    return ok({
        "total_archives": total_archives,
        "plans_issued_this_month": plans_this_month,
        "plans_issued_total": plans_total,
        "return_visit_conversion_rate": return_visit_rate,
        "consultations_this_month": consultations_this_month,
        "consultation_revenue_estimate": consultation_revenue,
        "followup_completion_rate": followup_completion_rate,
        "high_risk_patients": high_risk_patients,
        "auto_alerts_this_month": auto_alerts_this_month,
        "no_visit_reminder_sent": no_visit_sent,
        "disease_stats": disease_stats,
    })


@router.get("/business/trend")
async def get_business_trend(
    months: int = 6,
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
):
    """近N个月趋势数据（方案下达/咨询量/预警触发）"""
    _require_auth(access_token)
    if months < 1 or months > 24:
        months = 6

    now = datetime.now(timezone.utc)
    labels = []
    plans_data = []
    consult_data = []
    alerts_data = []

    for i in range(months - 1, -1, -1):
        # 计算目标月份
        target = now - timedelta(days=30 * i)
        y, m = target.year, target.month
        start, end = _month_range(y, m)
        label = f"{y}-{m:02d}"
        labels.append(label)

        # 方案下达数
        p = (await db.execute(
            select(func.count()).select_from(Notification).where(
                Notification.notif_type == "PLAN_ISSUED",
                Notification.created_at >= start,
                Notification.created_at <= end,
            )
        )).scalar_one()
        plans_data.append(p)

        # 咨询数
        c = (await db.execute(
            select(func.count()).select_from(Consultation).where(
                Consultation.created_at >= start,
                Consultation.created_at <= end,
            )
        )).scalar_one()
        consult_data.append(c)

        # 预警触发数
        a = (await db.execute(
            select(func.count()).select_from(AlertEvent).where(
                AlertEvent.created_at >= start,
                AlertEvent.created_at <= end,
            )
        )).scalar_one()
        alerts_data.append(a)

    return ok({
        "labels": labels,
        "plans_issued": plans_data,
        "consultations": consult_data,
        "alerts_triggered": alerts_data,
    })
