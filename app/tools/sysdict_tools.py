"""
数据字典、版本管理、授权管理、登录日志、短信日志 API
"""
import uuid
from datetime import datetime, UTC
from typing import Any

from fastapi import APIRouter, Body, Cookie, Query
from sqlalchemy import select, func

from app.database import AsyncSessionLocal
from app.models.sysdict import DictGroup, DictItem, SystemVersion, AuthLicense, LoginLog, SmsLog
from app.models.enums import DictStatus
from app.services.auth_service import decode_token
from app.tools.response import ok, fail as err

router = APIRouter(prefix="/sysdict", tags=["sysdict"])


def _auth(access_token: str | None, admin_only: bool = False) -> dict | None:
    if not access_token:
        return None
    payload = decode_token(access_token)
    if payload is None:
        return None
    role = payload.get("role")
    if admin_only and role != "ADMIN":
        return None
    if role not in ("ADMIN", "PROFESSIONAL"):
        return None
    return payload


# ── 数据字典分组 ──────────────────────────────────────────────────────
@router.get("/groups")
async def list_groups(access_token: str | None = Cookie(default=None)):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录")
    async with AsyncSessionLocal() as sess:
        rows = (await sess.execute(
            select(DictGroup).order_by(DictGroup.sort_order, DictGroup.created_at)
        )).scalars().all()
        items = [{
            "id": str(r.id), "code": r.code, "name": r.name,
            "description": r.description, "is_active": r.is_active,
        } for r in rows]
        return ok({"items": items})


@router.post("/groups")
async def create_group(body: dict, access_token: str | None = Cookie(default=None)):
    if not _auth(access_token, admin_only=True):
        return err("UNAUTHORIZED", "需要管理员权限")
    async with AsyncSessionLocal() as sess:
        record = DictGroup(
            code=body.get("code", "").strip(),
            name=body.get("name", "").strip(),
            description=body.get("description"),
        )
        sess.add(record)
        await sess.commit()
        await sess.refresh(record)
        return ok({"id": str(record.id)})


@router.patch("/groups/{group_id}")
async def update_group(group_id: str, body: dict, access_token: str | None = Cookie(default=None)):
    if not _auth(access_token, admin_only=True):
        return err("UNAUTHORIZED", "需要管理员权限")
    async with AsyncSessionLocal() as sess:
        row = await sess.get(DictGroup, _puuid(group_id))
        if not row:
            return err("NOT_FOUND", "分组不存在")
        for f in ["code", "name", "description", "is_active"]:
            if f in body:
                setattr(row, f, body[f])
        await sess.commit()
        return ok({"id": group_id})


# ── 字典条目 ──────────────────────────────────────────────────────────
@router.get("/groups/{group_id}/items")
async def list_items(group_id: str, access_token: str | None = Cookie(default=None)):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录")
    async with AsyncSessionLocal() as sess:
        rows = (await sess.execute(
            select(DictItem)
            .where(DictItem.group_id == _puuid(group_id))
            .order_by(DictItem.sort_order, DictItem.created_at)
        )).scalars().all()
        items = [{
            "id": str(r.id), "item_code": r.item_code, "item_name": r.item_name,
            "item_value": r.item_value, "external_code": r.external_code,
            "sort_order": r.sort_order, "status": r.status, "notes": r.notes,
        } for r in rows]
        return ok({"items": items})


@router.post("/groups/{group_id}/items")
async def create_item(group_id: str, body: dict, access_token: str | None = Cookie(default=None)):
    if not _auth(access_token, admin_only=True):
        return err("UNAUTHORIZED", "需要管理员权限")
    async with AsyncSessionLocal() as sess:
        record = DictItem(
            group_id=_puuid(group_id),
            item_code=body.get("item_code", "").strip(),
            item_name=body.get("item_name", "").strip(),
            item_value=body.get("item_value"),
            external_code=body.get("external_code"),
            sort_order=body.get("sort_order", 0),
            notes=body.get("notes"),
        )
        sess.add(record)
        await sess.commit()
        await sess.refresh(record)
        return ok({"id": str(record.id)})


@router.patch("/items/{item_id}")
async def update_item(item_id: str, body: dict, access_token: str | None = Cookie(default=None)):
    if not _auth(access_token, admin_only=True):
        return err("UNAUTHORIZED", "需要管理员权限")
    async with AsyncSessionLocal() as sess:
        row = await sess.get(DictItem, _puuid(item_id))
        if not row:
            return err("NOT_FOUND", "条目不存在")
        for f in ["item_code", "item_name", "item_value", "external_code", "sort_order", "status", "notes"]:
            if f in body:
                setattr(row, f, body[f])
        await sess.commit()
        return ok({"id": item_id})


