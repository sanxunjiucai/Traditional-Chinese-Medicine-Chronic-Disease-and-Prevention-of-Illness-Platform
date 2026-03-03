from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models.content import ContentItem
from app.models.enums import ContentStatus, UserRole
from app.services.audit_service import log_action
from app.tools.response import fail, ok

router = APIRouter(prefix="/content", tags=["content-tools"])


class ContentCreateRequest(BaseModel):
    title: str
    summary: str | None = None
    body: str
    tags: list[str] = []
    cover_url: str | None = None


class ContentUpdateRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    body: str | None = None
    tags: list[str] | None = None


class ReviewRequest(BaseModel):
    review_note: str | None = None


@router.get("/")
async def list_published(
    tags: list[str] | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(get_current_user),
):
    result = await db.execute(
        select(ContentItem)
        .where(ContentItem.status == ContentStatus.PUBLISHED)
        .order_by(ContentItem.published_at.desc())
        .offset(skip)
        .limit(limit)
    )
    items = result.scalars().all()
    return ok([_item_dict(i) for i in items])


@router.get("/admin")
async def list_all_content(
    status: ContentStatus | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    filters = []
    if status:
        filters.append(ContentItem.status == status)
    result = await db.execute(
        select(ContentItem)
        .where(and_(*filters) if filters else True)
        .order_by(ContentItem.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    items = result.scalars().all()
    return ok([_item_dict(i) for i in items])


@router.get("/{content_id}")
async def get_content(
    content_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    import uuid
    item = await _get_item(db, uuid.UUID(content_id))
    if item is None:
        return fail("NOT_FOUND", "内容不存在", status_code=404)
    return ok(_item_dict(item, include_body=True))


@router.post("/")
async def create_content(
    body: ContentCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    item = ContentItem(
        title=body.title,
        summary=body.summary,
        body=body.body,
        tags=body.tags,
        cover_url=body.cover_url,
        author_id=current_user.id,
        status=ContentStatus.DRAFT,
    )
    db.add(item)
    await db.flush()
    await log_action(
        db, action="CREATE_CONTENT", resource_type="ContentItem",
        user_id=current_user.id, resource_id=str(item.id),
        new_values={"title": body.title, "status": "DRAFT"},
    )
    await db.commit()
    return ok({"id": str(item.id), "content_id": str(item.id)}, status_code=201)


@router.patch("/{content_id}")
async def update_content(
    content_id: str,
    body: ContentUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    import uuid
    result = await db.execute(
        select(ContentItem).where(ContentItem.id == uuid.UUID(content_id))
    )
    item = result.scalar_one_or_none()
    if item is None:
        return fail("NOT_FOUND", "内容不存在", status_code=404)
    if item.status not in (ContentStatus.DRAFT, ContentStatus.OFFLINE):
        return fail("STATE_ERROR", "只有草稿/下线状态可编辑", status_code=409)

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(item, field, value)
    db.add(item)
    await db.commit()
    return ok({"content_id": content_id})


@router.patch("/{content_id}/submit-review")
async def submit_review(
    content_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    import uuid
    item = await _get_item(db, uuid.UUID(content_id))
    if item is None:
        return fail("NOT_FOUND", "内容不存在", status_code=404)
    if item.status != ContentStatus.DRAFT:
        return fail("STATE_ERROR", f"当前状态 {item.status.value} 不可提交审核", status_code=409)

    item.status = ContentStatus.PENDING_REVIEW
    db.add(item)
    await log_action(db, action="SUBMIT_REVIEW", resource_type="ContentItem",
                     user_id=current_user.id, resource_id=content_id,
                     old_values={"status": "DRAFT"}, new_values={"status": "PENDING_REVIEW"})
    await db.commit()
    return ok({"content_id": content_id, "status": "PENDING_REVIEW"})


@router.patch("/{content_id}/publish")
async def publish_content(
    content_id: str,
    body: ReviewRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    import uuid
    item = await _get_item(db, uuid.UUID(content_id))
    if item is None:
        return fail("NOT_FOUND", "内容不存在", status_code=404)
    if item.status != ContentStatus.PENDING_REVIEW:
        return fail("STATE_ERROR", f"当前状态 {item.status.value} 不可发布", status_code=409)

    item.status = ContentStatus.PUBLISHED
    item.reviewed_by_id = current_user.id
    item.review_note = body.review_note
    item.published_at = datetime.now(timezone.utc)
    db.add(item)
    await log_action(db, action="PUBLISH_CONTENT", resource_type="ContentItem",
                     user_id=current_user.id, resource_id=content_id,
                     old_values={"status": "PENDING_REVIEW"}, new_values={"status": "PUBLISHED"})
    await db.commit()
    return ok({"content_id": content_id, "status": "PUBLISHED"})


@router.patch("/{content_id}/offline")
async def offline_content(
    content_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(require_role(UserRole.ADMIN)),
):
    import uuid
    item = await _get_item(db, uuid.UUID(content_id))
    if item is None:
        return fail("NOT_FOUND", "内容不存在", status_code=404)
    if item.status != ContentStatus.PUBLISHED:
        return fail("STATE_ERROR", f"当前状态 {item.status.value} 不可下线", status_code=409)

    item.status = ContentStatus.OFFLINE
    item.offline_at = datetime.now(timezone.utc)
    db.add(item)
    await log_action(db, action="OFFLINE_CONTENT", resource_type="ContentItem",
                     user_id=current_user.id, resource_id=content_id,
                     old_values={"status": "PUBLISHED"}, new_values={"status": "OFFLINE"})
    await db.commit()
    return ok({"content_id": content_id, "status": "OFFLINE"})


async def _get_item(db: AsyncSession, item_id) -> ContentItem | None:
    result = await db.execute(select(ContentItem).where(ContentItem.id == item_id))
    return result.scalar_one_or_none()


def _item_dict(i: ContentItem, include_body: bool = False) -> dict:
    d = {
        "id": str(i.id),
        "title": i.title,
        "summary": i.summary,
        "tags": i.tags,
        "status": i.status.value,
        "author_id": str(i.author_id),
        "published_at": i.published_at.isoformat() if i.published_at else None,
        "created_at": i.created_at.isoformat(),
    }
    if include_body:
        d["body"] = i.body
    return d
