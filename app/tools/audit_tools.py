from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import require_role
from app.models.audit import AuditLog
from app.models.enums import UserRole
from app.tools.response import ok

router = APIRouter(prefix="/audit", tags=["audit-tools"])


@router.get("")
@router.get("/")
async def list_audit_logs(
    user_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    import uuid
    from datetime import datetime, timezone

    filters = []
    if user_id:
        try:
            filters.append(AuditLog.user_id == uuid.UUID(user_id))
        except ValueError:
            pass
    if action:
        filters.append(AuditLog.action == action)
    if from_date:
        try:
            dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            filters.append(AuditLog.created_at >= dt)
        except ValueError:
            pass
    if to_date:
        try:
            from datetime import timedelta
            dt = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            filters.append(AuditLog.created_at < dt)
        except ValueError:
            pass

    where_clause = and_(*filters) if filters else True

    total_result = await db.execute(
        select(func.count()).select_from(AuditLog).where(where_clause)
    )
    total = total_result.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        select(AuditLog)
        .where(where_clause)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    logs = result.scalars().all()

    return ok({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_log_dict(log) for log in logs],
    })


def _log_dict(log: AuditLog) -> dict:
    return {
        "id": str(log.id),
        "action": log.action,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "user_id": str(log.user_id) if log.user_id else None,
        "ip_address": log.ip_address,
        "old_values": log.old_values,
        "new_values": log.new_values,
        "extra": log.extra,
        "created_at": log.created_at.isoformat(),
    }