@router.delete("/items/{item_id}")
async def delete_item(item_id: str, access_token: str | None = Cookie(default=None)):
    if not _auth(access_token, admin_only=True):
        return err("UNAUTHORIZED", "需要管理员权限")
    async with AsyncSessionLocal() as sess:
        row = await sess.get(DictItem, _puuid(item_id))
        if not row:
            return err("NOT_FOUND", "条目不存在")
        await sess.delete(row)
        await sess.commit()
        return ok({"deleted": True})


# ── 版本管理 ──────────────────────────────────────────────────────────
@router.get("/versions")
async def list_versions(access_token: str | None = Cookie(default=None)):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录")
    async with AsyncSessionLocal() as sess:
        rows = (await sess.execute(
            select(SystemVersion).order_by(SystemVersion.released_at.desc())
        )).scalars().all()
        items = [{
            "id": str(r.id), "version_no": r.version_no, "release_notes": r.release_notes,
            "is_current": r.is_current,
            "released_at": r.released_at.isoformat() if r.released_at else None,
        } for r in rows]
        return ok({"items": items})


@router.post("/versions")
async def create_version(body: dict, access_token: str | None = Cookie(default=None)):
    payload = _auth(access_token, admin_only=True)
    if not payload:
        return err("UNAUTHORIZED", "需要管理员权限")
    async with AsyncSessionLocal() as sess:
        # 先将其他版本设为非当前版本
        all_versions = (await sess.execute(select(SystemVersion))).scalars().all()
        for v in all_versions:
            v.is_current = False
        record = SystemVersion(
            version_no=body.get("version_no", "").strip(),
            release_notes=body.get("release_notes"),
            is_current=True,
            released_by=_puuid(payload.get("sub")),
            released_at=datetime.now(UTC),
        )
        sess.add(record)
        await sess.commit()
        await sess.refresh(record)
        return ok({"id": str(record.id)})


# ── 授权管理 ──────────────────────────────────────────────────────────
@router.get("/licenses")
async def list_licenses(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token, admin_only=True):
        return err("UNAUTHORIZED", "需要管理员权限")
    async with AsyncSessionLocal() as sess:
        stmt = select(AuthLicense).order_by(AuthLicense.created_at.desc())
        total = await sess.scalar(select(func.count()).select_from(stmt.subquery()))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await sess.execute(stmt)).scalars().all()
        items = [{
            "id": str(r.id), "user_id": str(r.user_id), "license_type": r.license_type,
            "expire_at": r.expire_at.isoformat() if r.expire_at else None,
            "is_active": r.is_active, "notes": r.notes,
        } for r in rows]
        return ok({"total": total, "items": items})


# ── 登录日志 ──────────────────────────────────────────────────────────
@router.get("/login-logs")
async def list_login_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token, admin_only=True):
        return err("UNAUTHORIZED", "需要管理员权限")
    async with AsyncSessionLocal() as sess:
        stmt = select(LoginLog)
        if status:
            stmt = stmt.where(LoginLog.status == status)
        stmt = stmt.order_by(LoginLog.created_at.desc())
        total = await sess.scalar(select(func.count()).select_from(stmt.subquery()))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await sess.execute(stmt)).scalars().all()
        items = [{
            "id": str(r.id), "username": r.username, "ip_address": r.ip_address,
            "status": r.status, "fail_reason": r.fail_reason,
            "created_at": r.created_at.isoformat(),
        } for r in rows]
        return ok({"total": total, "items": items})


# ── 短信日志 ──────────────────────────────────────────────────────────
@router.get("/sms-logs")
async def list_sms_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录")
    async with AsyncSessionLocal() as sess:
        stmt = select(SmsLog)
        if status:
            stmt = stmt.where(SmsLog.status == status)
        stmt = stmt.order_by(SmsLog.created_at.desc())
        total = await sess.scalar(select(func.count()).select_from(stmt.subquery()))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await sess.execute(stmt)).scalars().all()
        items = [{
            "id": str(r.id), "phone": r.phone, "sms_type": r.sms_type,
            "status": r.status, "retry_count": r.retry_count,
            "error_msg": r.error_msg, "created_at": r.created_at.isoformat(),
        } for r in rows]
        return ok({"total": total, "items": items})


# ── helper ──────────────────────────────────────────────────────────
def _puuid(v: Any) -> uuid.UUID | None:
    if not v:
        return None
    try:
        return uuid.UUID(str(v))
    except ValueError:
        return None
