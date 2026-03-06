from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models.alert import AlertEvent, AlertRule
from app.models.enums import AlertStatus, UserRole
from app.models.user import User
from app.services.audit_service import log_action
from app.tools.response import fail, ok

router = APIRouter(prefix="/alerts", tags=["alert-tools"])


@router.get("/")
async def my_alerts(
    status: AlertStatus | None = Query(default=None),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(get_current_user),
):
    filters = [AlertEvent.user_id == current_user.id]
    if status:
        filters.append(AlertEvent.status == status)
    result = await db.execute(
        select(AlertEvent).where(and_(*filters)).order_by(AlertEvent.created_at.desc())
    )
    events = result.scalars().all()
    return ok([_event_dict(e) for e in events])


@router.get("/admin")
async def all_alerts(
    status: AlertStatus | None = Query(default=None),
    severity: str | None = Query(default=None),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)),
):
    filters = []
    if status:
        filters.append(AlertEvent.status == status)
    if severity:
        from app.models.enums import AlertSeverity
        filters.append(AlertEvent.severity == AlertSeverity(severity))
    result = await db.execute(
        select(AlertEvent).where(and_(*filters) if filters else True).order_by(AlertEvent.created_at.desc())
    )
    events = result.scalars().all()
    items = []
    for e in events:
        d = _event_dict(e)
        user_r = await db.execute(select(User).where(User.id == e.user_id))
        user = user_r.scalar_one_or_none()
        d["user_name"] = user.name if user else None
        d["user_phone"] = user.phone if user else None
        rule_r = await db.execute(select(AlertRule).where(AlertRule.id == e.rule_id))
        rule = rule_r.scalar_one_or_none()
        d["rule_name"] = rule.name if rule else None
        items.append(d)
    return ok(items)


@router.get("/{event_id}")
async def get_alert(
    event_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)),
):
    import uuid
    result = await db.execute(
        select(AlertEvent).where(AlertEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if event is None:
        return fail("NOT_FOUND", "预警事件不存在", status_code=404)
    d = _event_dict(event)
    user_r = await db.execute(select(User).where(User.id == event.user_id))
    user = user_r.scalar_one_or_none()
    d["user_name"] = user.name if user else None
    d["user_phone"] = user.phone if user else None
    rule_r = await db.execute(select(AlertRule).where(AlertRule.id == event.rule_id))
    rule = rule_r.scalar_one_or_none()
    d["rule_name"] = rule.name if rule else None
    return ok(d)


class AckRequest(BaseModel):
    handler_note: str | None = None


class CloseRequest(BaseModel):
    handler_note: str | None = None


@router.patch("/{event_id}/ack")
async def ack_alert(
    event_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)),
    body: AckRequest | None = None,
):
    import uuid
    result = await db.execute(
        select(AlertEvent).where(AlertEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if event is None:
        return fail("NOT_FOUND", "预警事件不存在", status_code=404)
    if event.status != AlertStatus.OPEN:
        return fail("STATE_ERROR", f"预警状态为 {event.status.value}，无法确认", status_code=409)

    event.status = AlertStatus.ACKED
    if body and body.handler_note:
        event.handler_note = body.handler_note
    event.handled_by_id = current_user.id
    event.acked_at = datetime.now(timezone.utc)
    db.add(event)

    await log_action(
        db, action="ACK_ALERT", resource_type="AlertEvent",
        user_id=current_user.id, resource_id=str(event.id),
        old_values={"status": "OPEN"}, new_values={"status": "ACKED"},
    )
    await db.commit()
    return ok({"event_id": str(event.id), "status": "ACKED"})


@router.patch("/{event_id}/close")
async def close_alert(
    event_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)),
    body: CloseRequest | None = None,
):
    import uuid
    result = await db.execute(
        select(AlertEvent).where(AlertEvent.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if event is None:
        return fail("NOT_FOUND", "预警事件不存在", status_code=404)
    if event.status not in (AlertStatus.OPEN, AlertStatus.ACKED):
        return fail("STATE_ERROR", f"预警状态为 {event.status.value}，无法关闭", status_code=409)

    event.status = AlertStatus.CLOSED
    event.handler_note = body.handler_note if body else None
    event.handled_by_id = current_user.id
    event.closed_at = datetime.now(timezone.utc)
    db.add(event)

    await log_action(
        db, action="CLOSE_ALERT", resource_type="AlertEvent",
        user_id=current_user.id, resource_id=str(event.id),
        old_values={"status": event.status.value}, new_values={"status": "CLOSED"},
    )
    await db.commit()
    return ok({"event_id": str(event.id), "status": "CLOSED"})


def _event_dict(e: AlertEvent) -> dict:
    return {
        "id": str(e.id),
        "user_id": str(e.user_id),
        "rule_id": str(e.rule_id),
        "severity": e.severity.value,
        "status": e.status.value,
        "message": e.message,
        "trigger_value": e.trigger_value,
        "handler_note": e.handler_note,
        "acked_at": e.acked_at.isoformat() if e.acked_at else None,
        "closed_at": e.closed_at.isoformat() if e.closed_at else None,
        "created_at": e.created_at.isoformat(),
    }
