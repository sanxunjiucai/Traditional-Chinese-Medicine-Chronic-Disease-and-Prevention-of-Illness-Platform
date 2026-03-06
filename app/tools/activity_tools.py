"""
活动档案 API
GET  /activity-archives/kpi              - 总览 KPI
GET  /activity-archives                  - 活动档案列表（每条 = 一个预警规则 + 覆盖患者数）
GET  /activity-archives/rules            - 规则管理列表
PATCH /activity-archives/rules/{id}/status - 切换规则启用/停用
DELETE /activity-archives/rules/{id}    - 删除规则
GET  /activity-archives/generate-log/kpi - 生成日志 KPI
GET  /activity-archives/generate-log    - 生成日志列表
GET  /activity-archives/{id}            - 活动详情
GET  /activity-archives/{id}/kpi        - 单活动 KPI
GET  /activity-archives/{id}/patients   - 活动覆盖患者列表
GET  /activity-archives/{id}/generate-log - 单活动生成时间轴

以 alert_rules 作为活动规则数据来源，以 alert_events 统计覆盖患者数。
"""
from __future__ import annotations

from datetime import datetime, timezone, date, timedelta
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, status
from sqlalchemy import func, select, distinct, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.alert import AlertRule, AlertEvent
from app.models.archive import PatientArchive
from app.models.user import User
from app.services.auth_service import decode_token
from app.tools.response import ok

router = APIRouter(prefix="/activity-archives", tags=["activity-archives"])


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

_CONDITION_LABELS = {
    "BLOOD_PRESSURE": "血压",
    "BLOOD_GLUCOSE": "血糖",
    "HEART_RATE": "心率",
    "WEIGHT": "体重",
    "OXYGEN": "血氧",
    "TEMPERATURE": "体温",
    "CHOLESTEROL": "血脂",
}

_CYCLE_MAP = {
    "HIGH": "每日",
    "MEDIUM": "每周一",
    "LOW": "每月1日",
}


def _rule_to_activity(rule: AlertRule, patient_count: int, last_gen: str | None = None) -> dict:
    """Convert AlertRule + patient_count to activity dict."""
    cond_parts = []
    for c in (rule.conditions or []):
        field = _CONDITION_LABELS.get(c.get("field", ""), c.get("field", ""))
        op = c.get("op", ">")
        val = c.get("value", "")
        unit = c.get("unit", "")
        cond_parts.append(f"{field} {op} {val}{unit}")
    condition = "；".join(cond_parts) if cond_parts else rule.message_template or rule.name

    cycle = _CYCLE_MAP.get(str(rule.severity.value) if rule.severity else "MEDIUM", "每日")
    status = "ACTIVE" if rule.is_active else "INACTIVE"
    created_str = rule.created_at.strftime("%Y-%m-%d") if rule.created_at else "-"

    if last_gen is None:
        last_gen = datetime.now(timezone.utc).strftime("%Y-%m-%d 06:00")

    return {
        "id": str(rule.id),
        "name": rule.name,
        "rule": condition,
        "condition": condition,
        "cycle": cycle,
        "scope": "全部类型",
        "doctor": "负责医生",
        "status": status,
        "patients": patient_count,
        "last_gen": last_gen,
        "created": created_str,
    }


@router.get("/kpi")
async def get_activity_kpi(
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
):
    """活动档案总览 KPI"""
    _require_auth(access_token)
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    total_rules = (await db.execute(
        select(func.count()).select_from(AlertRule)
    )).scalar_one()

    month_rules = (await db.execute(
        select(func.count()).select_from(AlertRule).where(
            AlertRule.created_at >= month_start
        )
    )).scalar_one()

    active_rules = (await db.execute(
        select(func.count()).select_from(AlertRule).where(AlertRule.is_active.is_(True))
    )).scalar_one()

    total_patients = (await db.execute(
        select(func.count(distinct(AlertEvent.user_id))).select_from(AlertEvent)
    )).scalar_one()

    return ok({
        "total": total_rules,
        "month": month_rules,
        "rules": active_rules,
        "patients": total_patients,
    })


@router.get("")
@router.get("/")
async def list_activities(
    q: str = "",
    status: str = "",
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
):
    """活动档案列表"""
    _require_auth(access_token)
    where = []
    if status == "ACTIVE":
        where.append(AlertRule.is_active.is_(True))
    elif status == "INACTIVE":
        where.append(AlertRule.is_active.is_(False))

    rules = (await db.execute(
        select(AlertRule).where(*where).order_by(AlertRule.created_at.desc())
    )).scalars().all()

    # Count distinct patients per rule
    count_rows = (await db.execute(
        select(AlertEvent.rule_id, func.count(distinct(AlertEvent.user_id)).label("cnt"))
        .group_by(AlertEvent.rule_id)
    )).all()
    patient_map = {str(r.rule_id): r.cnt for r in count_rows}

    # Last event time per rule
    last_rows = (await db.execute(
        select(AlertEvent.rule_id, func.max(AlertEvent.created_at).label("last"))
        .group_by(AlertEvent.rule_id)
    )).all()
    last_map = {str(r.rule_id): r.last for r in last_rows}

    items = []
    for rule in rules:
        rid = str(rule.id)
        if q and q.lower() not in rule.name.lower():
            continue
        cnt = patient_map.get(rid, 0)
        last = last_map.get(rid)
        last_gen = last.strftime("%Y-%m-%d 06:00") if last else datetime.now(timezone.utc).strftime("%Y-%m-%d 06:00")
        items.append(_rule_to_activity(rule, cnt, last_gen))

    return ok({"items": items, "total": len(items), "success": True})


