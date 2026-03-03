import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def log_action(
    db: AsyncSession,
    action: str,
    resource_type: str,
    user_id: uuid.UUID | str | None = None,
    resource_id: str | None = None,
    old_values: dict | None = None,
    new_values: dict | None = None,
    ip_address: str | None = None,
    extra: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=uuid.UUID(str(user_id)) if user_id else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else None,
        old_values=old_values,
        new_values=new_values,
        ip_address=ip_address,
        extra=extra,
    )
    db.add(entry)
    await db.flush()
    return entry
