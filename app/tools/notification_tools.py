"""
患者通知 API
prefix: /notifications

患者端调用，通过 archive_id Cookie 识别患者身份（简化实现）。
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.archive import PatientArchive
from app.models.notification import Notification
from app.services.notification_service import (
    get_list,
    get_unread_count,
    mark_all_read,
    mark_read,
)
from app.tools.response import fail, ok

router = APIRouter(prefix="/notifications", tags=["notifications"])


async def _resolve_archive(db: AsyncSession, current_user) -> PatientArchive | None:
    """通过当前登录用户找到对应患者档案"""
    result = await db.execute(
        select(PatientArchive).where(PatientArchive.user_id == current_user.id)
    )
    return result.scalar_one_or_none()


@router.get("/mine")
async def my_notifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, le=50),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(get_current_user),
):
    """患者查看自己的通知列表"""
    archive = await _resolve_archive(db, current_user)
    if not archive:
        return ok({"total": 0, "items": []})

    items, total = await get_list(db, archive.id, page=page, page_size=page_size)
    return ok({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_notif_dict(n) for n in items],
    })


@router.get("/count")
async def unread_count(
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(get_current_user),
):
    """未读通知数量（前端轮询用）"""
    archive = await _resolve_archive(db, current_user)
    if not archive:
        return ok({"unread": 0})
    count = await get_unread_count(db, archive.id)
    return ok({"unread": count})


@router.post("/{notif_id}/read")
async def read_one(
    notif_id: str = Path(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(get_current_user),
):
    """标记单条通知为已读"""
    archive = await _resolve_archive(db, current_user)
    if not archive:
        return fail("NOT_FOUND", "未找到患者档案", status_code=404)
    try:
        nid = uuid.UUID(notif_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "notif_id 格式无效")

    success = await mark_read(db, nid, archive.id)
    if not success:
        return fail("NOT_FOUND", "通知不存在", status_code=404)
    await db.commit()
    return ok({"notif_id": notif_id, "status": "READ"})


@router.post("/read-all")
async def read_all(
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(get_current_user),
):
    """全部标记已读"""
    archive = await _resolve_archive(db, current_user)
    if not archive:
        return ok({"updated": 0})
    count = await mark_all_read(db, archive.id)
    await db.commit()
    return ok({"updated": count})


def _notif_dict(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "title": n.title,
        "content": n.content,
        "notif_type": n.notif_type,
        "status": n.status,
        "action_url": n.action_url,
        "created_at": n.created_at.isoformat(),
        "read_at": n.read_at.isoformat() if n.read_at else None,
    }