@router.get("/rules")
async def list_rules(
    q: str = "",
    status: str = "",
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
):
    """规则管理列表"""
    _require_auth(access_token)
    where = []
    if status == "ACTIVE":
        where.append(AlertRule.is_active.is_(True))
    elif status == "INACTIVE":
        where.append(AlertRule.is_active.is_(False))

    rules = (await db.execute(
        select(AlertRule).where(*where).order_by(AlertRule.created_at.asc())
    )).scalars().all()

    items = []
    for rule in rules:
        if q and q.lower() not in rule.name.lower():
            continue
        act = _rule_to_activity(rule, 0)
        items.append(act)

    return ok({"items": items, "total": len(items), "success": True})


@router.patch("/rules/{rule_id}/status")
async def toggle_rule_status(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
):
    """切换规则启用/停用"""
    _require_auth(access_token)
    import uuid as _uuid
    try:
        uid = _uuid.UUID(rule_id)
    except ValueError:
        return ok({"message": "操作成功"})

    rule = (await db.execute(
        select(AlertRule).where(AlertRule.id == uid)
    )).scalar_one_or_none()
    if rule:
        rule.is_active = not rule.is_active
        await db.commit()
    return ok({"message": "操作成功", "is_active": rule.is_active if rule else None})


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
):
    """删除规则"""
    _require_auth(access_token)
    import uuid as _uuid
    try:
        uid = _uuid.UUID(rule_id)
    except ValueError:
        return ok({"message": "删除成功"})
    rule = (await db.execute(
        select(AlertRule).where(AlertRule.id == uid)
    )).scalar_one_or_none()
    if rule:
        await db.delete(rule)
        await db.commit()
    return ok({"message": "删除成功"})


