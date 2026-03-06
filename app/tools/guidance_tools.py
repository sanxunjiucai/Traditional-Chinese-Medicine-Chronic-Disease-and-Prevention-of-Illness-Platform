"""
中医指导 / 干预 / 宣教 API。
包含：模板管理、记录创建/查询。
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models.enums import GuidanceStatus, GuidanceType, TemplateScope, UserRole
from app.models.guidance import GuidanceRecord, GuidanceTemplate
from app.models.user import User
from app.tools.response import fail, ok

router = APIRouter(prefix="/guidance", tags=["guidance"])

_ADMIN_OR_PRO = require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)


# ════════════════════════════════════
# 模板管理
# ════════════════════════════════════

@router.get("/templates")
async def list_templates(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    guidance_type: GuidanceType | None = Query(default=None),
    scope: TemplateScope | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    filters = [GuidanceTemplate.is_active == True]
    if guidance_type:
        filters.append(GuidanceTemplate.guidance_type == guidance_type)
    if scope:
        filters.append(GuidanceTemplate.scope == scope)
    if q:
        filters.append(GuidanceTemplate.name.contains(q))

    total_r = await db.execute(
        select(func.count()).select_from(GuidanceTemplate).where(and_(*filters))
    )
    total = total_r.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        select(GuidanceTemplate)
        .where(and_(*filters))
        .order_by(GuidanceTemplate.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    templates = result.scalars().all()

    return ok({
        "total": total, "page": page, "page_size": page_size,
        "items": [
            {
                "id": str(t.id),
                "name": t.name,
                "guidance_type": t.guidance_type.value,
                "scope": t.scope.value,
                "tags": t.tags,
                "content_preview": t.content[:100] + "..." if len(t.content) > 100 else t.content,
                "created_at": t.created_at.isoformat(),
            }
            for t in templates
        ],
    })


@router.post("/templates")
async def create_template(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    body: dict = Body(...),
):
    name = body.get("name", "").strip()
    content = body.get("content", "").strip()
    guidance_type_str = body.get("guidance_type", "GUIDANCE")
    scope_str = body.get("scope", "PERSONAL")
    tags = body.get("tags", "")

    if not name or not content:
        return fail("VALIDATION_ERROR", "name 和 content 不能为空")

    try:
        guidance_type = GuidanceType(guidance_type_str)
        scope = TemplateScope(scope_str)
    except ValueError:
        return fail("VALIDATION_ERROR", "类型或范围枚举值无效")

    tmpl = GuidanceTemplate(
        name=name,
        guidance_type=guidance_type,
        scope=scope,
        content=content,
        tags=tags,
        created_by=current_user.id,
    )
    db.add(tmpl)
    await db.commit()
    await db.refresh(tmpl)
    return ok({"template_id": str(tmpl.id)})


@router.get("/templates/{template_id}")
async def get_template(
    template_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
):
    result = await db.execute(
        select(GuidanceTemplate).where(GuidanceTemplate.id == uuid.UUID(template_id))
    )
    tmpl = result.scalar_one_or_none()
    if tmpl is None:
        return fail("NOT_FOUND", "模板不存在", status_code=404)
    return ok({
        "id": str(tmpl.id),
        "name": tmpl.name,
        "guidance_type": tmpl.guidance_type.value,
        "scope": tmpl.scope.value,
        "content": tmpl.content,
        "tags": tmpl.tags,
        "is_active": tmpl.is_active,
        "created_at": tmpl.created_at.isoformat(),
    })


@router.patch("/templates/{template_id}")
async def update_template(
    template_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    body: dict = Body(...),
):
    result = await db.execute(
        select(GuidanceTemplate).where(GuidanceTemplate.id == uuid.UUID(template_id))
    )
    tmpl = result.scalar_one_or_none()
    if tmpl is None:
        return fail("NOT_FOUND", "模板不存在", status_code=404)

    if "name" in body:
        tmpl.name = body["name"].strip()
    if "content" in body:
        tmpl.content = body["content"].strip()
    if "tags" in body:
        tmpl.tags = body["tags"]
    if "is_active" in body:
        tmpl.is_active = bool(body["is_active"])

    db.add(tmpl)
    await db.commit()
    return ok({"template_id": template_id})


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
):
    result = await db.execute(
        select(GuidanceTemplate).where(GuidanceTemplate.id == uuid.UUID(template_id))
    )
    tmpl = result.scalar_one_or_none()
    if tmpl is None:
        return fail("NOT_FOUND", "模板不存在", status_code=404)
    tmpl.is_active = False
    db.add(tmpl)
    await db.commit()
    return ok({"deleted": True})


# ════════════════════════════════════
# 指导记录（下达 / 查询）
# ════════════════════════════════════

@router.get("/records/{record_id}")
async def get_record(
    record_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    """获取指导记录详情（患者和医生均可访问）"""
    try:
        rid = uuid.UUID(record_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "record_id 格式无效")

    result = await db.execute(
        select(GuidanceRecord).where(GuidanceRecord.id == rid)
    )
    r = result.scalar_one_or_none()
    if r is None:
        return fail("NOT_FOUND", "记录不存在", status_code=404)

    doctor_r = await db.execute(select(User).where(User.id == r.doctor_id))
    doctor = doctor_r.scalar_one_or_none()

    return ok({
        "id": str(r.id),
        "patient_id": str(r.patient_id),
        "doctor_id": str(r.doctor_id) if r.doctor_id else None,
        "doctor_name": doctor.name if doctor else "医生",
        "guidance_type": r.guidance_type.value,
        "title": r.title,
        "content": r.content,
        "status": r.status.value,
        "is_read": r.is_read,
        "created_at": r.created_at.isoformat(),
    })


@router.get("/records")
async def list_records(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    guidance_type: GuidanceType | None = Query(default=None),
    patient_id: str | None = Query(default=None),
    status: GuidanceStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    filters = []
    if guidance_type:
        filters.append(GuidanceRecord.guidance_type == guidance_type)
    if status:
        filters.append(GuidanceRecord.status == status)
    if patient_id:
        try:
            pid = uuid.UUID(patient_id)
            filters.append(GuidanceRecord.patient_id == pid)
        except ValueError:
            return fail("VALIDATION_ERROR", "patient_id 格式无效")

    total_r = await db.execute(
        select(func.count()).select_from(GuidanceRecord)
        .where(and_(*filters) if filters else True)
    )
    total = total_r.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        select(GuidanceRecord)
        .where(and_(*filters) if filters else True)
        .order_by(GuidanceRecord.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    records = result.scalars().all()

    items = []
    for r in records:
        patient_r = await db.execute(select(User).where(User.id == r.patient_id))
        patient = patient_r.scalar_one_or_none()
        items.append({
            "id": str(r.id),
            "patient_id": str(r.patient_id),
            "patient_name": patient.name if patient else "未知",
            "guidance_type": r.guidance_type.value,
            "title": r.title,
            "status": r.status.value,
            "is_read": r.is_read,
            "created_at": r.created_at.isoformat(),
        })

    return ok({"total": total, "page": page, "page_size": page_size, "items": items})


@router.post("/records")
async def create_record(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    body: dict = Body(...),
):
    patient_id_str = body.get("patient_id", "")
    title = body.get("title", "").strip()
    content = body.get("content", "").strip()
    guidance_type_str = body.get("guidance_type", "GUIDANCE")
    template_id_str = body.get("template_id")

    if not patient_id_str or not title or not content:
        return fail("VALIDATION_ERROR", "patient_id、title、content 不能为空")

    try:
        patient_id = uuid.UUID(patient_id_str)
        guidance_type = GuidanceType(guidance_type_str)
    except ValueError:
        return fail("VALIDATION_ERROR", "参数格式或枚举值无效")

    # 校验患者存在
    patient_r = await db.execute(select(User).where(User.id == patient_id))
    if patient_r.scalar_one_or_none() is None:
        return fail("NOT_FOUND", "患者不存在", status_code=404)

    template_id = uuid.UUID(template_id_str) if template_id_str else None

    record = GuidanceRecord(
        patient_id=patient_id,
        doctor_id=current_user.id,
        guidance_type=guidance_type,
        title=title,
        content=content,
        template_id=template_id,
        status=GuidanceStatus.PUBLISHED,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return ok({"record_id": str(record.id)})


@router.post("/records/{record_id}/remind")
async def send_reminder(
    record_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
):
    """对已下达的指导记录发送二次提醒通知。"""
    try:
        rid = uuid.UUID(record_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "record_id 格式无效")

    r_res = await db.execute(select(GuidanceRecord).where(GuidanceRecord.id == rid))
    record = r_res.scalar_one_or_none()
    if not record:
        return fail("NOT_FOUND", "记录不存在", status_code=404)

    from app.models.archive import PatientArchive
    from app.services.notification_service import push_to_patient
    arch_r = await db.execute(
        select(PatientArchive).where(PatientArchive.user_id == record.patient_id)
    )
    arch = arch_r.scalar_one_or_none()
    if not arch:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    await push_to_patient(
        db=db,
        archive_id=arch.id,
        title="医生发来提醒：请查看您的健康指导",
        content=f"【二次提醒】{record.title}",
        notif_type="REMINDER",
        action_url=f"/h5/plan/{record_id}",
        sender_id=current_user.id,
    )
    await db.commit()
    return ok({"message": "提醒已发送"})


@router.post("/templates/{template_id}/copy")
async def copy_template(
    template_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    body: dict = Body(default={}),
):
    """将指定指导模板复制为当前用户的个人模板。"""
    try:
        tid = uuid.UUID(template_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "template_id 格式无效")

    src_res = await db.execute(select(GuidanceTemplate).where(GuidanceTemplate.id == tid))
    src = src_res.scalar_one_or_none()
    if not src:
        return fail("NOT_FOUND", "源模板不存在", status_code=404)

    new_name = (body.get("name") or f"{src.name}（副本）").strip()
    copy_tmpl = GuidanceTemplate(
        name=new_name,
        guidance_type=src.guidance_type,
        scope=TemplateScope.PERSONAL,
        content=src.content,
        created_by=current_user.id,
    )
    db.add(copy_tmpl)
    await db.commit()
    await db.refresh(copy_tmpl)
    return ok({"template_id": str(copy_tmpl.id), "source_id": template_id}, status_code=201)
