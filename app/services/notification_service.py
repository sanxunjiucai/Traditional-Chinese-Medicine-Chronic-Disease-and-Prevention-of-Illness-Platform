"""
患者通知服务 - 向患者档案推送系统消息
演示模式：通知写入数据库，不发短信/App推送
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


async def push_to_patient(
    db: AsyncSession,
    archive_id: uuid.UUID,
    title: str,
    content: str,
    notif_type: str = "SYSTEM",
    action_url: str | None = None,
    sender_id: uuid.UUID | None = None,
) -> Notification:
    """创建一条患者通知（写库，演示模式不发推送）"""
    notif = Notification(
        archive_id=archive_id,
        sender_id=sender_id,
        title=title,
        content=content,
        notif_type=notif_type,
        status="UNREAD",
        action_url=action_url,
    )
    db.add(notif)
    await db.flush()
    return notif


async def mark_read(
    db: AsyncSession,
    notif_id: uuid.UUID,
    archive_id: uuid.UUID,
) -> bool:
    """标记单条通知为已读，验证归属"""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notif_id,
            Notification.archive_id == archive_id,
        )
    )
    notif = result.scalar_one_or_none()
    if not notif:
        return False
    if notif.status == "UNREAD":
        notif.status = "READ"
        notif.read_at = datetime.now(timezone.utc)
        db.add(notif)
    return True


async def mark_all_read(db: AsyncSession, archive_id: uuid.UUID) -> int:
    """标记该患者所有未读通知为已读，返回更新数量"""
    result = await db.execute(
        select(Notification).where(
            Notification.archive_id == archive_id,
            Notification.status == "UNREAD",
        )
    )
    notifs = result.scalars().all()
    now = datetime.now(timezone.utc)
    for n in notifs:
        n.status = "READ"
        n.read_at = now
        db.add(n)
    return len(notifs)


async def get_unread_count(db: AsyncSession, archive_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.archive_id == archive_id,
            Notification.status == "UNREAD",
        )
    )
    return result.scalar_one()


async def get_list(
    db: AsyncSession,
    archive_id: uuid.UUID,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Notification], int]:
    """返回通知列表和总数"""
    total_r = await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.archive_id == archive_id
        )
    )
    total = total_r.scalar_one()

    result = await db.execute(
        select(Notification)
        .where(Notification.archive_id == archive_id)
        .order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = result.scalars().all()
    return list(items), total