@router.get("/generate-log/kpi")
async def get_generate_log_kpi(
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
):
    """生成日志 KPI（用 alert_events 数据模拟）"""
    _require_auth(access_token)
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    month_events = (await db.execute(
        select(func.count()).select_from(AlertEvent).where(
            AlertEvent.created_at >= month_start
        )
    )).scalar_one()

    total_events = (await db.execute(
        select(func.count()).select_from(AlertEvent)
    )).scalar_one()

    return ok({
        "count": month_events,
        "added": total_events,
        "removed": max(0, total_events // 5),
        "failed": 0,
    })


@router.get("/generate-log")
async def get_generate_log(
    page: int = 1,
    page_size: int = 10,
    rule: str = "",
    status: str = "",
    range: str = "week",
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
):
    """生成日志列表（以 alert_events 按天聚合模拟）"""
    _require_auth(access_token)
    now = datetime.now(timezone.utc)
    if range == "week":
        since = now - timedelta(days=7)
    elif range == "month":
        since = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    else:
        since = now - timedelta(days=30)

    # Aggregate events per day per rule
    rows = (await db.execute(
        select(
            AlertEvent.rule_id,
            func.date(AlertEvent.created_at).label("day"),
            func.count().label("cnt"),
        )
        .where(AlertEvent.created_at >= since)
        .group_by(AlertEvent.rule_id, func.date(AlertEvent.created_at))
        .order_by(text("day DESC"))
    )).all()

    # Bulk load rule names
    rule_ids = list({str(r.rule_id) for r in rows})
    rule_name_map: dict[str, str] = {}
    if rule_ids:
        import uuid as _uuid
        rule_objs = (await db.execute(
            select(AlertRule).where(AlertRule.id.in_([_uuid.UUID(i) for i in rule_ids]))
        )).scalars().all()
        rule_name_map = {str(r.id): r.name for r in rule_objs}

    items = []
    for idx, r in enumerate(rows):
        rule_name = rule_name_map.get(str(r.rule_id), "未知规则")
        if rule and rule not in rule_name:
            continue
        day_str = str(r.day) if r.day else str(now.date())
        items.append({
            "id": idx + 1,
            "time": f"{day_str} 06:00:00",
            "rule": rule_name,
            "trigger": "AUTO",
            "added": r.cnt,
            "removed": max(0, r.cnt // 5),
            "duration": f"{round(1.0 + r.cnt * 0.1, 1)}s",
            "status": "SUCCESS",
            "error": None,
        })

    total = len(items)
    offset = (page - 1) * page_size
    page_items = items[offset: offset + page_size]
    return ok({"items": page_items, "total": total})


@router.get("/{activity_id}/kpi")
async def get_activity_detail_kpi(
    activity_id: str,
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
):
    """单个活动详情 KPI"""
    _require_auth(access_token)
    import uuid as _uuid
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    try:
        uid = _uuid.UUID(activity_id)
    except ValueError:
        return ok({"all": 0, "week": 0, "month": 0, "handled": 0})

    total = (await db.execute(
        select(func.count(distinct(AlertEvent.user_id)))
        .where(AlertEvent.rule_id == uid)
    )).scalar_one()

    week_new = (await db.execute(
        select(func.count(distinct(AlertEvent.user_id)))
        .where(AlertEvent.rule_id == uid, AlertEvent.created_at >= week_ago)
    )).scalar_one()

    month_new = (await db.execute(
        select(func.count(distinct(AlertEvent.user_id)))
        .where(AlertEvent.rule_id == uid, AlertEvent.created_at >= month_start)
    )).scalar_one()

    handled = (await db.execute(
        select(func.count())
        .select_from(AlertEvent)
        .where(AlertEvent.rule_id == uid, AlertEvent.status != "OPEN")
    )).scalar_one()

    return ok({"all": total, "week": week_new, "month": month_new, "handled": handled})


@router.get("/{activity_id}/patients")
async def get_activity_patients(
    activity_id: str,
    page: int = 1,
    page_size: int = 10,
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
):
    """活动覆盖患者列表"""
    _require_auth(access_token)
    import uuid as _uuid
    try:
        uid = _uuid.UUID(activity_id)
    except ValueError:
        return ok({"items": [], "total": 0})

    # Distinct user_ids with events for this rule
    user_rows = (await db.execute(
        select(
            AlertEvent.user_id,
            func.min(AlertEvent.created_at).label("joined"),
            func.max(AlertEvent.trigger_value).label("last_val"),
        )
        .where(AlertEvent.rule_id == uid)
        .group_by(AlertEvent.user_id)
        .order_by(func.min(AlertEvent.created_at).desc())
    )).all()

    total = len(user_rows)
    offset = (page - 1) * page_size
    page_rows = user_rows[offset: offset + page_size]

    # Bulk load user + archive info
    user_ids = [r.user_id for r in page_rows]
    archives: dict[str, PatientArchive] = {}
    if user_ids:
        arch_objs = (await db.execute(
            select(PatientArchive).where(PatientArchive.user_id.in_(user_ids))
        )).scalars().all()
        archives = {str(a.user_id): a for a in arch_objs}

    items = []
    for idx, row in enumerate(page_rows):
        arch = archives.get(str(row.user_id))
        name = arch.name if arch else f"患者{idx+1}"
        gender = "男" if (arch and arch.gender == "male") else "女" if (arch and arch.gender == "female") else "-"
        age = "-"
        if arch and arch.birth_date:
            today = date.today()
            age = str(today.year - arch.birth_date.year - (
                1 if (today.month, today.day) < (arch.birth_date.month, arch.birth_date.day) else 0
            ))
        metric = "指标异常"
        if row.last_val and isinstance(row.last_val, dict):
            parts = [f"{k}: {v}" for k, v in list(row.last_val.items())[:2]]
            if parts:
                metric = "；".join(parts)
        joined = row.joined.strftime("%Y-%m-%d") if row.joined else "-"
        archive_id = str(arch.id) if arch else ""
        items.append({
            "id": archive_id,
            "name": name,
            "age": age,
            "gender": gender,
            "metric": metric,
            "joined": joined,
        })

    return ok({"items": items, "total": total})


@router.get("/{activity_id}/generate-log")
async def get_activity_generate_log(
    activity_id: str,
    limit: int = 5,
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
):
    """单活动生成时间轴（最近 N 次）"""
    _require_auth(access_token)
    import uuid as _uuid
    try:
        uid = _uuid.UUID(activity_id)
    except ValueError:
        return ok({"items": []})

    rows = (await db.execute(
        select(
            func.date(AlertEvent.created_at).label("day"),
            func.count().label("cnt"),
        )
        .where(AlertEvent.rule_id == uid)
        .group_by(func.date(AlertEvent.created_at))
        .order_by(text("day DESC"))
        .limit(limit)
    )).all()

    items = []
    for r in rows:
        day_str = str(r.day) if r.day else "-"
        items.append({
            "time": f"{day_str} 06:00",
            "added": r.cnt,
            "removed": max(0, r.cnt // 5),
        })

    return ok({"items": items})


@router.get("/{activity_id}")
async def get_activity_detail(
    activity_id: str,
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(default=None),
):
    """活动详情"""
    _require_auth(access_token)
    import uuid as _uuid
    try:
        uid = _uuid.UUID(activity_id)
    except ValueError:
        return ok(None)

    rule = (await db.execute(
        select(AlertRule).where(AlertRule.id == uid)
    )).scalar_one_or_none()
    if not rule:
        return ok(None)

    patient_count = (await db.execute(
        select(func.count(distinct(AlertEvent.user_id)))
        .where(AlertEvent.rule_id == uid)
    )).scalar_one()

    return ok(_rule_to_activity(rule, patient_count))
