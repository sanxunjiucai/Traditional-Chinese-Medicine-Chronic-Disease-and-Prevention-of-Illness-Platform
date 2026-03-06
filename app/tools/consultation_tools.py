"""
在线咨询 API
prefix: /consultations

医患双向：患者发起，医生接诊回复
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models.archive import PatientArchive
from app.models.consultation import Consultation, ConsultationMessage
from app.models.enums import UserRole
from app.services.audit_service import log_action
from app.services.notification_service import push_to_patient
from app.tools.response import fail, ok

router = APIRouter(prefix="/consultations", tags=["consultations"])


# ── 帮助函数 ──────────────────────────────────────────────────────────────────

async def _resolve_archive(db: AsyncSession, current_user) -> PatientArchive | None:
    result = await db.execute(
        select(PatientArchive).where(PatientArchive.user_id == current_user.id)
    )
    return result.scalar_one_or_none()


def _consult_dict(c: Consultation, last_msg: str | None = None) -> dict:
    return {
        "id": str(c.id),
        "archive_id": str(c.archive_id),
        "doctor_id": str(c.doctor_id) if c.doctor_id else None,
        "title": c.title,
        "status": c.status,
        "priority": c.priority,
        "last_message": last_msg,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
        "closed_at": c.closed_at.isoformat() if c.closed_at else None,
    }


def _msg_dict(m: ConsultationMessage) -> dict:
    return {
        "id": str(m.id),
        "consultation_id": str(m.consultation_id),
        "sender_id": str(m.sender_id),
        "sender_type": m.sender_type,
        "content": m.content,
        "msg_type": m.msg_type,
        "created_at": m.created_at.isoformat(),
    }


# ── 患者发起咨询 ───────────────────────────────────────────────────────────────

class CreateConsultationRequest(BaseModel):
    title: str
    content: str
    priority: str = "NORMAL"  # NORMAL / URGENT


@router.post("")
async def create_consultation(
    body: CreateConsultationRequest,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(get_current_user),
):
    """患者发起咨询（任何登录用户均可，通过 archive 识别）"""
    archive = await _resolve_archive(db, current_user)
    if not archive:
        return fail("NOT_FOUND", "未找到患者档案，请先建档", status_code=404)

    consult = Consultation(
        archive_id=archive.id,
        title=body.title,
        status="OPEN",
        priority=body.priority,
    )
    db.add(consult)
    await db.flush()

    # 第一条消息
    msg = ConsultationMessage(
        consultation_id=consult.id,
        sender_id=archive.id,  # 患者用 archive_id 作为发送者ID
        sender_type="PATIENT",
        content=body.content,
        msg_type="TEXT",
    )
    db.add(msg)

    await log_action(
        db, action="CREATE_CONSULTATION", resource_type="Consultation",
        user_id=current_user.id, resource_id=str(consult.id),
        old_values=None, new_values={"title": body.title, "priority": body.priority},
    )
    await db.commit()

    return ok({"consultation_id": str(consult.id), "status": "OPEN"}, status_code=201)


# ── 医生查咨询列表 ─────────────────────────────────────────────────────────────

@router.get("")
async def list_consultations(
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, le=50),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)),
):
    """医生查看咨询列表"""
    filters = []
    if status:
        filters.append(Consultation.status == status)
    if priority:
        filters.append(Consultation.priority == priority)

    total_r = await db.execute(
        select(func.count()).select_from(Consultation).where(and_(*filters) if filters else True)
    )
    total = total_r.scalar_one()

    result = await db.execute(
        select(Consultation)
        .where(and_(*filters) if filters else True)
        .order_by(desc(Consultation.updated_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    consults = result.scalars().all()

    items = []
    for c in consults:
        # 获取最新一条消息内容
        last_msg_r = await db.execute(
            select(ConsultationMessage)
            .where(ConsultationMessage.consultation_id == c.id)
            .order_by(desc(ConsultationMessage.created_at))
            .limit(1)
        )
        last_msg = last_msg_r.scalar_one_or_none()

        # 获取患者姓名
        archive_r = await db.execute(select(PatientArchive).where(PatientArchive.id == c.archive_id))
        archive = archive_r.scalar_one_or_none()

        d = _consult_dict(c, last_msg.content[:50] if last_msg else None)
        d["patient_name"] = archive.name if archive else "未知"
        d["patient_phone"] = archive.phone if archive else None
        items.append(d)

    return ok({"total": total, "page": page, "page_size": page_size, "items": items})


# ── 咨询详情 + 消息列表 ────────────────────────────────────────────────────────

@router.get("/stats")
async def consultation_stats(
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)),
):
    """咨询统计（本月量、各状态数量）"""
    from datetime import date

    first_day = date.today().replace(day=1)

    total_r = await db.execute(select(func.count()).select_from(Consultation))
    open_r = await db.execute(
        select(func.count()).select_from(Consultation).where(Consultation.status == "OPEN")
    )
    replied_r = await db.execute(
        select(func.count()).select_from(Consultation).where(Consultation.status == "REPLIED")
    )
    closed_r = await db.execute(
        select(func.count()).select_from(Consultation).where(Consultation.status == "CLOSED")
    )
    month_r = await db.execute(
        select(func.count()).select_from(Consultation).where(
            func.date(Consultation.created_at) >= first_day
        )
    )

    return ok({
        "total": total_r.scalar_one(),
        "open": open_r.scalar_one(),
        "replied": replied_r.scalar_one(),
        "closed": closed_r.scalar_one(),
        "this_month": month_r.scalar_one(),
    })


@router.get("/{consult_id}")
async def get_consultation(
    consult_id: str = Path(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(get_current_user),
):
    """查看咨询详情（医患均可查看）"""
    try:
        cid = uuid.UUID(consult_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "consult_id 格式无效")

    result = await db.execute(select(Consultation).where(Consultation.id == cid))
    consult = result.scalar_one_or_none()
    if not consult:
        return fail("NOT_FOUND", "咨询不存在", status_code=404)

    msgs_r = await db.execute(
        select(ConsultationMessage)
        .where(ConsultationMessage.consultation_id == cid)
        .order_by(ConsultationMessage.created_at)
    )
    messages = msgs_r.scalars().all()

    archive_r = await db.execute(select(PatientArchive).where(PatientArchive.id == consult.archive_id))
    archive = archive_r.scalar_one_or_none()

    data = _consult_dict(consult)
    data["patient_name"] = archive.name if archive else "未知"
    data["messages"] = [_msg_dict(m) for m in messages]

    return ok(data)


# ── 发送消息 ──────────────────────────────────────────────────────────────────

class SendMessageRequest(BaseModel):
    content: str
    msg_type: str = "TEXT"


@router.post("/{consult_id}/messages")
async def send_message(
    body: SendMessageRequest,
    consult_id: str = Path(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(get_current_user),
):
    """发送消息（医生或患者）"""
    try:
        cid = uuid.UUID(consult_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "consult_id 格式无效")

    result = await db.execute(select(Consultation).where(Consultation.id == cid))
    consult = result.scalar_one_or_none()
    if not consult:
        return fail("NOT_FOUND", "咨询不存在", status_code=404)
    if consult.status == "CLOSED":
        return fail("STATE_ERROR", "咨询已关闭，无法发送消息", status_code=409)

    # 判断发送方角色
    is_doctor = current_user.role in (UserRole.ADMIN, UserRole.PROFESSIONAL)
    sender_type = "DOCTOR" if is_doctor else "PATIENT"

    msg = ConsultationMessage(
        consultation_id=cid,
        sender_id=current_user.id,
        sender_type=sender_type,
        content=body.content,
        msg_type=body.msg_type,
    )
    db.add(msg)

    # 医生回复：更新咨询状态 + 推送通知给患者
    if is_doctor:
        consult.status = "REPLIED"
        consult.doctor_id = current_user.id
        db.add(consult)

        notif = await push_to_patient(
            db=db,
            archive_id=consult.archive_id,
            title="医生已回复您的咨询",
            content=body.content[:100] + ("..." if len(body.content) > 100 else ""),
            notif_type="CONSULTATION_REPLY",
            action_url=f"/h5/consultation/{consult_id}",
            sender_id=current_user.id,
        )

    await db.commit()
    return ok({"message_id": str(msg.id), "sender_type": sender_type}, status_code=201)


# ── 关闭咨询 ──────────────────────────────────────────────────────────────────

@router.patch("/{consult_id}/close")
async def close_consultation(
    consult_id: str = Path(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)),
):
    """医生关闭咨询"""
    try:
        cid = uuid.UUID(consult_id)
    except ValueError:
        return fail("VALIDATION_ERROR", "consult_id 格式无效")

    result = await db.execute(select(Consultation).where(Consultation.id == cid))
    consult = result.scalar_one_or_none()
    if not consult:
        return fail("NOT_FOUND", "咨询不存在", status_code=404)
    if consult.status == "CLOSED":
        return fail("STATE_ERROR", "咨询已关闭", status_code=409)

    consult.status = "CLOSED"
    consult.closed_at = datetime.now(timezone.utc)
    db.add(consult)

    await log_action(
        db, action="CLOSE_CONSULTATION", resource_type="Consultation",
        user_id=current_user.id, resource_id=consult_id,
        old_values={"status": "OPEN"}, new_values={"status": "CLOSED"},
    )
    await db.commit()
    return ok({"consultation_id": consult_id, "status": "CLOSED"})
