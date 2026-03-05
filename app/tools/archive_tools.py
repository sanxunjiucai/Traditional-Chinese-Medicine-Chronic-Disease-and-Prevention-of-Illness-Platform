"""
档案管理 API
GET/POST/PATCH/DELETE /tools/archive/archives
GET/PATCH/DELETE /tools/archive/archives/{id}
GET /tools/archive/recycle  回收站
POST /tools/archive/archives/{id}/restore  恢复
GET/POST /tools/archive/families  家庭档案
GET /tools/archive/export  导出CSV
"""
import csv
import io
import uuid
from datetime import datetime, date, UTC
from typing import Any

from fastapi import APIRouter, Cookie, Query, Body
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, or_, and_, cast, Integer, extract, text
from sqlalchemy.sql.expression import func as sqlfunc

from app.database import AsyncSessionLocal
from app.models.archive import PatientArchive, FamilyArchive, ArchiveFamilyMember, ArchiveTransfer
from app.models.user import User
from app.models.org import Organization
from app.models.enums import ArchiveType, IdType
from app.services.auth_service import decode_token
from app.tools.response import ok, fail as err

router = APIRouter(prefix="/archive", tags=["archive"])


def _auth(access_token: str | None) -> dict | None:
    if not access_token:
        return None
    payload = decode_token(access_token)
    if payload is None:
        return None
    if payload.get("role") not in ("ADMIN", "PROFESSIONAL"):
        return None
    return payload


