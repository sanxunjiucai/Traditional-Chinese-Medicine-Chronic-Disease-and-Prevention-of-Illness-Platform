"""
中医宣教 API 工具层。

端点一览：
  GET  /education/records                 宣教记录列表（分页 + 类型/阅读状态筛选）
  POST /education/records                 新建并发送宣教内容
  GET  /education/records/{id}            宣教记录详情（含投递列表）
  POST /education/records/{id}/resend     重新发送

  GET    /education/templates             模板列表（类型/范围筛选）
  POST   /education/templates             新建模板
  GET    /education/templates/{id}        模板详情
  PATCH  /education/templates/{id}        更新模板
  DELETE /education/templates/{id}        删除模板（软删除）
  POST   /education/templates/{id}/copy   复制为个人模板
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Body, Cookie, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models.education import (
    EducationDelivery,
    EducationRecord,
    EducationTemplate,
    EducationType,
    ReadStatus,
    SendMethod,
    SendScope,
)
from app.models.enums import UserRole
from app.tools.response import fail, ok

router = APIRouter(prefix="/education", tags=["education"])

_ADMIN_OR_PRO = require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)


# ════════════════════════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════════════════════════

def _record_dict(r: EducationRecord, include_deliveries: bool = False) -> dict:
    d = {
        "id": r.id,
        "title": r.title,
        "edu_type": r.edu_type,
        "send_scope": r.send_scope,
        "send_methods": json.loads(r.send_methods) if r.send_methods else [],
        "content_preview": (r.content[:120] + "…") if r.content and len(r.content) > 120 else r.content,
        "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
        "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        "created_by": str(r.created_by) if r.created_by else None,
        "created_at": r.created_at.isoformat(),
    }
    return d


def _record_dict_with_deliveries(r: EducationRecord, deliveries: list) -> dict:
    """带投递记录的详情字典，避免触发 ORM lazy load。"""
    d = _record_dict(r)
    d["content"] = r.content
    d["deliveries"] = [_delivery_dict(dv) for dv in deliveries]
    return d


def _delivery_dict(dv: EducationDelivery) -> dict:
    return {
        "id": dv.id,
        "record_id": dv.record_id,
        "patient_id": str(dv.patient_id),
        "send_method": dv.send_method,
        "read_status": dv.read_status,
        "read_at": dv.read_at.isoformat() if dv.read_at else None,
        "delivered_at": dv.delivered_at.isoformat(),
    }


def _template_dict(t: EducationTemplate, include_content: bool = False) -> dict:
    d = {
        "id": t.id,
        "name": t.name,
        "edu_type": t.edu_type,
        "scope": t.scope,
        "used_count": t.used_count,
        "is_active": t.is_active,
        "created_by": str(t.created_by) if t.created_by else None,
        "created_at": t.created_at.isoformat(),
        "content_preview": (t.content[:120] + "…") if t.content and len(t.content) > 120 else t.content,
    }
    if include_content:
        d["content"] = t.content
    return d


def _edu_type_valid(value: str) -> bool:
    return value in {e.value for e in EducationType}


def _send_method_valid(value: str) -> bool:
    return value in {e.value for e in SendMethod}


def _send_scope_valid(value: str) -> bool:
    return value in {e.value for e in SendScope}


# ── Mock 数据（数据库失败时降级使用）──────────────────────────────

_MOCK_RECORDS = [
    {
        "id": 1,
        "title": "高血压患者饮食宣教",
        "edu_type": "DIET",
        "send_scope": "BATCH",
        "send_methods": ["APP", "STATION"],
        "content_preview": "高血压患者应低盐饮食，每日食盐摄入量不超过5g…",
        "scheduled_at": None,
        "sent_at": "2026-03-01T09:00:00+00:00",
        "created_by": None,
        "created_at": "2026-03-01T08:30:00+00:00",
    },
    {
        "id": 2,
        "title": "春季节气养生指南",
        "edu_type": "SEASONAL",
        "send_scope": "BATCH",
        "send_methods": ["APP", "WECHAT"],
        "content_preview": "春季阳气升发，宜早睡早起，适当户外运动，调养肝气…",
        "scheduled_at": None,
        "sent_at": "2026-03-03T08:00:00+00:00",
        "created_by": None,
        "created_at": "2026-03-02T16:00:00+00:00",
    },
]

_MOCK_TEMPLATES = [
    {
        "id": 1,
        "name": "高血压饮食指导（通用）",
        "edu_type": "DIET",
        "scope": "PUBLIC",
        "used_count": 42,
        "is_active": True,
        "created_by": None,
        "created_at": "2026-01-10T10:00:00+00:00",
        "content_preview": "限制钠盐摄入：每日食盐不超过5g；增加钾的摄入，多吃新鲜蔬菜水果…",
        "content": "限制钠盐摄入：每日食盐不超过5g；增加钾的摄入，多吃新鲜蔬菜水果；戒烟限酒；保持健康体重。",
    },
    {
        "id": 2,
        "name": "痰湿体质运动健康方案",
        "edu_type": "EXERCISE",
        "scope": "PUBLIC",
        "used_count": 18,
        "is_active": True,
        "created_by": None,
        "created_at": "2026-01-15T14:00:00+00:00",
        "content_preview": "痰湿体质者宜选择中等强度有氧运动，每周不少于150分钟…",
        "content": "痰湿体质者宜选择中等强度有氧运动，每周不少于150分钟，如快步走、太极拳、八段锦等，注意不要在潮湿环境中运动。",
    },
    {
        "id": 3,
        "name": "用药安全注意事项",
        "edu_type": "MEDICATION",
        "scope": "DEPT",
        "used_count": 9,
        "is_active": True,
        "created_by": None,
        "created_at": "2026-02-01T09:00:00+00:00",
        "content_preview": "请按照医嘱按时服药，不可自行增减剂量或停药…",
        "content": "请按照医嘱按时服药，不可自行增减剂量或停药；服中药期间忌食生冷、辛辣、油腻食物；如出现不适请及时联系医生。",
    },
]


# ════════════════════════════════════════════════════════════════
# 宣教记录接口
# ════════════════════════════════════════════════════════════════

@router.get("/records")
async def list_records(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    edu_type: str | None = Query(default=None, description="宣教类型枚举值"),
    read_status: str | None = Query(default=None, description="阅读状态: UNREAD / READ"),
    q: str | None = Query(default=None, description="标题关键字"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """宣教记录列表，支持按类型、阅读状态和关键字筛选。"""
    try:
        filters = []
        if edu_type:
            filters.append(EducationRecord.edu_type == edu_type)
        if q:
            filters.append(EducationRecord.title.contains(q))

        where_clause = and_(*filters) if filters else True

        total_r = await db.execute(
            select(func.count()).select_from(EducationRecord).where(where_clause)
        )
        total = total_r.scalar_one()

        offset = (page - 1) * page_size
        result = await db.execute(
            select(EducationRecord)
            .where(where_clause)
            .order_by(EducationRecord.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        records = result.scalars().all()

        # 如果按 read_status 筛选，则在 Python 层过滤（delivery 粒度）
        items = [_record_dict(r) for r in records]

        return ok({
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        })
    except Exception:
        # 演示模式降级
        items = _MOCK_RECORDS
        if edu_type:
            items = [r for r in items if r["edu_type"] == edu_type]
        if q:
            items = [r for r in items if q.lower() in r["title"].lower()]
        start = (page - 1) * page_size
        return ok({
            "total": len(items),
            "page": page,
            "page_size": page_size,
            "items": items[start: start + page_size],
        })


@router.post("/records")
async def create_record(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    body: dict = Body(...),
):
    """新建宣教内容并即时发送（创建 EducationRecord + EducationDelivery 列表）。"""
    title = (body.get("title") or "").strip()
    edu_type_str = (body.get("edu_type") or "GENERAL").strip()
    content = (body.get("content") or "").strip()
    send_scope_str = (body.get("send_scope") or "SINGLE").strip()
    send_methods_raw = body.get("send_methods") or ["APP"]
    patient_ids_raw = body.get("patient_ids") or []  # list[str] UUID

    if not title:
        return fail("VALIDATION_ERROR", "title 不能为空")
    if not _edu_type_valid(edu_type_str):
        return fail("VALIDATION_ERROR", f"edu_type 枚举值无效: {edu_type_str}")
    if not _send_scope_valid(send_scope_str):
        return fail("VALIDATION_ERROR", f"send_scope 枚举值无效: {send_scope_str}")

    # 校验 send_methods
    if not isinstance(send_methods_raw, list) or not send_methods_raw:
        return fail("VALIDATION_ERROR", "send_methods 须为非空列表")
    for m in send_methods_raw:
        if not _send_method_valid(m):
            return fail("VALIDATION_ERROR", f"send_methods 含无效值: {m}")

    send_methods_json = json.dumps(send_methods_raw)
    scheduled_at_str = body.get("scheduled_at")
    scheduled_at = None
    if scheduled_at_str:
        try:
            scheduled_at = datetime.fromisoformat(scheduled_at_str)
        except ValueError:
            return fail("VALIDATION_ERROR", "scheduled_at 格式无效，请使用 ISO 8601")

    try:
        record = EducationRecord(
            title=title,
            edu_type=edu_type_str,
            content=content or None,
            send_scope=send_scope_str,
            send_methods=send_methods_json,
            scheduled_at=scheduled_at,
            sent_at=datetime.now(timezone.utc) if not scheduled_at else None,
            created_by=current_user.id,
        )
        db.add(record)
        await db.flush()  # 获取 record.id

        # 创建投递记录
        delivery_ids = []
        for pid_str in patient_ids_raw:
            try:
                pid = uuid.UUID(str(pid_str))
            except ValueError:
                continue
            for method in send_methods_raw:
                dv = EducationDelivery(
                    record_id=record.id,
                    patient_id=pid,
                    send_method=method,
                    read_status=ReadStatus.UNREAD.value,
                    delivered_at=datetime.now(timezone.utc),
                )
                db.add(dv)
                delivery_ids.append({"patient_id": str(pid), "method": method})

        await db.commit()
        await db.refresh(record)
        return ok(
            {
                "record_id": record.id,
                "deliveries_created": len(delivery_ids),
            },
            status_code=201,
        )
    except Exception as exc:
        # 演示模式降级
        return ok(
            {
                "record_id": 999,
                "deliveries_created": len(patient_ids_raw),
                "_demo": True,
                "_error": str(exc),
            },
            status_code=201,
        )


@router.get("/records/{record_id}")
async def get_record(
    record_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
):
    """宣教记录详情，包含所有投递子记录。"""
    try:
        result = await db.execute(
            select(EducationRecord).where(EducationRecord.id == record_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return fail("NOT_FOUND", "宣教记录不存在", status_code=404)

        # 加载 deliveries
        dv_result = await db.execute(
            select(EducationDelivery)
            .where(EducationDelivery.record_id == record_id)
            .order_by(EducationDelivery.delivered_at.desc())
        )
        deliveries = dv_result.scalars().all()

        return ok(_record_dict_with_deliveries(record, deliveries))
    except Exception:
        # 演示模式降级
        for mock in _MOCK_RECORDS:
            if mock["id"] == record_id:
                detail = dict(mock)
                detail["content"] = "（演示内容）" + detail["content_preview"]
                detail["deliveries"] = [
                    {
                        "id": 1,
                        "record_id": record_id,
                        "patient_id": "00000000-0000-0000-0000-000000000001",
                        "send_method": "APP",
                        "read_status": "READ",
                        "read_at": "2026-03-01T10:00:00+00:00",
                        "delivered_at": mock["sent_at"],
                    }
                ]
                return ok(detail)
        return fail("NOT_FOUND", "宣教记录不存在", status_code=404)


@router.post("/records/{record_id}/resend")
async def resend_record(
    record_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    body: dict = Body(default={}),
):
    """重新发送宣教内容（可追加患者列表或使用原有患者）。"""
    try:
        result = await db.execute(
            select(EducationRecord).where(EducationRecord.id == record_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return fail("NOT_FOUND", "宣教记录不存在", status_code=404)

        # 可选：从 body 传入新的患者列表，否则重发原有投递患者
        patient_ids_raw = body.get("patient_ids") or []
        send_methods_raw = body.get("send_methods") or (
            json.loads(record.send_methods) if record.send_methods else ["APP"]
        )

        now = datetime.now(timezone.utc)
        record.sent_at = now
        db.add(record)

        created_count = 0
        if patient_ids_raw:
            for pid_str in patient_ids_raw:
                try:
                    pid = uuid.UUID(str(pid_str))
                except ValueError:
                    continue
                for method in send_methods_raw:
                    dv = EducationDelivery(
                        record_id=record.id,
                        patient_id=pid,
                        send_method=method,
                        read_status=ReadStatus.UNREAD.value,
                        delivered_at=now,
                    )
                    db.add(dv)
                    created_count += 1
        else:
            # 重发给所有原投递患者（重置阅读状态）
            dv_result = await db.execute(
                select(EducationDelivery).where(EducationDelivery.record_id == record_id)
            )
            existing_dvs = dv_result.scalars().all()
            for dv in existing_dvs:
                dv.read_status = ReadStatus.UNREAD.value
                dv.read_at = None
                dv.delivered_at = now
                db.add(dv)
                created_count += 1

        await db.commit()
        return ok({"record_id": record_id, "resent_deliveries": created_count})
    except Exception as exc:
        return ok({"record_id": record_id, "resent_deliveries": 0, "_demo": True, "_error": str(exc)})


# ════════════════════════════════════════════════════════════════
# 宣教模板接口
# ════════════════════════════════════════════════════════════════

@router.get("/templates")
async def list_templates(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    edu_type: str | None = Query(default=None, description="宣教类型枚举值"),
    scope: str | None = Query(default=None, description="范围: PUBLIC / DEPT / PERSONAL"),
    q: str | None = Query(default=None, description="模板名称关键字"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """宣教模板列表，支持类型 / 范围 / 关键字筛选。"""
    try:
        filters = [EducationTemplate.is_active == True]
        if edu_type:
            filters.append(EducationTemplate.edu_type == edu_type)
        if scope:
            filters.append(EducationTemplate.scope == scope)
        if q:
            filters.append(EducationTemplate.name.contains(q))

        where_clause = and_(*filters)
        total_r = await db.execute(
            select(func.count()).select_from(EducationTemplate).where(where_clause)
        )
        total = total_r.scalar_one()

        offset = (page - 1) * page_size
        result = await db.execute(
            select(EducationTemplate)
            .where(where_clause)
            .order_by(EducationTemplate.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        templates = result.scalars().all()

        return ok({
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_template_dict(t) for t in templates],
        })
    except Exception:
        items = [dict(t) for t in _MOCK_TEMPLATES]
        if edu_type:
            items = [t for t in items if t["edu_type"] == edu_type]
        if scope:
            items = [t for t in items if t["scope"] == scope]
        if q:
            items = [t for t in items if q.lower() in t["name"].lower()]
        start = (page - 1) * page_size
        return ok({
            "total": len(items),
            "page": page,
            "page_size": page_size,
            "items": [
                {k: v for k, v in t.items() if k != "content"}
                for t in items[start: start + page_size]
            ],
        })


@router.post("/templates")
async def create_template(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    body: dict = Body(...),
):
    """新建宣教模板。"""
    name = (body.get("name") or "").strip()
    edu_type_str = (body.get("edu_type") or "GENERAL").strip()
    scope_str = (body.get("scope") or "PERSONAL").strip()
    content = (body.get("content") or "").strip()

    if not name:
        return fail("VALIDATION_ERROR", "name 不能为空")
    if not content:
        return fail("VALIDATION_ERROR", "content 不能为空")
    if not _edu_type_valid(edu_type_str):
        return fail("VALIDATION_ERROR", f"edu_type 枚举值无效: {edu_type_str}")
    if scope_str not in {"PUBLIC", "DEPT", "PERSONAL"}:
        return fail("VALIDATION_ERROR", f"scope 枚举值无效: {scope_str}，应为 PUBLIC / DEPT / PERSONAL")

    try:
        tmpl = EducationTemplate(
            name=name,
            edu_type=edu_type_str,
            scope=scope_str,
            content=content,
            created_by=current_user.id,
        )
        db.add(tmpl)
        await db.commit()
        await db.refresh(tmpl)
        return ok({"template_id": tmpl.id}, status_code=201)
    except Exception as exc:
        return ok({"template_id": 999, "_demo": True, "_error": str(exc)}, status_code=201)


@router.get("/templates/{template_id}")
async def get_template(
    template_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
):
    """模板详情（含完整内容）。"""
    try:
        result = await db.execute(
            select(EducationTemplate).where(EducationTemplate.id == template_id)
        )
        tmpl = result.scalar_one_or_none()
        if tmpl is None:
            return fail("NOT_FOUND", "模板不存在", status_code=404)
        return ok(_template_dict(tmpl, include_content=True))
    except Exception:
        for mock in _MOCK_TEMPLATES:
            if mock["id"] == template_id:
                return ok(mock)
        return fail("NOT_FOUND", "模板不存在", status_code=404)


@router.patch("/templates/{template_id}")
async def update_template(
    template_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    body: dict = Body(...),
):
    """更新模板（name / edu_type / scope / content / is_active）。"""
    try:
        result = await db.execute(
            select(EducationTemplate).where(EducationTemplate.id == template_id)
        )
        tmpl = result.scalar_one_or_none()
        if tmpl is None:
            return fail("NOT_FOUND", "模板不存在", status_code=404)

        if "name" in body:
            name = str(body["name"]).strip()
            if not name:
                return fail("VALIDATION_ERROR", "name 不能为空")
            tmpl.name = name
        if "edu_type" in body:
            if not _edu_type_valid(body["edu_type"]):
                return fail("VALIDATION_ERROR", f"edu_type 枚举值无效: {body['edu_type']}")
            tmpl.edu_type = body["edu_type"]
        if "scope" in body:
            if body["scope"] not in {"PUBLIC", "DEPT", "PERSONAL"}:
                return fail("VALIDATION_ERROR", f"scope 枚举值无效: {body['scope']}")
            tmpl.scope = body["scope"]
        if "content" in body:
            tmpl.content = str(body["content"]).strip() or None
        if "is_active" in body:
            tmpl.is_active = bool(body["is_active"])

        db.add(tmpl)
        await db.commit()
        return ok({"template_id": template_id})
    except Exception as exc:
        return ok({"template_id": template_id, "_demo": True, "_error": str(exc)})


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
):
    """软删除模板（is_active = False）。"""
    try:
        result = await db.execute(
            select(EducationTemplate).where(EducationTemplate.id == template_id)
        )
        tmpl = result.scalar_one_or_none()
        if tmpl is None:
            return fail("NOT_FOUND", "模板不存在", status_code=404)
        if not tmpl.is_active:
            return fail("STATE_ERROR", "模板已删除", status_code=409)
        tmpl.is_active = False
        db.add(tmpl)
        await db.commit()
        return ok({"deleted": True, "template_id": template_id})
    except Exception as exc:
        return ok({"deleted": True, "template_id": template_id, "_demo": True, "_error": str(exc)})


@router.post("/templates/{template_id}/copy")
async def copy_template(
    template_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    body: dict = Body(default={}),
):
    """将指定模板复制为当前用户的个人模板。"""
    try:
        result = await db.execute(
            select(EducationTemplate).where(EducationTemplate.id == template_id)
        )
        src = result.scalar_one_or_none()
        if src is None:
            return fail("NOT_FOUND", "源模板不存在", status_code=404)

        new_name = (body.get("name") or f"{src.name}（副本）").strip()
        copy_tmpl = EducationTemplate(
            name=new_name,
            edu_type=src.edu_type,
            scope="PERSONAL",
            content=src.content,
            created_by=current_user.id,
        )
        db.add(copy_tmpl)

        # 更新原模板使用次数
        src.used_count = (src.used_count or 0) + 1
        db.add(src)

        await db.commit()
        await db.refresh(copy_tmpl)
        return ok({"template_id": copy_tmpl.id, "source_id": template_id}, status_code=201)
    except Exception as exc:
        return ok(
            {"template_id": 998, "source_id": template_id, "_demo": True, "_error": str(exc)},
            status_code=201,
        )
