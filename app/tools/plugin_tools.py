"""
HIS 插件端 API
prefix: /plugin

提供给 HIS 嵌入插件 / 外部工具调用的统一接口：

A. context   — 读取 / 绑定就诊上下文（patient_id, visit_id, doctor_id, his_page_type, org_id）
B. patient   — 患者档案、健康指标、风险标签
C. plan      — 调理方案（草稿·版本·发布·diff·渲染）
D. template  — 指导/干预/宣教模板库
E. followup  — 随访计划与任务
"""
from __future__ import annotations

import difflib
import re
import uuid
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import require_role
from app.models.alert import AlertEvent
from app.models.archive import PatientArchive
from app.models.constitution import ConstitutionAssessment
from app.models.enums import (
    AlertStatus, DiseaseType, FollowupStatus, GuidanceStatus,
    GuidanceType, TaskType, UserRole,
)
from app.models.followup import FollowupPlan, FollowupTask
from app.models.guidance import GuidanceRecord, GuidanceTemplate
from app.models.health import ChronicDiseaseRecord, HealthIndicator, HealthProfile
from app.models.user import User
from app.tools.response import fail, ok

router = APIRouter(prefix="/plugin", tags=["plugin"])

_PRO = require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)

# ── 内部辅助 ──────────────────────────────────────────────────────────────────

_DISEASE_CN = {
    "HYPERTENSION": "高血压", "DIABETES_T2": "2型糖尿病",
    "DYSLIPIDEMIA": "血脂异常", "COPD": "慢阻肺",
    "CORONARY_HEART_DISEASE": "冠心病", "CEREBROVASCULAR_DISEASE": "脑血管病",
    "CHRONIC_KIDNEY_DISEASE": "慢性肾病", "FATTY_LIVER": "脂肪肝",
    "OSTEOPOROSIS": "骨质疏松", "GOUT": "痛风",
}

_INDICATOR_CN = {
    "BLOOD_PRESSURE": "血压", "BLOOD_GLUCOSE": "血糖",
    "WEIGHT": "体重", "WAIST_CIRCUMFERENCE": "腰围",
}

_BODY_TYPE_CN = {
    "BALANCED": "平和质", "QI_DEFICIENCY": "气虚质",
    "YANG_DEFICIENCY": "阳虚质", "YIN_DEFICIENCY": "阴虚质",
    "PHLEGM_DAMPNESS": "痰湿质", "DAMP_HEAT": "湿热质",
    "BLOOD_STASIS": "血瘀质", "QI_STAGNATION": "气郁质",
    "SPECIAL_DIATHESIS": "特禀质",
}