# ── 档案列表 ──────────────────────────────────────────────────────────
@router.get("/archives")
async def list_archives(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    archive_type: str | None = None,
    gender: str | None = None,
    org_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    birth_year_from: int | None = None,
    birth_year_to: int | None = None,
    tag: str | None = None,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    async with AsyncSessionLocal() as sess:
        stmt = select(PatientArchive).where(PatientArchive.is_deleted == False)
        if q:
            stmt = stmt.where(or_(
                PatientArchive.name.ilike(f"%{q}%"),
                PatientArchive.phone.ilike(f"%{q}%"),
                PatientArchive.id_number.ilike(f"%{q}%"),
            ))
        if archive_type:
            stmt = stmt.where(PatientArchive.archive_type == archive_type)
        if gender:
            stmt = stmt.where(PatientArchive.gender == gender)
        if org_id:
            try:
                stmt = stmt.where(PatientArchive.org_id == uuid.UUID(org_id))
            except ValueError:
                pass
        if date_from:
            try:
                stmt = stmt.where(PatientArchive.created_at >= datetime.fromisoformat(date_from))
            except ValueError:
                pass
        if date_to:
            try:
                dt = datetime.fromisoformat(date_to)
                # 包含当天结束
                from datetime import timedelta
                stmt = stmt.where(PatientArchive.created_at < dt + timedelta(days=1))
            except ValueError:
                pass
        if birth_year_from:
            stmt = stmt.where(func.strftime('%Y', PatientArchive.birth_date).cast(Integer) >= birth_year_from)
        if birth_year_to:
            stmt = stmt.where(func.strftime('%Y', PatientArchive.birth_date).cast(Integer) <= birth_year_to)
        if tag:
            # tags 字段存储为 JSON 列表，用 JSON_EACH 或字符串包含匹配
            stmt = stmt.where(PatientArchive.tags.contains(tag))

        total = await sess.scalar(select(func.count()).select_from(stmt.subquery()))
        stmt = stmt.order_by(PatientArchive.created_at.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await sess.execute(stmt)).scalars().all()

        items = []
        for r in rows:
            items.append({
                "id": str(r.id),
                "name": r.name,
                "gender": r.gender,
                "birth_date": r.birth_date.isoformat() if r.birth_date else None,
                "id_type": r.id_type,
                "id_number": _mask_id(r.id_number),
                "phone": _mask_phone(r.phone),
                "archive_type": r.archive_type,
                "district": r.district,
                "tags": r.tags or [],
                "created_at": r.created_at.isoformat(),
            })
        return ok({"total": total, "items": items, "page": page, "page_size": page_size})


def _mask_id(v: str | None) -> str | None:
    if not v or len(v) < 8:
        return v
    return v[:4] + "****" + v[-4:]


def _mask_phone(v: str | None) -> str | None:
    if not v or len(v) < 7:
        return v
    return v[:3] + "****" + v[-4:]


# ── 档案详情 ──────────────────────────────────────────────────────────
@router.get("/archives/{archive_id}")
async def get_archive(
    archive_id: str,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    async with AsyncSessionLocal() as sess:
        try:
            aid = uuid.UUID(archive_id)
        except ValueError:
            return err("INVALID_ID", "无效ID")
        row = await sess.get(PatientArchive, aid)
        if not row:
            return err("NOT_FOUND", "档案不存在", status_code=404)
        return ok(_archive_detail(row))


def _archive_detail(r: PatientArchive) -> dict:
    return {
        "id": str(r.id),
        "user_id": str(r.user_id) if r.user_id else None,
        "name": r.name,
        "gender": r.gender,
        "birth_date": r.birth_date.isoformat() if r.birth_date else None,
        "ethnicity": r.ethnicity,
        "occupation": r.occupation,
        "id_type": r.id_type,
        "id_number": r.id_number,
        "phone": r.phone,
        "phone2": r.phone2,
        "email": r.email,
        "province": r.province,
        "city": r.city,
        "district": r.district,
        "address": r.address,
        "emergency_contact_name": r.emergency_contact_name,
        "emergency_contact_phone": r.emergency_contact_phone,
        "emergency_contact_relation": r.emergency_contact_relation,
        "org_id": str(r.org_id) if r.org_id else None,
        "responsible_doctor_id": str(r.responsible_doctor_id) if r.responsible_doctor_id else None,
        "archive_type": r.archive_type,
        "tags": r.tags or [],
        "past_history": r.past_history,
        "family_history": r.family_history,
        "allergy_history": r.allergy_history,
        "notes": r.notes,
        "is_deleted": r.is_deleted,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


# ── 新增档案 ──────────────────────────────────────────────────────────
@router.post("/archives")
async def create_archive(
    body: dict,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    name = (body.get("name") or "").strip()
    if not name:
        return err("MISSING_FIELD", "姓名不能为空")

    async with AsyncSessionLocal() as sess:
        record = PatientArchive(
            name=name,
            gender=body.get("gender"),
            birth_date=_parse_date(body.get("birth_date")),
            ethnicity=body.get("ethnicity", "汉族"),
            occupation=body.get("occupation"),
            id_type=body.get("id_type", IdType.ID_CARD),
            id_number=body.get("id_number"),
            phone=body.get("phone"),
            phone2=body.get("phone2"),
            email=body.get("email"),
            province=body.get("province"),
            city=body.get("city"),
            district=body.get("district"),
            address=body.get("address"),
            emergency_contact_name=body.get("emergency_contact_name"),
            emergency_contact_phone=body.get("emergency_contact_phone"),
            emergency_contact_relation=body.get("emergency_contact_relation"),
            org_id=_parse_uuid(body.get("org_id")),
            responsible_doctor_id=_parse_uuid(body.get("responsible_doctor_id")),
            archive_type=body.get("archive_type", ArchiveType.NORMAL),
            tags=body.get("tags", []),
            past_history=body.get("past_history"),
            family_history=body.get("family_history"),
            allergy_history=body.get("allergy_history"),
            notes=body.get("notes"),
        )
        sess.add(record)
        await sess.commit()
        await sess.refresh(record)
        return ok({"id": str(record.id)})


# ── 编辑档案 ──────────────────────────────────────────────────────────
@router.patch("/archives/{archive_id}")
async def update_archive(
    archive_id: str,
    body: dict,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    async with AsyncSessionLocal() as sess:
        row = await sess.get(PatientArchive, _parse_uuid(archive_id))
        if not row:
            return err("NOT_FOUND", "档案不存在", status_code=404)
        fields = [
            "name", "gender", "ethnicity", "occupation", "id_type", "id_number",
            "phone", "phone2", "email", "province", "city", "district", "address",
            "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation",
            "archive_type", "tags", "past_history", "family_history", "allergy_history", "notes",
        ]
        for f in fields:
            if f in body:
                setattr(row, f, body[f])
        if "birth_date" in body:
            row.birth_date = _parse_date(body["birth_date"])
        if "org_id" in body:
            row.org_id = _parse_uuid(body["org_id"])
        if "responsible_doctor_id" in body:
            row.responsible_doctor_id = _parse_uuid(body["responsible_doctor_id"])
        await sess.commit()
        return ok({"id": str(row.id)})


# ── 批量软删除 ────────────────────────────────────────────────────────
@router.post("/archives/batch-delete")
async def batch_delete_archives(
    body: dict,
    access_token: str | None = Cookie(default=None),
):
    payload = _auth(access_token)
    if not payload:
        return err("UNAUTHORIZED", "未登录", status_code=401)
    ids = body.get("ids", [])
    if not ids:
        return err("VALIDATION_ERROR", "ids 不能为空")
    async with AsyncSessionLocal() as sess:
        deleted = 0
        for raw_id in ids:
            try:
                aid = uuid.UUID(raw_id)
            except ValueError:
                continue
            row = await sess.get(PatientArchive, aid)
            if row and not row.is_deleted:
                row.is_deleted = True
                row.deleted_at = datetime.now(UTC)
                row.deleted_by = _parse_uuid(payload.get("sub"))
                deleted += 1
        await sess.commit()
    return ok({"deleted": deleted})


# ── 批量更新责任医生 ──────────────────────────────────────────────────
@router.post("/archives/batch-assign-doctor")
async def batch_assign_doctor(
    body: dict,
    access_token: str | None = Cookie(default=None),
):
    payload = _auth(access_token)
    if not payload:
        return err("UNAUTHORIZED", "未登录", status_code=401)
    ids = body.get("ids", [])
    doctor_id = body.get("doctor_id")
    if not ids or not doctor_id:
        return err("VALIDATION_ERROR", "ids 和 doctor_id 不能为空")
    doc_uuid = _parse_uuid(doctor_id)
    async with AsyncSessionLocal() as sess:
        updated = 0
        for raw_id in ids:
            try:
                aid = uuid.UUID(raw_id)
            except ValueError:
                continue
            row = await sess.get(PatientArchive, aid)
            if row and not row.is_deleted:
                row.responsible_doctor_id = doc_uuid
                updated += 1
        await sess.commit()
    return ok({"updated": updated})


# ── 批量更新管辖机构 ──────────────────────────────────────────────────
@router.post("/archives/batch-assign-org")
async def batch_assign_org(
    body: dict,
    access_token: str | None = Cookie(default=None),
):
    payload = _auth(access_token)
    if not payload:
        return err("UNAUTHORIZED", "未登录", status_code=401)
    ids = body.get("ids", [])
    org_id = body.get("org_id")
    if not ids or not org_id:
        return err("VALIDATION_ERROR", "ids 和 org_id 不能为空")
    org_uuid = _parse_uuid(org_id)
    async with AsyncSessionLocal() as sess:
        updated = 0
        for raw_id in ids:
            try:
                aid = uuid.UUID(raw_id)
            except ValueError:
                continue
            row = await sess.get(PatientArchive, aid)
            if row and not row.is_deleted:
                row.org_id = org_uuid
                updated += 1
        await sess.commit()
    return ok({"updated": updated})


# ── 软删除（移入回收站）──────────────────────────────────────────────
@router.delete("/archives/{archive_id}")
async def delete_archive(
    archive_id: str,
    access_token: str | None = Cookie(default=None),
):
    payload = _auth(access_token)
    if not payload:
        return err("UNAUTHORIZED", "未登录", status_code=401)
    async with AsyncSessionLocal() as sess:
        row = await sess.get(PatientArchive, _parse_uuid(archive_id))
        if not row:
            return err("NOT_FOUND", "档案不存在", status_code=404)
        row.is_deleted = True
        row.deleted_at = datetime.now(UTC)
        row.deleted_by = _parse_uuid(payload.get("sub"))
        await sess.commit()
        return ok({"deleted": True})


# ── 回收站列表 ────────────────────────────────────────────────────────
@router.get("/recycle")
async def list_recycle(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    deleted_from: str | None = None,
    deleted_to: str | None = None,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    async with AsyncSessionLocal() as sess:
        stmt = select(PatientArchive).where(PatientArchive.is_deleted == True)
        if deleted_from:
            try:
                stmt = stmt.where(PatientArchive.deleted_at >= datetime.fromisoformat(deleted_from))
            except ValueError:
                pass
        if deleted_to:
            try:
                from datetime import timedelta
                dt = datetime.fromisoformat(deleted_to)
                stmt = stmt.where(PatientArchive.deleted_at < dt + timedelta(days=1))
            except ValueError:
                pass
        total = await sess.scalar(select(func.count()).select_from(stmt.subquery()))
        stmt = stmt.order_by(PatientArchive.deleted_at.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await sess.execute(stmt)).scalars().all()
        items = [{
            "id": str(r.id), "name": r.name, "gender": r.gender,
            "phone": _mask_phone(r.phone), "archive_type": r.archive_type,
            "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None,
        } for r in rows]
        return ok({"total": total, "items": items})


# ── 恢复档案 ──────────────────────────────────────────────────────────
@router.post("/archives/{archive_id}/restore")
async def restore_archive(
    archive_id: str,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    async with AsyncSessionLocal() as sess:
        row = await sess.get(PatientArchive, _parse_uuid(archive_id))
        if not row or not row.is_deleted:
            return err("NOT_FOUND", "档案不在回收站", status_code=404)
        row.is_deleted = False
        row.deleted_at = None
        row.deleted_by = None
        await sess.commit()
        return ok({"restored": True})


# ── 家庭档案 ──────────────────────────────────────────────────────────
@router.get("/families")
async def list_families(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    access_token: str | None = Cookie(default=None),
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    async with AsyncSessionLocal() as sess:
        stmt = select(FamilyArchive)
        if q:
            stmt = stmt.where(or_(
                FamilyArchive.family_name.ilike(f"%{q}%"),
                FamilyArchive.address.ilike(f"%{q}%"),
            ))
        stmt = stmt.order_by(FamilyArchive.created_at.desc())
        total = await sess.scalar(select(func.count()).select_from(stmt.subquery()))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await sess.execute(stmt)).scalars().all()
        items = [{
            "id": str(r.id), "family_name": r.family_name,
            "address": r.address, "member_count": r.member_count,
            "notes": r.notes,
            "created_at": r.created_at.isoformat(),
        } for r in rows]
        return ok({"total": total, "items": items, "page": page, "page_size": page_size})


@router.post("/families")
async def create_family(body: dict, access_token: str | None = Cookie(default=None)):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    async with AsyncSessionLocal() as sess:
        record = FamilyArchive(
            family_name=body.get("family_name", ""),
            address=body.get("address"),
            notes=body.get("notes"),
        )
        sess.add(record)
        await sess.commit()
        await sess.refresh(record)
        return ok({"id": str(record.id)})


@router.get("/families/{family_id}")
async def get_family(family_id: str, access_token: str | None = Cookie(default=None)):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    fid = _parse_uuid(family_id)
    if not fid:
        return err("INVALID_ID", "无效ID")
    async with AsyncSessionLocal() as sess:
        row = await sess.get(FamilyArchive, fid)
        if not row:
            return err("NOT_FOUND", "家庭档案不存在", status_code=404)
        return ok({
            "id": str(row.id), "family_name": row.family_name,
            "address": row.address, "member_count": row.member_count,
            "notes": row.notes,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        })


@router.patch("/families/{family_id}")
async def update_family(
    family_id: str, body: dict, access_token: str | None = Cookie(default=None)
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    fid = _parse_uuid(family_id)
    if not fid:
        return err("INVALID_ID", "无效ID")
    async with AsyncSessionLocal() as sess:
        row = await sess.get(FamilyArchive, fid)
        if not row:
            return err("NOT_FOUND", "家庭档案不存在", status_code=404)
        for f in ["family_name", "address", "notes"]:
            if f in body:
                setattr(row, f, body[f])
        await sess.commit()
        return ok({"id": str(row.id)})


@router.delete("/families/{family_id}")
async def delete_family(family_id: str, access_token: str | None = Cookie(default=None)):
    payload = _auth(access_token)
    if not payload:
        return err("UNAUTHORIZED", "未登录", status_code=401)
    fid = _parse_uuid(family_id)
    if not fid:
        return err("INVALID_ID", "无效ID")
    async with AsyncSessionLocal() as sess:
        row = await sess.get(FamilyArchive, fid)
        if not row:
            return err("NOT_FOUND", "家庭档案不存在", status_code=404)
        members_stmt = select(ArchiveFamilyMember).where(ArchiveFamilyMember.family_id == fid)
        members = (await sess.execute(members_stmt)).scalars().all()
        for m in members:
            await sess.delete(m)
        await sess.delete(row)
        await sess.commit()
        return ok({"deleted": True})


@router.get("/families/{family_id}/members")
async def list_family_members(
    family_id: str, access_token: str | None = Cookie(default=None)
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    fid = _parse_uuid(family_id)
    if not fid:
        return err("INVALID_ID", "无效ID")
    async with AsyncSessionLocal() as sess:
        stmt = select(ArchiveFamilyMember).where(ArchiveFamilyMember.family_id == fid)
        rows = (await sess.execute(stmt)).scalars().all()
        items = []
        for r in rows:
            archive = await sess.get(PatientArchive, r.archive_id)
            if archive and not archive.is_deleted:
                items.append({
                    "id": str(r.id),
                    "archive_id": str(r.archive_id),
                    "name": archive.name,
                    "gender": archive.gender,
                    "birth_date": archive.birth_date.isoformat() if archive.birth_date else None,
                    "relation": r.relation,
                    "notes": r.notes,
                })
        return ok({"items": items, "total": len(items)})


@router.post("/families/{family_id}/members")
async def add_family_member(
    family_id: str, body: dict, access_token: str | None = Cookie(default=None)
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    fid = _parse_uuid(family_id)
    archive_id = _parse_uuid(body.get("archive_id"))
    if not fid or not archive_id:
        return err("VALIDATION_ERROR", "family_id 和 archive_id 不能为空")
    async with AsyncSessionLocal() as sess:
        archive = await sess.get(PatientArchive, archive_id)
        if not archive or archive.is_deleted:
            return err("NOT_FOUND", "档案不存在", status_code=404)
        existing = await sess.scalar(
            select(ArchiveFamilyMember).where(
                ArchiveFamilyMember.family_id == fid,
                ArchiveFamilyMember.archive_id == archive_id,
            )
        )
        if existing:
            return err("DUPLICATE", "该档案已是家庭成员")
        member = ArchiveFamilyMember(
            family_id=fid,
            archive_id=archive_id,
            relation=body.get("relation", "其他"),
            notes=body.get("notes"),
        )
        sess.add(member)
        family = await sess.get(FamilyArchive, fid)
        if family:
            family.member_count = (family.member_count or 0) + 1
        await sess.commit()
        await sess.refresh(member)
        return ok({"id": str(member.id)})


@router.delete("/families/{family_id}/members/{member_id}")
async def remove_family_member(
    family_id: str, member_id: str, access_token: str | None = Cookie(default=None)
):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    mid = _parse_uuid(member_id)
    if not mid:
        return err("INVALID_ID", "无效ID")
    async with AsyncSessionLocal() as sess:
        row = await sess.get(ArchiveFamilyMember, mid)
        if not row:
            return err("NOT_FOUND", "成员关系不存在", status_code=404)
        fid = row.family_id
        await sess.delete(row)
        family = await sess.get(FamilyArchive, fid)
        if family and family.member_count and family.member_count > 0:
            family.member_count -= 1
        await sess.commit()
        return ok({"deleted": True})


# ── 档案统计 ──────────────────────────────────────────────────────────
@router.get("/export")
async def export_archives(
    q: str | None = None,
    archive_type: str | None = None,
    gender: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    birth_year_from: int | None = None,
    birth_year_to: int | None = None,
    tag: str | None = None,
    access_token: str | None = Cookie(default=None),
):
    """导出档案为 CSV 文件（与列表筛选条件一致）"""
    if not _auth(access_token):
        from fastapi.responses import JSONResponse
        return JSONResponse({"success": False, "error": {"code": "UNAUTHORIZED", "message": "未登录"}}, status_code=401)
    async with AsyncSessionLocal() as sess:
        stmt = select(PatientArchive).where(PatientArchive.is_deleted == False)
        if q:
            stmt = stmt.where(or_(
                PatientArchive.name.ilike(f"%{q}%"),
                PatientArchive.phone.ilike(f"%{q}%"),
                PatientArchive.id_number.ilike(f"%{q}%"),
            ))
        if archive_type:
            stmt = stmt.where(PatientArchive.archive_type == archive_type)
        if gender:
            stmt = stmt.where(PatientArchive.gender == gender)
        if date_from:
            try:
                stmt = stmt.where(PatientArchive.created_at >= datetime.fromisoformat(date_from))
            except ValueError:
                pass
        if date_to:
            try:
                from datetime import timedelta
                dt = datetime.fromisoformat(date_to)
                stmt = stmt.where(PatientArchive.created_at < dt + timedelta(days=1))
            except ValueError:
                pass
        if birth_year_from:
            stmt = stmt.where(func.strftime('%Y', PatientArchive.birth_date).cast(Integer) >= birth_year_from)
        if birth_year_to:
            stmt = stmt.where(func.strftime('%Y', PatientArchive.birth_date).cast(Integer) <= birth_year_to)
        if tag:
            stmt = stmt.where(PatientArchive.tags.contains(tag))

        stmt = stmt.order_by(PatientArchive.created_at.desc()).limit(5000)
        rows = (await sess.execute(stmt)).scalars().all()

    TYPE_LABELS = {
        "NORMAL": "普通居民", "CHILD": "0-6岁儿童",
        "FEMALE": "女性档案", "ELDERLY": "老年人(60+)", "KEY_FOCUS": "重点关注"
    }
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["姓名", "性别", "出生日期", "证件号码", "手机号", "地区", "档案类型", "建档时间"])
    for r in rows:
        writer.writerow([
            r.name,
            "男" if r.gender == "male" else ("女" if r.gender == "female" else ""),
            r.birth_date.isoformat() if r.birth_date else "",
            r.id_number or "",
            r.phone or "",
            r.district or "",
            TYPE_LABELS.get(r.archive_type, r.archive_type or ""),
            r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
        ])
    output.seek(0)
    from urllib.parse import quote
    filename = f"archives_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
    encoded_name = quote(f"档案导出_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv")
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={filename}; filename*=UTF-8''{encoded_name}"},
    )


@router.get("/stats")
async def archive_stats(access_token: str | None = Cookie(default=None)):
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    async with AsyncSessionLocal() as sess:
        total = await sess.scalar(
            select(func.count(PatientArchive.id)).where(PatientArchive.is_deleted == False)
        )
        by_type: dict[str, int] = {}
        for at in ArchiveType:
            cnt = await sess.scalar(
                select(func.count(PatientArchive.id)).where(
                    PatientArchive.archive_type == at,
                    PatientArchive.is_deleted == False,
                )
            )
            by_type[at.value] = cnt or 0
        recycle_count = await sess.scalar(
            select(func.count(PatientArchive.id)).where(PatientArchive.is_deleted == True)
        )
        family_count = await sess.scalar(select(func.count(FamilyArchive.id)))
        return ok({
            "total": total or 0,
            "by_type": by_type,
            "recycle_count": recycle_count or 0,
            "family_count": family_count or 0,
        })


# ── helpers ──────────────────────────────────────────────────────────
def _parse_uuid(v: Any) -> uuid.UUID | None:
    if not v:
        return None
    try:
        return uuid.UUID(str(v))
    except ValueError:
        return None


def _parse_date(v: Any):
    if not v:
        return None
    try:
        from datetime import date
        return date.fromisoformat(str(v))
    except Exception:
        return None


@router.post("/transfer")
async def transfer_archive(
    body: dict,
    access_token: str | None = Cookie(default=None)
):
    ctx = _auth(access_token)
    if not ctx:
        return err("UNAUTHORIZED", "未登录", status_code=401)

    archive_id_str = body.get("archive_id", "")
    to_doctor_id_str = body.get("to_doctor_id", "")
    if not archive_id_str or not to_doctor_id_str:
        return err("VALIDATION_ERROR", "archive_id 和 to_doctor_id 不能为空", status_code=400)

    try:
        archive_id = uuid.UUID(archive_id_str)
        to_doctor_id = uuid.UUID(to_doctor_id_str)
        from_doctor_id = uuid.UUID(ctx["sub"])
    except (ValueError, KeyError):
        return err("VALIDATION_ERROR", "ID 格式无效", status_code=400)

    async with AsyncSessionLocal() as db:
        transfer = ArchiveTransfer(
            archive_id=archive_id,
            from_doctor_id=from_doctor_id,
            to_doctor_id=to_doctor_id,
            reason=body.get("reason"),
        )
        db.add(transfer)
        await db.commit()
        await db.refresh(transfer)
        return ok({"id": str(transfer.id)})


@router.get("/transfers")
async def list_transfers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    access_token: str | None = Cookie(default=None),
):
    """档案移交记录列表"""
    if not _auth(access_token):
        return err("UNAUTHORIZED", "未登录", status_code=401)
    async with AsyncSessionLocal() as sess:
        stmt = select(ArchiveTransfer).order_by(ArchiveTransfer.created_at.desc())
        total = await sess.scalar(select(func.count()).select_from(stmt.subquery()))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await sess.execute(stmt)).scalars().all()
        items = []
        for r in rows:
            archive = await sess.get(PatientArchive, r.archive_id)
            patient_name = archive.name if archive else "未知患者"
            # 过滤：患者姓名搜索
            if q and q not in patient_name:
                continue
            from_doctor = await sess.get(User, r.from_doctor_id) if r.from_doctor_id else None
            to_doctor = await sess.get(User, r.to_doctor_id) if r.to_doctor_id else None
            items.append({
                "id": str(r.id),
                "time": r.created_at.strftime("%Y-%m-%d %H:%M"),
                "patient": patient_name,
                "archive_id": str(r.archive_id),
                "from_doctor": from_doctor.name if from_doctor else "-",
                "to_doctor": to_doctor.name if to_doctor else "-",
                "reason": r.reason or "",
                "notify": r.notify,
                "status": "DONE",
            })
        return ok({"total": len(items), "items": items, "page": page, "page_size": page_size})


@router.delete("/recycle/{archive_id}/permanent")
async def permanent_delete_archive(
    archive_id: str,
    access_token: str | None = Cookie(default=None),
):
    """永久删除回收站中的档案（不可恢复）"""
    payload = _auth(access_token)
    if not payload:
        return err("UNAUTHORIZED", "未登录", status_code=401)
    if payload.get("role") != "ADMIN":
        return err("FORBIDDEN", "仅管理员可永久删除档案")
    async with AsyncSessionLocal() as sess:
        row = await sess.get(PatientArchive, _parse_uuid(archive_id))
        if not row:
            return err("NOT_FOUND", "档案不存在", status_code=404)
        if not row.is_deleted:
            return err("VALIDATION_ERROR", "档案不在回收站中，请先移入回收站")
        await sess.delete(row)
        await sess.commit()
        return ok({"deleted": True})