def _parse_uuid(v: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(v)
    except (ValueError, AttributeError):
        return None


def _archive_brief(a: PatientArchive) -> dict:
    age = None
    if a.birth_date:
        today = date.today()
        age = today.year - a.birth_date.year - (
            (today.month, today.day) < (a.birth_date.month, a.birth_date.day)
        )
    return {
        "patient_id": str(a.id),
        "name": a.name,
        "gender": a.gender,
        "age": age,
        "birth_date": str(a.birth_date) if a.birth_date else None,
        "phone": a.phone,
        "archive_type": a.archive_type.value if a.archive_type else None,
        "district": a.district,
    }


# ══════════════════════════════════════════════════════════════════════════════
# A. Context — 就诊上下文
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/context")
async def get_his_context(
    patient_id: str | None = Query(default=None, description="HIS 注入的 archive_id"),
    visit_id: str | None = Query(default=None, description="HIS 就诊流水号"),
    doctor_id: str | None = Query(default=None, description="接诊医生 ID"),
    his_page_type: str | None = Query(default=None, description="HIS页面类型：OUTPATIENT/INPATIENT/EMERGENCY"),
    org_id: str | None = Query(default=None, description="机构 ID"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    读取 HIS 注入的就诊上下文。
    真实部署时由 HIS iframe URL 参数携带；演示模式接受 query 参数回传。
    输出：patient_id, visit_id, doctor_id, his_page_type, org_id
    """
    result: dict = {
        "visit_id": visit_id,
        "his_page_type": his_page_type or "OUTPATIENT",
        "org_id": org_id,
        "doctor_id": doctor_id or str(current_user.id),
        "doctor_name": current_user.name,
        "patient_id": None,
        "patient_brief": None,
    }

    if patient_id:
        aid = _parse_uuid(patient_id)
        if aid:
            a = await db.get(PatientArchive, aid)
            if a and not a.is_deleted:
                result["patient_id"] = patient_id
                result["patient_brief"] = _archive_brief(a)

    return ok(result)


class BindContextRequest(BaseModel):
    patient_key: str  # 姓名 / 手机号 / 证件号（手动输入或扫码识别）


@router.post("/bind")
async def bind_patient_context(
    body: BindContextRequest,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    手动搜索 / 扫码绑定患者。
    patient_key 支持：姓名、手机号、身份证号。
    返回匹配的 patient_id 及档案摘要。
    """
    key = body.patient_key.strip()
    if not key:
        return fail("VALIDATION_ERROR", "patient_key 不能为空")

    stmt = (
        select(PatientArchive)
        .where(
            and_(
                PatientArchive.is_deleted == False,
                or_(
                    PatientArchive.name.ilike(f"%{key}%"),
                    PatientArchive.phone == key,
                    PatientArchive.id_number == key,
                ),
            )
        )
        .limit(10)
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return fail("NOT_FOUND", f"未找到匹配患者：{key}", status_code=404)

    return ok({
        "matched": len(rows),
        "patient_id": str(rows[0].id) if len(rows) == 1 else None,
        "items": [_archive_brief(a) for a in rows],
        "bound": len(rows) == 1,
    })


# ══════════════════════════════════════════════════════════════════════════════
# B. Patient — 患者档案、指标、风险标签
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/patient/search")
async def patient_search(
    query: str = Query(..., description="姓名 / 手机号 / 身份证号关键字"),
    archive_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """搜索患者档案（支持姓名/手机/证件）"""
    filters = [
        PatientArchive.is_deleted == False,
        or_(
            PatientArchive.name.ilike(f"%{query}%"),
            PatientArchive.phone.ilike(f"%{query}%"),
            PatientArchive.id_number.ilike(f"%{query}%"),
        ),
    ]
    if archive_type:
        filters.append(PatientArchive.archive_type == archive_type)

    total = await db.scalar(
        select(func.count(PatientArchive.id)).where(and_(*filters))
    )
    rows = (await db.execute(
        select(PatientArchive).where(and_(*filters))
        .order_by(PatientArchive.name)
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return ok({"total": total, "items": [_archive_brief(a) for a in rows]})


@router.get("/patient/{patient_id}/profile")
async def get_patient_profile(
    patient_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    获取患者完整档案资料。
    包含：基本信息、体质评估、慢病记录、健康概况。
    """
    aid = _parse_uuid(patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    # 体质评估
    constitution = None
    chronic_diseases: list[dict] = []
    health_profile = None

    if archive.user_id:
        ca = (await db.execute(
            select(ConstitutionAssessment)
            .where(ConstitutionAssessment.user_id == archive.user_id)
            .order_by(desc(ConstitutionAssessment.created_at))
            .limit(1)
        )).scalar_one_or_none()
        if ca and ca.main_type:
            constitution = {
                "main_type": ca.main_type.value,
                "main_type_cn": _BODY_TYPE_CN.get(ca.main_type.value, ca.main_type.value),
                "assessed_at": ca.scored_at.isoformat() if ca.scored_at else None,
            }

        # 慢病记录
        diseases = (await db.execute(
            select(ChronicDiseaseRecord)
            .where(
                ChronicDiseaseRecord.user_id == archive.user_id,
                ChronicDiseaseRecord.is_active == True,
            )
        )).scalars().all()
        chronic_diseases = [
            {
                "disease_type": d.disease_type.value,
                "disease_cn": _DISEASE_CN.get(d.disease_type.value, d.disease_type.value),
                "diagnosed_at": str(d.diagnosed_at) if d.diagnosed_at else None,
                "hospital": d.diagnosed_hospital,
            }
            for d in diseases
        ]

        # 健康概况
        hp = (await db.execute(
            select(HealthProfile).where(HealthProfile.user_id == archive.user_id)
        )).scalar_one_or_none()
        if hp:
            health_profile = {
                "height_cm": hp.height_cm,
                "weight_kg": hp.weight_kg,
                "bmi": round(hp.weight_kg / (hp.height_cm / 100) ** 2, 1)
                       if hp.height_cm and hp.weight_kg else None,
                "smoking": hp.smoking,
                "drinking": hp.drinking,
                "exercise_frequency": hp.exercise_frequency,
            }

    age = None
    if archive.birth_date:
        today = date.today()
        age = today.year - archive.birth_date.year - (
            (today.month, today.day) < (archive.birth_date.month, archive.birth_date.day)
        )

    return ok({
        "patient_id": patient_id,
        "name": archive.name,
        "gender": archive.gender,
        "age": age,
        "birth_date": str(archive.birth_date) if archive.birth_date else None,
        "phone": archive.phone,
        "id_number": archive.id_number,
        "archive_type": archive.archive_type.value if archive.archive_type else None,
        "address": " ".join(filter(None, [archive.province, archive.city, archive.district, archive.address])),
        "past_history": archive.past_history or [],
        "family_history": archive.family_history or [],
        "allergy_history": archive.allergy_history or [],
        "constitution": constitution,
        "chronic_diseases": chronic_diseases,
        "health_profile": health_profile,
    })


@router.get("/patient/{patient_id}/metrics")
async def get_patient_metrics(
    patient_id: str,
    range_days: int = Query(default=90, ge=7, le=365, alias="range"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    获取患者健康指标时序数据（血压、血糖、体重、腰围）。
    range：天数范围，默认 90 天。
    """
    aid = _parse_uuid(patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    if not archive.user_id:
        return ok({"patient_id": patient_id, "range_days": range_days, "metrics": {}})

    from datetime import datetime, timezone
    since = datetime.now(timezone.utc) - timedelta(days=range_days)

    rows = (await db.execute(
        select(HealthIndicator)
        .where(
            HealthIndicator.user_id == archive.user_id,
            HealthIndicator.recorded_at >= since,
        )
        .order_by(HealthIndicator.recorded_at.asc())
    )).scalars().all()

    # 按 indicator_type 分组
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        key = r.indicator_type.value
        entry = {
            "recorded_at": r.recorded_at.isoformat(),
            **r.values,
        }
        grouped.setdefault(key, []).append(entry)

    # 统计摘要
    summary: dict[str, dict] = {}
    for itype, entries in grouped.items():
        if itype == "BLOOD_PRESSURE":
            systolics = [e.get("systolic") for e in entries if e.get("systolic")]
            diastolics = [e.get("diastolic") for e in entries if e.get("diastolic")]
            if systolics:
                summary[itype] = {
                    "cn": "血压",
                    "count": len(entries),
                    "latest": f"{entries[-1].get('systolic')}/{entries[-1].get('diastolic')} mmHg",
                    "avg_systolic": round(sum(systolics) / len(systolics), 1),
                    "avg_diastolic": round(sum(diastolics) / len(diastolics), 1),
                    "abnormal_count": sum(1 for s in systolics if s > 140),
                }
        elif itype == "BLOOD_GLUCOSE":
            values = [e.get("value") for e in entries if e.get("value")]
            if values:
                summary[itype] = {
                    "cn": "血糖",
                    "count": len(entries),
                    "latest": f"{entries[-1].get('value')} mmol/L",
                    "avg": round(sum(values) / len(values), 2),
                    "abnormal_count": sum(1 for v in values if v > 7.0),
                }
        else:
            vals = [e.get("value") for e in entries if e.get("value")]
            if vals:
                summary[itype] = {
                    "cn": _INDICATOR_CN.get(itype, itype),
                    "count": len(entries),
                    "latest": str(vals[-1]),
                    "avg": round(sum(vals) / len(vals), 2),
                }

    return ok({
        "patient_id": patient_id,
        "range_days": range_days,
        "summary": summary,
        "metrics": {k: v for k, v in grouped.items()},
    })


@router.get("/patient/{patient_id}/risk-tags")
async def get_patient_risk_tags(
    patient_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    获取患者当前风险标签：
    - 档案 tags（人工打标）
    - 未处置 AlertEvent（系统自动预警）
    - 活跃慢病列表
    """
    aid = _parse_uuid(patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    # 档案标签
    manual_tags: list[str] = archive.tags or []

    # 未处置预警
    alert_tags: list[dict] = []
    if archive.user_id:
        alerts = (await db.execute(
            select(AlertEvent)
            .where(
                AlertEvent.user_id == archive.user_id,
                AlertEvent.status == AlertStatus.OPEN,
            )
            .order_by(desc(AlertEvent.created_at))
            .limit(10)
        )).scalars().all()
        alert_tags = [
            {
                "alert_id": str(e.id),
                "severity": e.severity.value,
                "message": e.message,
                "created_at": e.created_at.isoformat(),
            }
            for e in alerts
        ]

    # 慢病
    disease_tags: list[str] = []
    if archive.user_id:
        diseases = (await db.execute(
            select(ChronicDiseaseRecord)
            .where(
                ChronicDiseaseRecord.user_id == archive.user_id,
                ChronicDiseaseRecord.is_active == True,
            )
        )).scalars().all()
        disease_tags = [
            _DISEASE_CN.get(d.disease_type.value, d.disease_type.value)
            for d in diseases
        ]

    # 综合风险等级推断
    has_high = any(a["severity"] == "HIGH" for a in alert_tags)
    has_medium = any(a["severity"] == "MEDIUM" for a in alert_tags)
    inferred_risk = "HIGH" if has_high else ("MEDIUM" if (has_medium or len(disease_tags) >= 2) else "LOW")

    return ok({
        "patient_id": patient_id,
        "inferred_risk_level": inferred_risk,
        "manual_tags": manual_tags,
        "disease_tags": disease_tags,
        "alert_tags": alert_tags,
        "total_open_alerts": len(alert_tags),
    })


# ══════════════════════════════════════════════════════════════════════════════
# C. Plan — 调理方案（版本管理、草稿、发布、diff、渲染）
# ══════════════════════════════════════════════════════════════════════════════

def _plan_item(r: GuidanceRecord) -> dict:
    return {
        "plan_id": str(r.id),
        "title": r.title,
        "status": r.status.value,
        "is_read": r.is_read,
        "created_at": r.created_at.isoformat(),
        "content_preview": r.content[:120] + "..." if len(r.content) > 120 else r.content,
    }


@router.get("/plan/versions/{patient_id}")
async def list_plan_versions(
    patient_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """列出患者所有方案版本（DRAFT / PUBLISHED / ARCHIVED）"""
    aid = _parse_uuid(patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    if not archive.user_id:
        return ok({"total": 0, "items": []})

    filters = [
        GuidanceRecord.patient_id == archive.user_id,
        GuidanceRecord.guidance_type == GuidanceType.GUIDANCE,
    ]
    total = await db.scalar(select(func.count(GuidanceRecord.id)).where(and_(*filters)))
    rows = (await db.execute(
        select(GuidanceRecord).where(and_(*filters))
        .order_by(desc(GuidanceRecord.created_at))
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return ok({"total": total, "items": [_plan_item(r) for r in rows]})


@router.get("/plan/current/{patient_id}")
async def get_current_plan(
    patient_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """获取患者当前生效方案（status=PUBLISHED）"""
    aid = _parse_uuid(patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    if not archive.user_id:
        return ok({"plan": None})

    plan = (await db.execute(
        select(GuidanceRecord)
        .where(
            GuidanceRecord.patient_id == archive.user_id,
            GuidanceRecord.guidance_type == GuidanceType.GUIDANCE,
            GuidanceRecord.status == GuidanceStatus.PUBLISHED,
        )
        .order_by(desc(GuidanceRecord.created_at))
        .limit(1)
    )).scalar_one_or_none()

    if not plan:
        return ok({"plan": None})

    return ok({
        "plan": {
            **_plan_item(plan),
            "content": plan.content,
        }
    })


class CreateDraftRequest(BaseModel):
    patient_id: str
    source: Literal["template", "ai", "copy", "manual"] = "manual"
    title: str = "个性化中医调理方案"
    content: str = ""
    template_id: str | None = None   # source=template 时使用
    copy_from_plan_id: str | None = None  # source=copy 时使用


@router.post("/plan/draft")
async def create_plan_draft(
    body: CreateDraftRequest,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    新建草稿方案。
    source=template → 从模板复制内容
    source=ai       → 触发 AI 生成（异步：返回空草稿，内容通过 PATCH 更新）
    source=copy     → 复制已有方案
    source=manual   → 空白草稿，由医生手动撰写
    """
    aid = _parse_uuid(body.patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    if not archive.user_id:
        return fail("BUSINESS_ERROR", "该患者档案未关联系统用户，无法创建方案")

    content = body.content
    title = body.title

    if body.source == "template" and body.template_id:
        tid = _parse_uuid(body.template_id)
        if tid:
            tmpl = await db.get(GuidanceTemplate, tid)
            if tmpl:
                content = tmpl.content
                title = title or tmpl.name

    elif body.source == "copy" and body.copy_from_plan_id:
        pid = _parse_uuid(body.copy_from_plan_id)
        if pid:
            src = await db.get(GuidanceRecord, pid)
            if src:
                content = src.content
                title = f"{src.title}（副本）"

    elif body.source == "ai":
        # 异步触发 AI 生成：先建草稿占位，前端轮询或用 /plan/update_draft 填充
        content = content or "（AI 正在生成，请稍后刷新...）"

    draft = GuidanceRecord(
        patient_id=archive.user_id,
        doctor_id=current_user.id,
        guidance_type=GuidanceType.GUIDANCE,
        title=title,
        content=content,
        status=GuidanceStatus.DRAFT,
        is_read=False,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)

    return ok({
        "plan_id": str(draft.id),
        "title": draft.title,
        "status": draft.status.value,
        "source": body.source,
        "created_at": draft.created_at.isoformat(),
    })


class UpdateDraftRequest(BaseModel):
    title: str | None = None
    content: str | None = None


@router.patch("/plan/{plan_id}/draft")
async def update_plan_draft(
    plan_id: str,
    body: UpdateDraftRequest,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """更新草稿（仅 DRAFT 状态可编辑）"""
    pid = _parse_uuid(plan_id)
    if not pid:
        return fail("VALIDATION_ERROR", "plan_id 格式无效")

    plan = await db.get(GuidanceRecord, pid)
    if not plan:
        return fail("NOT_FOUND", "方案不存在", status_code=404)
    if plan.status != GuidanceStatus.DRAFT:
        return fail("BUSINESS_ERROR", f"只有草稿状态可编辑，当前状态：{plan.status.value}")

    if body.title is not None:
        plan.title = body.title
    if body.content is not None:
        plan.content = body.content

    db.add(plan)
    await db.commit()
    await db.refresh(plan)

    return ok({"plan_id": plan_id, "title": plan.title, "updated": True})


@router.get("/plan/diff")
async def diff_plans(
    plan_id_old: str = Query(...),
    plan_id_new: str = Query(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    对比两个方案版本的内容差异。
    返回 unified diff 格式（逐行）。
    """
    oid = _parse_uuid(plan_id_old)
    nid = _parse_uuid(plan_id_new)
    if not oid or not nid:
        return fail("VALIDATION_ERROR", "plan_id 格式无效")

    old_plan = await db.get(GuidanceRecord, oid)
    new_plan = await db.get(GuidanceRecord, nid)
    if not old_plan or not new_plan:
        return fail("NOT_FOUND", "方案不存在", status_code=404)

    old_lines = old_plan.content.splitlines(keepends=True)
    new_lines = new_plan.content.splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"{old_plan.title} ({old_plan.status.value})",
        tofile=f"{new_plan.title} ({new_plan.status.value})",
        lineterm="",
    ))

    additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    deletions = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

    return ok({
        "plan_id_old": plan_id_old,
        "plan_id_new": plan_id_new,
        "additions": additions,
        "deletions": deletions,
        "diff_lines": diff,
        "unchanged": additions == 0 and deletions == 0,
    })


@router.post("/plan/{plan_id}/publish")
async def publish_plan(
    plan_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    发布方案：
    1. 将指定方案状态置为 PUBLISHED
    2. 该患者所有旧 PUBLISHED 方案自动 ARCHIVED
    """
    pid = _parse_uuid(plan_id)
    if not pid:
        return fail("VALIDATION_ERROR", "plan_id 格式无效")

    plan = await db.get(GuidanceRecord, pid)
    if not plan:
        return fail("NOT_FOUND", "方案不存在", status_code=404)
    if plan.status == GuidanceStatus.PUBLISHED:
        return fail("BUSINESS_ERROR", "方案已处于 PUBLISHED 状态")
    if plan.status == GuidanceStatus.ARCHIVED:
        return fail("BUSINESS_ERROR", "已归档方案不可重新发布")

    # 归档旧 PUBLISHED 方案
    old_published = (await db.execute(
        select(GuidanceRecord)
        .where(
            GuidanceRecord.patient_id == plan.patient_id,
            GuidanceRecord.guidance_type == GuidanceType.GUIDANCE,
            GuidanceRecord.status == GuidanceStatus.PUBLISHED,
            GuidanceRecord.id != plan.id,
        )
    )).scalars().all()

    archived_count = 0
    for old in old_published:
        old.status = GuidanceStatus.ARCHIVED
        db.add(old)
        archived_count += 1

    plan.status = GuidanceStatus.PUBLISHED
    db.add(plan)
    await db.commit()

    return ok({
        "plan_id": plan_id,
        "status": "PUBLISHED",
        "archived_previous": archived_count,
        "message": f"方案已发布，归档了 {archived_count} 个历史版本",
    })


@router.get("/plan/{plan_id}/summary")
async def render_plan_summary(
    plan_id: str,
    format: Literal["his_text", "patient_text"] = Query(default="patient_text"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    渲染方案摘要。
    his_text    → HIS 病历风格（纯文本，无 Markdown）
    patient_text → 患者友好版（保留结构，精简表达）
    """
    pid = _parse_uuid(plan_id)
    if not pid:
        return fail("VALIDATION_ERROR", "plan_id 格式无效")

    plan = await db.get(GuidanceRecord, pid)
    if not plan:
        return fail("NOT_FOUND", "方案不存在", status_code=404)

    raw = plan.content

    if format == "his_text":
        # 去除 Markdown 标记，生成 HIS 可粘贴纯文本
        text = re.sub(r"#{1,6}\s*", "", raw)          # 去标题 #
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)  # 去加粗
        text = re.sub(r"\*(.*?)\*", r"\1", text)       # 去斜体
        text = re.sub(r"`(.*?)`", r"\1", text)         # 去代码
        text = re.sub(r">\s*", "", text)               # 去引用
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        summary = text[:300] + "..." if len(text) > 300 else text

    else:  # patient_text
        # 保留结构，去掉技术标记，语言口语化
        text = re.sub(r"#{1,3}\s*(.*)", r"【\1】", raw)
        text = re.sub(r"#{4,6}\s*(.*)", r"- \1", text)
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"\*(.*?)\*", r"\1", text)
        text = re.sub(r">`.*?`", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        summary = text[:400] + "..." if len(text) > 400 else text

    return ok({
        "plan_id": plan_id,
        "title": plan.title,
        "status": plan.status.value,
        "format": format,
        "summary": summary,
        "full_length": len(raw),
    })


# ══════════════════════════════════════════════════════════════════════════════
# D. Template — 指导/干预/宣教模板库
# ══════════════════════════════════════════════════════════════════════════════

_TEMPLATE_TYPE_MAP = {
    "plan": GuidanceType.GUIDANCE,
    "followup": None,   # 随访模板暂用 GUIDANCE 兜底
    "reply": GuidanceType.EDUCATION,
}


@router.get("/template/list")
async def list_templates(
    type: Literal["plan", "followup", "reply"] | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """列出模板（按类型筛选）"""
    filters = [GuidanceTemplate.is_active == True]
    if type and type in _TEMPLATE_TYPE_MAP:
        gtype = _TEMPLATE_TYPE_MAP[type]
        if gtype:
            filters.append(GuidanceTemplate.guidance_type == gtype)
    if q:
        filters.append(
            or_(
                GuidanceTemplate.name.ilike(f"%{q}%"),
                GuidanceTemplate.tags.ilike(f"%{q}%"),
            )
        )

    total = await db.scalar(
        select(func.count(GuidanceTemplate.id)).where(and_(*filters))
    )
    rows = (await db.execute(
        select(GuidanceTemplate).where(and_(*filters))
        .order_by(GuidanceTemplate.name)
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    return ok({
        "total": total,
        "items": [
            {
                "template_id": str(t.id),
                "name": t.name,
                "guidance_type": t.guidance_type.value,
                "scope": t.scope.value,
                "tags": t.tags,
                "content_preview": t.content[:100] + "..." if len(t.content) > 100 else t.content,
                "created_at": t.created_at.isoformat(),
            }
            for t in rows
        ],
    })


@router.get("/template/{template_id}")
async def get_template(
    template_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """获取模板完整内容"""
    tid = _parse_uuid(template_id)
    if not tid:
        return fail("VALIDATION_ERROR", "template_id 格式无效")

    t = await db.get(GuidanceTemplate, tid)
    if not t or not t.is_active:
        return fail("NOT_FOUND", "模板不存在", status_code=404)

    return ok({
        "template_id": template_id,
        "name": t.name,
        "guidance_type": t.guidance_type.value,
        "scope": t.scope.value,
        "tags": t.tags,
        "content": t.content,
        "created_at": t.created_at.isoformat(),
    })


# ══════════════════════════════════════════════════════════════════════════════
# E. Follow-up — 随访计划与任务
# ══════════════════════════════════════════════════════════════════════════════

class CreateFollowupPlanRequest(BaseModel):
    patient_id: str
    disease_type: str = "HYPERTENSION"
    cadence_days: int = 7   # 随访频率（每隔 N 天）
    total_weeks: int = 4    # 计划持续周数
    items: list[str] = []   # 随访项目名称列表（为空则用默认）


@router.post("/followup/plan")
async def create_followup_plan(
    body: CreateFollowupPlanRequest,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    为患者创建随访计划。
    cadence_days：随访间隔天数
    total_weeks：计划总周数（决定结束时间）
    items：随访任务名称列表（可选，不填则自动生成默认任务）
    """
    aid = _parse_uuid(body.patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    if not archive.user_id:
        return fail("BUSINESS_ERROR", "该患者档案未关联系统用户")

    # 验证 disease_type
    try:
        dtype = DiseaseType(body.disease_type)
    except ValueError:
        return fail("VALIDATION_ERROR", f"不支持的 disease_type：{body.disease_type}")

    today = date.today()
    end_date = today + timedelta(weeks=body.total_weeks)

    plan = FollowupPlan(
        user_id=archive.user_id,
        disease_type=dtype,
        status=FollowupStatus.ACTIVE,
        start_date=today,
        end_date=end_date,
        note=f"插件端创建随访计划（间隔{body.cadence_days}天，共{body.total_weeks}周）",
    )
    db.add(plan)
    await db.flush()

    # 按 cadence 生成任务
    default_items = body.items or ["指标上报", "服药依从性"]
    tasks_created: list[dict] = []
    current_date = today + timedelta(days=body.cadence_days)

    while current_date <= end_date:
        for item_name in default_items:
            task = FollowupTask(
                plan_id=plan.id,
                task_type=TaskType.INDICATOR_REPORT,
                name=item_name,
                scheduled_date=current_date,
                required=True,
                meta={"source": "plugin", "cadence_days": body.cadence_days},
            )
            db.add(task)
            tasks_created.append({
                "scheduled_date": str(current_date),
                "name": item_name,
            })
        current_date += timedelta(days=body.cadence_days)

    await db.commit()
    await db.refresh(plan)

    return ok({
        "plan_id": str(plan.id),
        "patient_id": body.patient_id,
        "disease_type": dtype.value,
        "start_date": str(today),
        "end_date": str(end_date),
        "cadence_days": body.cadence_days,
        "tasks_created": len(tasks_created),
        "task_schedule": tasks_created[:5],  # 展示前5条预览
    })


@router.get("/followup/tasks/{patient_id}")
async def list_followup_tasks(
    patient_id: str,
    status: str | None = Query(default=None, description="pending / done / missed / all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    列出患者随访任务。
    status 筛选：pending（未来任务）/ done（已完成）/ missed（已逾期）/ all
    """
    aid = _parse_uuid(patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    if not archive.user_id:
        return ok({"total": 0, "items": []})

    # 找到该患者所有随访计划
    plan_ids_rows = (await db.execute(
        select(FollowupPlan.id).where(FollowupPlan.user_id == archive.user_id)
    )).scalars().all()

    if not plan_ids_rows:
        return ok({"total": 0, "items": []})

    today = date.today()
    task_filters = [FollowupTask.plan_id.in_(plan_ids_rows)]

    if status == "pending":
        task_filters.append(FollowupTask.scheduled_date >= today)
    elif status == "missed":
        task_filters.append(FollowupTask.scheduled_date < today)
    # "done" and "all" handled via checkin join — simplified here

    total = await db.scalar(
        select(func.count(FollowupTask.id)).where(and_(*task_filters))
    )
    tasks = (await db.execute(
        select(FollowupTask).where(and_(*task_filters))
        .order_by(FollowupTask.scheduled_date.asc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    task_items = [
        {
            "task_id": str(t.id),
            "plan_id": str(t.plan_id),
            "name": t.name,
            "task_type": t.task_type.value,
            "scheduled_date": str(t.scheduled_date),
            "required": t.required,
            "is_overdue": t.scheduled_date < today,
            "meta": t.meta,
        }
        for t in tasks
    ]

    return ok({"total": total, "patient_id": patient_id, "items": task_items})
