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

import asyncio
import difflib
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, AsyncIterator, Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
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
from app.models.followup import CheckIn, FollowupPlan, FollowupTask
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
    """搜索患者档案（支持 archive_id / 姓名 / 手机 / 证件）"""
    # 优先：query 是 archive id（32位hex），精确匹配
    aid = _parse_uuid(query)
    if aid:
        row = await db.get(PatientArchive, aid)
        if row and not row.is_deleted:
            return ok({"total": 1, "items": [_archive_brief(row)]})
        return ok({"total": 0, "items": []})

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
            sec_list = ca.secondary_types if isinstance(ca.secondary_types, list) else []
            constitution = {
                "main_type": ca.main_type.value,
                "main_type_cn": _BODY_TYPE_CN.get(ca.main_type.value, ca.main_type.value),
                "secondary_types": [
                    {"type": t, "type_cn": _BODY_TYPE_CN.get(t, t)}
                    for t in sec_list if isinstance(t, str)
                ],
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

    # ── 过敏史 ──
    allergy_list: list[str] = []
    raw_allergy = archive.allergy_history
    if isinstance(raw_allergy, list):
        allergy_list = [str(a) for a in raw_allergy if a]
    elif isinstance(raw_allergy, str) and raw_allergy.strip():
        allergy_list = [raw_allergy]

    alert_tags: list[dict] = []
    disease_tags: list[str] = []
    contraindication_alerts: list[dict] = []
    comorbidity_alerts: list[dict] = []

    if archive.user_id:
        # ── 未处置预警（近期异常指标）──
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

        # ── 慢病 + 禁忌 + 共病 ──
        diseases = (await db.execute(
            select(ChronicDiseaseRecord)
            .where(
                ChronicDiseaseRecord.user_id == archive.user_id,
                ChronicDiseaseRecord.is_active == True,
            )
        )).scalars().all()

        for d in diseases:
            disease_cn = _DISEASE_CN.get(d.disease_type.value, d.disease_type.value)
            disease_tags.append(disease_cn)

            # 禁忌：从 notes JSON 的 contraindications 字段提取
            if d.notes:
                try:
                    notes_obj = json.loads(d.notes)
                    for item in (notes_obj.get("contraindications") or []):
                        contraindication_alerts.append({"disease": disease_cn, "item": item})
                except (json.JSONDecodeError, AttributeError):
                    pass

            # 共病：从 complications 字段提取
            complications = d.complications or []
            if isinstance(complications, str):
                try:
                    complications = json.loads(complications)
                except json.JSONDecodeError:
                    complications = [complications]
            for comp in complications:
                if comp:
                    comorbidity_alerts.append({"disease": disease_cn, "complication": str(comp)})

        # ── 依从性：近30天随访任务完成率 ──
        today = date.today()
        cutoff = today - timedelta(days=30)
        past_tasks = (await db.execute(
            select(FollowupTask)
            .join(FollowupPlan, FollowupTask.plan_id == FollowupPlan.id)
            .where(
                FollowupPlan.user_id == archive.user_id,
                FollowupTask.scheduled_date < today,
                FollowupTask.scheduled_date >= cutoff,
                FollowupTask.required == True,
            )
        )).scalars().all()

        adherence_alert: dict | None = None
        if past_tasks:
            task_ids = [t.id for t in past_tasks]
            done_checkins = (await db.execute(
                select(func.count()).select_from(CheckIn).where(
                    CheckIn.task_id.in_(task_ids),
                    CheckIn.status == "DONE",
                )
            )).scalar() or 0
            total = len(past_tasks)
            rate = round(done_checkins / total * 100)
            risk_lv = "HIGH" if rate < 60 else ("MEDIUM" if rate < 80 else "LOW")
            adherence_alert = {
                "done_count": done_checkins,
                "total_count": total,
                "rate_pct": rate,
                "risk_level": risk_lv,
                "text": f"近30天随访完成率 {rate}%，{'依从性偏低，需关注' if risk_lv != 'LOW' else '依从性良好'}",
            }

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
        "key_alerts": {
            "allergy": allergy_list,
            "contraindications": contraindication_alerts,
            "comorbidities": comorbidity_alerts,
            "indicator_alerts": alert_tags,          # 复用，前端按 severity 分类
            "adherence": adherence_alert,
        },
    })


# ──────────────────────────────────────────────────────────────────────────────
# B-extra-0. AI 风险结论（Step 5 风险提示推理）
# ──────────────────────────────────────────────────────────────────────────────

async def _ai_generate_risk_conclusions(patient_summary: str, api_key: str) -> list[dict] | None:
    """
    调用 AI 生成 3-6 条结构化风险结论标签。
    支持 Zhipu/GLM（OpenAI 兼容）和 Anthropic Claude，通过 _ai_call() 统一调用。
    返回 None 时由规则引擎降级。
    """
    system_prompt = (
        "你是中医慢病管理平台的AI风险分析助手。\n"
        "根据患者数据，生成3-6条精准的风险结论标签，供医生快速决策。\n"
        "输出格式：严格JSON数组，无任何额外文字或代码块标记。\n"
        "每条包含三个字段：\n"
        "- label: 显示文字，简洁精准，8字以内，"
        "示例：代谢风险中高 / 血压控制欠佳 / 依从性偏低 / 中医痰湿夹瘀\n"
        "- category: 维度，选自：代谢、心血管、肾脏、血糖、血压、血脂、依从性、中医、体重、营养\n"
        "- level: 严重程度，high/medium/low 之一\n"
        "要求：\n"
        "1. 优先标注 HIGH 严重度指标；\n"
        "2. 中医体质特征单独一条；\n"
        "3. 依从性风险单独一条（如有随访数据）；\n"
        "4. label 须含具体维度+程度描述，不能只写高风险。"
    )
    raw = await _ai_call(system_prompt, patient_summary, max_tokens=512)
    if raw is None:
        return None
    try:
        json_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not json_match:
            return None
        parsed = json.loads(json_match.group())
        valid = [
            {
                "label":    str(c.get("label", "")).strip(),
                "category": str(c.get("category", "综合")).strip(),
                "level":    str(c.get("level", "medium")).lower(),
            }
            for c in parsed
            if isinstance(c, dict) and c.get("label")
        ]
        return valid or None
    except Exception:
        return None



def _rule_based_risk_conclusions(
    diseases: list,
    ca,
    alert_msgs: list[str],
    adherence_text: str,
    hp,
) -> list[dict]:
    """无 API KEY 或 AI 调用失败时的规则引擎降级。"""
    results: list[dict] = []
    disease_values = {d.disease_type.value for d in diseases}

    # 代谢
    if "HYPERTENSION" in disease_values and "DIABETES_T2" in disease_values:
        results.append({"label": "代谢综合征风险高", "category": "代谢", "level": "high"})
    elif "DYSLIPIDEMIA" in disease_values or "DIABETES_T2" in disease_values:
        results.append({"label": "代谢风险中等", "category": "代谢", "level": "medium"})

    # 血压
    if "HYPERTENSION" in disease_values:
        has_high_bp = any("血压" in m and "[HIGH]" in m for m in alert_msgs)
        lv = "high" if has_high_bp else "medium"
        results.append({"label": f"血压控制{'欠佳' if lv == 'high' else '待优化'}", "category": "血压", "level": lv})

    # 心脑血管
    if "CORONARY_HEART_DISEASE" in disease_values or "CEREBROVASCULAR_DISEASE" in disease_values:
        results.append({"label": "心脑血管风险高", "category": "心血管", "level": "high"})

    # 肾脏
    if "CHRONIC_KIDNEY_DISEASE" in disease_values:
        results.append({"label": "慢性肾病需监控", "category": "肾脏", "level": "high"})

    # 依从性
    if adherence_text:
        m = re.search(r'(\d+)', adherence_text)
        if m:
            rate = int(m.group(1))
            if rate < 60:
                results.append({"label": "管理依从性高风险", "category": "依从性", "level": "high"})
            elif rate < 80:
                results.append({"label": "管理依从性中风险", "category": "依从性", "level": "medium"})

    # BMI
    if hp and hp.bmi and hp.bmi >= 28:
        results.append({"label": "超重/肥胖风险", "category": "体重", "level": "medium"})

    # 中医体质
    if ca and ca.main_type:
        cn = _BODY_TYPE_CN.get(ca.main_type.value, "")
        if cn and cn != "平和质":
            tcm_label_map = {
                "气虚质": "中医气虚倾向",    "阳虚质": "中医阳虚偏寒",
                "阴虚质": "中医阴虚内热",    "痰湿质": "中医偏虚夹湿倾向",
                "湿热质": "中医湿热内蕴",    "血瘀质": "中医血瘀倾向",
                "气郁质": "中医气郁体质",    "特禀质": "中医特禀过敏体质",
            }
            results.append({"label": tcm_label_map.get(cn, f"中医{cn}倾向"), "category": "中医", "level": "low"})

    return results or [{"label": "综合风险待评估", "category": "综合", "level": "low"}]


@router.get("/patient/{patient_id}/risk-conclusions")
async def get_patient_risk_conclusions(
    patient_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    AI 风险结论生成：基于患者全量数据，产出 3-6 条精准风险标签。
    无 ANTHROPIC_API_KEY 时降级为规则引擎。
    """
    aid = _parse_uuid(patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    # ── 并行收集数据 ──────────────────────────────────────────────────────────
    ca_q    = select(ConstitutionAssessment).where(
        ConstitutionAssessment.user_id == archive.user_id
    ).order_by(desc(ConstitutionAssessment.scored_at)).limit(1)
    disease_q = select(ChronicDiseaseRecord).where(
        ChronicDiseaseRecord.user_id == archive.user_id,
        ChronicDiseaseRecord.is_active == True,
    )
    alert_q = select(AlertEvent).where(
        AlertEvent.user_id == archive.user_id,
        AlertEvent.status == AlertStatus.OPEN,
    ).order_by(desc(AlertEvent.created_at)).limit(8)
    hp_q    = select(HealthProfile).where(HealthProfile.user_id == archive.user_id)

    ca_res, dis_res, alert_res, hp_res = await asyncio.gather(
        db.execute(ca_q),
        db.execute(disease_q),
        db.execute(alert_q),
        db.execute(hp_q),
    )
    ca       = ca_res.scalar_one_or_none()
    diseases = list(dis_res.scalars().all())
    alerts   = list(alert_res.scalars().all())
    hp       = hp_res.scalar_one_or_none()

    # ── 依从性 ────────────────────────────────────────────────────────────────
    adherence_text = ""
    if archive.user_id:
        today  = date.today()
        cutoff = today - timedelta(days=30)
        tasks  = (await db.execute(
            select(FollowupTask)
            .join(FollowupPlan, FollowupTask.plan_id == FollowupPlan.id)
            .where(
                FollowupPlan.user_id  == archive.user_id,
                FollowupTask.scheduled_date < today,
                FollowupTask.scheduled_date >= cutoff,
                FollowupTask.required == True,
            )
        )).scalars().all()
        if tasks:
            done = (await db.execute(
                select(func.count()).select_from(CheckIn).where(
                    CheckIn.task_id.in_([t.id for t in tasks]),
                    CheckIn.status == "DONE",
                )
            )).scalar() or 0
            adherence_text = f"近30天随访完成率{round(done / len(tasks) * 100)}%"

    # ── 构建 prompt 摘要 ──────────────────────────────────────────────────────
    const_str = ""
    if ca and ca.main_type:
        main_cn = _BODY_TYPE_CN.get(ca.main_type.value, ca.main_type.value)
        sec_list = ca.secondary_types if isinstance(ca.secondary_types, list) else []
        sec_cn   = "、".join(_BODY_TYPE_CN.get(t, t) for t in sec_list if isinstance(t, str))
        const_str = main_cn + (f"，兼夹{sec_cn}" if sec_cn else "")

    disease_str = "、".join(
        _DISEASE_CN.get(d.disease_type.value, d.disease_type.value) for d in diseases
    ) or "无"

    compl_parts: list[str] = []
    for d in diseases:
        comps = d.complications or []
        if isinstance(comps, str):
            try:    comps = json.loads(comps)
            except: comps = [comps]
        dcn = _DISEASE_CN.get(d.disease_type.value, d.disease_type.value)
        for c in (comps or []):
            if c:
                compl_parts.append(f"{dcn}→{c}")

    alert_lines = [f"[{e.severity.value}] {e.message}" for e in alerts]

    allergy_str = (
        "、".join(archive.allergy_history) if isinstance(archive.allergy_history, list)
        else (archive.allergy_history or "无")
    )

    patient_summary = (
        f"患者信息摘要：\n"
        f"- 体质：{const_str or '未评估'}\n"
        f"- 慢病诊断：{disease_str}\n"
        f"- 并发症：{'；'.join(compl_parts) or '无'}\n"
        f"- 近期异常预警：{chr(10).join(alert_lines) if alert_lines else '无'}\n"
        f"- 依从性：{adherence_text or '无随访记录'}\n"
        f"- BMI：{str(hp.bmi) if hp and hp.bmi else '未知'}\n"
        f"- 过敏史：{allergy_str}"
    )

    from app.config import settings
    conclusions = await _ai_generate_risk_conclusions(patient_summary, settings.anthropic_api_key)
    if conclusions is None:
        conclusions = _rule_based_risk_conclusions(diseases, ca, alert_lines, adherence_text, hp)

    return ok({"patient_id": patient_id, "conclusions": conclusions})


# ──────────────────────────────────────────────────────────────────────────────
# B-extra. 补充采集（Step 4）
# ──────────────────────────────────────────────────────────────────────────────

class SupplementRequest(BaseModel):
    # 生活方式快速勾选
    sedentary: str | None = None          # 久坐：often/sometimes/rarely
    exercise_frequency: str | None = None  # 运动频率：never/occasional/regular
    sleep_quality: str | None = None       # 睡眠质量（中文或 poor/average/good）
    stress_level: str | None = None        # 压力：high/medium/low
    # 中医四诊（结构化）
    tongue_color: str | None = None        # 舌色：淡红/红/暗红/淡白/紫暗
    tongue_coating: str | None = None      # 舌苔：薄白/薄黄/厚腻/黄腻/无苔
    tongue: str | None = None              # 舌象自由文字（兼容旧版）
    pulse: str | None = None               # 脉象（如：弦细）
    stool: str | None = None               # 大便：正常/干结/稀溏/不成形
    urine: str | None = None               # 小便：正常/频多/短黄/夜尿多
    sizhen_summary: str | None = None      # 四诊综合摘要
    chief_complaint: str | None = None     # 主诉症状
    # 经济评估
    budget_tier: str | None = None        # low/medium/high
    visit_frequency: str | None = None    # monthly/quarterly/biannual


@router.post("/patient/{patient_id}/supplement")
async def supplement_patient_info(
    patient_id: str,
    body: SupplementRequest,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    补充采集患者信息：
    - 写入 patient_archives.tags（追加）
    - 更新 health_profiles 生活方式字段
    - 返回结构化补充摘要
    """
    aid = _parse_uuid(patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    # 追加标签
    new_tags: list[str] = []
    if body.sedentary:       new_tags.append(f"久坐:{body.sedentary}")
    if body.stress_level:    new_tags.append(f"压力:{body.stress_level}")
    if body.budget_tier:     new_tags.append(f"预算:{body.budget_tier}")
    # 四诊结构化字段
    tongue_text = body.tongue or ""
    if body.tongue_color:   tongue_text = f"{body.tongue_color}舌" + (f"，苔{body.tongue_coating}" if body.tongue_coating else "")
    elif body.tongue_coating: tongue_text = f"苔{body.tongue_coating}"
    if tongue_text:          new_tags.append(f"舌象:{tongue_text[:20]}")
    if body.pulse:           new_tags.append(f"脉象:{body.pulse[:20]}")
    if body.sleep_quality:   new_tags.append(f"睡眠:{body.sleep_quality}")
    if body.stool:           new_tags.append(f"大便:{body.stool}")
    if body.urine:           new_tags.append(f"小便:{body.urine}")
    if body.sizhen_summary:  new_tags.append(f"四诊:{body.sizhen_summary[:40]}")
    if body.chief_complaint: new_tags.append(f"主诉:{body.chief_complaint[:40]}")

    existing_tags = archive.tags or []
    archive.tags = existing_tags + [t for t in new_tags if t not in existing_tags]
    db.add(archive)

    # 更新 HealthProfile（如存在）
    hp_user_id = archive.user_id
    hp_updated = False
    if hp_user_id:
        hp = (await db.execute(
            select(HealthProfile).where(HealthProfile.user_id == hp_user_id)
        )).scalar_one_or_none()
        if hp:
            if body.exercise_frequency:
                hp.exercise_frequency = body.exercise_frequency
                hp_updated = True
            db.add(hp)

    await db.commit()

    summary_parts = []
    if body.sedentary:       summary_parts.append(f"久坐习惯：{body.sedentary}")
    if body.exercise_frequency: summary_parts.append(f"运动频率：{body.exercise_frequency}")
    if body.sleep_quality:   summary_parts.append(f"睡眠质量：{body.sleep_quality}")
    if body.stress_level:    summary_parts.append(f"压力水平：{body.stress_level}")
    if body.tongue:          summary_parts.append(f"舌象：{body.tongue}")
    if body.pulse:           summary_parts.append(f"脉象：{body.pulse}")
    if body.chief_complaint: summary_parts.append(f"主诉：{body.chief_complaint}")
    if body.budget_tier:     summary_parts.append(f"经济档位：{body.budget_tier}")
    if body.visit_frequency: summary_parts.append(f"就诊频率偏好：{body.visit_frequency}")

    return ok({
        "patient_id": patient_id,
        "tags_added": new_tags,
        "health_profile_updated": hp_updated,
        "summary": "；".join(summary_parts),
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
        "updated_at": (r.updated_at or r.created_at).isoformat(),
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

    # 无 user_id 时用 archive.id 作为 patient_id（SQLite 不强制 FK）
    pid_filter = archive.user_id if archive.user_id else archive.id

    filters = [
        GuidanceRecord.patient_id == pid_filter,
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

    pid_filter = archive.user_id if archive.user_id else archive.id

    plan = (await db.execute(
        select(GuidanceRecord)
        .where(
            GuidanceRecord.patient_id == pid_filter,
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

    # 无关联用户时用 archive.id 作为方案归属（SQLite 不强制 FK，演示可用）
    plan_patient_id = archive.user_id if archive.user_id else archive.id

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
        patient_id=plan_patient_id,
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
    if plan.status == GuidanceStatus.CONFIRMED:
        return fail("BUSINESS_ERROR", "已确认方案请通过分发流程处理")
    if plan.status == GuidanceStatus.DISTRIBUTED:
        return fail("BUSINESS_ERROR", "已分发方案不可重新发布")
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
    format: Literal["his_text", "patient_text", "raw"] = Query(default="patient_text"),
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

    if format == "raw":
        return ok({
            "plan_id": plan_id,
            "title": plan.title,
            "status": plan.status.value,
            "format": format,
            "summary": raw,
            "full_length": len(raw),
        })

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


# ──────────────────────────────────────────────────────────────────────────────
# C-extra. Plan Preview / Confirm / Distribute
# ──────────────────────────────────────────────────────────────────────────────

def _to_his_text(raw: str) -> str:
    """将 Markdown 方案内容转换为 HIS 可粘贴纯文本。"""
    text = re.sub(r"#{1,6}\s*", "", raw)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    text = re.sub(r">\s*", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _to_patient_text(raw: str) -> str:
    """将 Markdown 方案内容转换为患者友好版。"""
    text = re.sub(r"#{1,3}\s*(.*)", r"【\1】", raw)
    text = re.sub(r"#{4,6}\s*(.*)", r"- \1", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r">`.*?`", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _extract_modules(raw: str) -> dict:
    """从方案内容中提取结构化管理端字段（简单关键词匹配）。"""
    syndrome = ""
    risk_level = ""
    followup_days = 7
    modules: list[str] = []

    for line in raw.splitlines():
        ln = line.strip()
        if not syndrome and ("证候" in ln or "证型" in ln or "主证" in ln):
            syndrome = ln
        if not risk_level and ("高风险" in ln or "中风险" in ln or "低风险" in ln):
            if "高风险" in ln:
                risk_level = "HIGH"
            elif "中风险" in ln:
                risk_level = "MEDIUM"
            else:
                risk_level = "LOW"
        for kw in ["作息", "饮食", "运动", "情志", "穴位", "艾灸", "到院"]:
            if kw in ln and kw not in modules:
                modules.append(kw)

    m = re.search(r"随访[：:]\s*(\d+)\s*天", raw)
    if m:
        followup_days = int(m.group(1))

    return {
        "syndrome": syndrome or "—",
        "risk_level": risk_level or "MEDIUM",
        "followup_days": followup_days,
        "modules": modules,
    }


@router.get("/plan/{plan_id}/preview")
async def preview_plan(
    plan_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    三端预览：返回 HIS 版、患者 H5 版、管理端结构化字段，以及变更清单。
    """
    pid = _parse_uuid(plan_id)
    if not pid:
        return fail("VALIDATION_ERROR", "plan_id 格式无效")

    plan = await db.get(GuidanceRecord, pid)
    if not plan:
        return fail("NOT_FOUND", "方案不存在", status_code=404)

    raw = plan.content
    his_text = _to_his_text(raw)
    patient_h5 = _to_patient_text(raw)
    management = _extract_modules(raw)

    change_list = [
        "创建方案记录（状态→DISTRIBUTED）",
        "患者 H5 端更新当前方案（is_read=False）",
        "管理端写入干预记录（intervention_records）",
        f"自动生成随访计划（间隔 {management['followup_days']} 天）",
    ]

    return ok({
        "plan_id": plan_id,
        "title": plan.title,
        "status": plan.status.value,
        "his_text": his_text,
        "patient_h5": patient_h5,
        "management": management,
        "change_list": change_list,
    })


@router.post("/plan/{plan_id}/confirm")
async def confirm_plan(
    plan_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    确认方案：DRAFT → CONFIRMED。
    状态锁定，此后只能通过 /distribute 或手动归档更改状态。
    """
    pid = _parse_uuid(plan_id)
    if not pid:
        return fail("VALIDATION_ERROR", "plan_id 格式无效")

    plan = await db.get(GuidanceRecord, pid)
    if not plan:
        return fail("NOT_FOUND", "方案不存在", status_code=404)
    if plan.status != GuidanceStatus.DRAFT:
        return fail("BUSINESS_ERROR", f"只有草稿状态可确认，当前：{plan.status.value}")

    plan.status = GuidanceStatus.CONFIRMED
    db.add(plan)
    await db.commit()

    return ok({
        "plan_id": plan_id,
        "status": "CONFIRMED",
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    })


class DistributeRequest(BaseModel):
    targets: list[str] = ["his", "patient_h5", "management"]
    auto_followup_days: int = 7


@router.post("/plan/{plan_id}/distribute")
async def distribute_plan(
    plan_id: str,
    body: DistributeRequest,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    一键分发：CONFIRMED → DISTRIBUTED。
    按 targets 列表依次处理各端，并按 auto_followup_days 自动生成随访计划。
    """
    pid = _parse_uuid(plan_id)
    if not pid:
        return fail("VALIDATION_ERROR", "plan_id 格式无效")

    plan = await db.get(GuidanceRecord, pid)
    if not plan:
        return fail("NOT_FOUND", "方案不存在", status_code=404)
    if plan.status != GuidanceStatus.CONFIRMED:
        return fail("BUSINESS_ERROR", f"只有已确认方案可分发，当前：{plan.status.value}")

    results: dict = {}
    raw = plan.content

    # his：纯文本摘要，不写库
    if "his" in body.targets:
        his_text = _to_his_text(raw)
        results["his"] = {"ok": True, "summary": his_text[:200]}

    # patient_h5：标记方案为 DISTRIBUTED，患者可见
    if "patient_h5" in body.targets:
        plan.status = GuidanceStatus.DISTRIBUTED
        plan.is_read = False
        db.add(plan)
        results["patient_h5"] = {"ok": True, "message": "已推送给患者"}

    # management：写入干预记录
    intervention_id = None
    if "management" in body.targets:
        mgmt = _extract_modules(raw)
        intervention = GuidanceRecord(
            patient_id=plan.patient_id,
            doctor_id=current_user.id,
            guidance_type=GuidanceType.INTERVENTION,
            title=f"[分发] {plan.title}",
            content=raw,
            status=GuidanceStatus.PUBLISHED,
            is_read=False,
        )
        db.add(intervention)
        await db.flush()
        intervention_id = str(intervention.id)
        results["management"] = {"ok": True, "intervention_id": intervention_id}

    await db.commit()

    # 自动生成随访计划
    followup_plan_id = None
    followup_created = False
    try:
        archive = (await db.execute(
            select(PatientArchive).where(
                or_(
                    PatientArchive.user_id == plan.patient_id,
                    PatientArchive.id == plan.patient_id,
                )
            ).limit(1)
        )).scalar_one_or_none()

        if archive:
            today = date.today()
            cadence = body.auto_followup_days
            end_date = today + timedelta(weeks=4)
            fp = FollowupPlan(
                user_id=plan.patient_id,
                disease_type=DiseaseType.HYPERTENSION,
                status=FollowupStatus.ACTIVE,
                start_date=today,
                end_date=end_date,
                note=f"分发方案自动随访（间隔{cadence}天）",
            )
            db.add(fp)
            await db.flush()
            task = FollowupTask(
                plan_id=fp.id,
                task_type=TaskType.INDICATOR_REPORT,
                name="指标上报",
                scheduled_date=today + timedelta(days=cadence),
                required=True,
                meta={"source": "distribute", "plan_id": plan_id},
            )
            db.add(task)
            await db.commit()
            followup_plan_id = str(fp.id)
            followup_created = True
    except Exception as _follow_exc:
        import logging as _log
        _log.getLogger(__name__).warning("随访计划自动创建失败: %s", _follow_exc)

    return ok({
        "plan_id": plan_id,
        "status": "DISTRIBUTED",
        "results": results,
        "followup_created": followup_created,
        "followup_plan_id": followup_plan_id,
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

    followup_user_id = archive.user_id if archive.user_id else archive.id

    # 验证 disease_type
    try:
        dtype = DiseaseType(body.disease_type)
    except ValueError:
        return fail("VALIDATION_ERROR", f"不支持的 disease_type：{body.disease_type}")

    today = date.today()
    end_date = today + timedelta(weeks=body.total_weeks)

    plan = FollowupPlan(
        user_id=followup_user_id,
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


# ══════════════════════════════════════════════════════════════════════════════
# F. Recall — 召回建议（基于 AlertEvent 推导召回动作）
# ══════════════════════════════════════════════════════════════════════════════

_RECALL_REASON_CN = {
    "HIGH": "高风险预警触发召回",
    "MEDIUM": "中风险预警触发召回",
    "LOW": "低风险例行召回",
}

_RECALL_ACTION_MAP = {
    "HIGH": "立即安排复诊，重新评估干预方案",
    "MEDIUM": "建议调整随访频率，复查关键指标",
    "LOW": "复评现有方案执行情况，更新健康档案",
}


def _alert_to_recall(alert: AlertEvent) -> dict:
    sev = alert.severity.value
    return {
        "recall_id": str(alert.id),
        "trigger_type": "ALERT_EVENT",
        "trigger_reason": _RECALL_REASON_CN.get(sev, "预警触发召回"),
        "severity": sev,
        "recommendation": _RECALL_ACTION_MAP.get(sev, "请医生评估处理"),
        "recommendation_payload": {
            "action": "reassess" if sev == "HIGH" else "adjust_followup",
            "priority": sev,
        },
        "evidence_summary": alert.message,
        "current_status": alert.status.value,
    }


@router.get("/recall/{patient_id}")
async def get_recall_suggestions(
    patient_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    获取患者当前待处理的召回建议（来自 OPEN 状态的 AlertEvent）。
    按严重程度降序排列，最多返回 10 条。
    """
    aid = _parse_uuid(patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    if not archive.user_id:
        return ok({"patient_id": patient_id, "total": 0, "items": []})

    alerts = (await db.execute(
        select(AlertEvent)
        .where(
            AlertEvent.user_id == archive.user_id,
            AlertEvent.status == AlertStatus.OPEN,
        )
        .order_by(desc(AlertEvent.created_at))
        .limit(10)
    )).scalars().all()

    return ok({
        "patient_id": patient_id,
        "total": len(alerts),
        "items": [_alert_to_recall(a) for a in alerts],
    })


class RecallActionRequest(BaseModel):
    action: str          # "accept" | "ignore"
    note: str = ""


@router.patch("/recall/{alert_id}/action")
async def handle_recall_action(
    alert_id: str,
    body: RecallActionRequest,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    处理召回建议：
    - action=accept  → 将 AlertEvent 标记为 ACKNOWLEDGED（已确认需要处理）
    - action=ignore  → 将 AlertEvent 标记为 RESOLVED（忽略本次召回）
    """
    aid = _parse_uuid(alert_id)
    if not aid:
        return fail("VALIDATION_ERROR", "alert_id 格式无效")

    alert = await db.get(AlertEvent, aid)
    if not alert:
        return fail("NOT_FOUND", "召回记录不存在", status_code=404)

    if body.action == "accept":
        alert.status = AlertStatus.ACKED
    elif body.action == "ignore":
        alert.status = AlertStatus.CLOSED
    else:
        return fail("VALIDATION_ERROR", f"不支持的 action：{body.action}，仅支持 accept / ignore")

    if body.note:
        alert.message = alert.message + f"\n[处理备注] {body.note}"

    db.add(alert)
    await db.commit()

    return ok({
        "alert_id": alert_id,
        "action": body.action,
        "new_status": alert.status.value,
        "note": body.note,
    })


# ══════════════════════════════════════════════════════════════════════════════
# G. Workbench — 工作台：待处理患者聚合视图（医生维度）
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/workbench/pending")
async def get_workbench_pending(
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    获取当前医生工作台待处理患者聚合视图。
    返回三类患者列表：
    - reassess_today：今日待复评（随访任务 scheduled_date=today 且未完成）
    - recall_triggered：已触发召回但未处理（OPEN 状态 HIGH/MEDIUM 预警）
    - followup_abnormal：随访异常（逾期未打卡）
    每类最多 10 条，按档案信息聚合。
    """
    from datetime import datetime, timezone
    today = date.today()

    # ── 1. 今日待复评：today 的随访任务（未完成）──────────────────────────
    today_tasks = (await db.execute(
        select(FollowupTask, FollowupPlan)
        .join(FollowupPlan, FollowupTask.plan_id == FollowupPlan.id)
        .where(
            FollowupTask.scheduled_date == today,
        )
        .order_by(FollowupTask.scheduled_date.asc())
        .limit(20)
    )).all()

    # 找出 user_id → archive
    reassess_user_ids = list({row.FollowupPlan.user_id for row in today_tasks})
    reassess_archives: dict = {}
    if reassess_user_ids:
        rows = (await db.execute(
            select(PatientArchive).where(
                PatientArchive.user_id.in_(reassess_user_ids),
                PatientArchive.is_deleted == False,
            )
        )).scalars().all()
        reassess_archives = {str(a.user_id): a for a in rows}

    reassess_today = []
    seen_uid = set()
    for row in today_tasks:
        uid = str(row.FollowupPlan.user_id)
        if uid in seen_uid:
            continue
        seen_uid.add(uid)
        a = reassess_archives.get(uid)
        if not a:
            continue
        reassess_today.append({
            "archive_id": str(a.id),
            "patient_name": a.name,
            "phone": a.phone,
            "pending_action": f"随访任务：{row.FollowupTask.name}",
            "risk_tag": "待复评",
            "recent_visit_at": str(row.FollowupTask.scheduled_date),
            "latest_status": "PENDING",
        })

    # ── 2. 已触发召回（OPEN HIGH/MEDIUM 预警）──────────────────────────────
    open_alerts = (await db.execute(
        select(AlertEvent)
        .where(AlertEvent.status == AlertStatus.OPEN)
        .order_by(desc(AlertEvent.created_at))
        .limit(30)
    )).scalars().all()

    recall_user_ids = [str(a.user_id) for a in open_alerts if a.user_id is not None]
    recall_user_ids = list(set(recall_user_ids))
    recall_archives: dict = {}
    if recall_user_ids:
        rows = (await db.execute(
            select(PatientArchive).where(
                PatientArchive.user_id.in_([_parse_uuid(uid) for uid in recall_user_ids if _parse_uuid(uid)]),
                PatientArchive.is_deleted == False,
            )
        )).scalars().all()
        recall_archives = {str(a.user_id): a for a in rows}

    recall_triggered = []
    seen_recall = set()
    for alert in open_alerts:
        uid = str(alert.user_id)
        if uid in seen_recall:
            continue
        seen_recall.add(uid)
        a = recall_archives.get(uid)
        if not a:
            continue
        recall_triggered.append({
            "archive_id": str(a.id),
            "patient_name": a.name,
            "phone": a.phone,
            "pending_action": f"处理召回：{alert.message[:40]}",
            "risk_tag": alert.severity.value,
            "recent_visit_at": alert.created_at.isoformat()[:10],
            "latest_status": "RECALL_OPEN",
        })
        if len(recall_triggered) >= 10:
            break

    # ── 3. 随访异常：逾期未打卡（scheduled_date < today）──────────────────
    overdue_tasks = (await db.execute(
        select(FollowupTask, FollowupPlan)
        .join(FollowupPlan, FollowupTask.plan_id == FollowupPlan.id)
        .where(
            FollowupTask.scheduled_date < today,
            FollowupPlan.status == FollowupStatus.ACTIVE,
        )
        .order_by(desc(FollowupTask.scheduled_date))
        .limit(20)
    )).all()

    overdue_user_ids = [str(row.FollowupPlan.user_id) for row in overdue_tasks if row.FollowupPlan.user_id is not None]
    overdue_user_ids = list(set(overdue_user_ids))
    overdue_archives: dict = {}
    if overdue_user_ids:
        rows = (await db.execute(
            select(PatientArchive).where(
                PatientArchive.user_id.in_([_parse_uuid(uid) for uid in overdue_user_ids if _parse_uuid(uid)]),
                PatientArchive.is_deleted == False,
            )
        )).scalars().all()
        overdue_archives = {str(a.user_id): a for a in rows}

    followup_abnormal = []
    seen_over = set()
    for row in overdue_tasks:
        uid = str(row.FollowupPlan.user_id)
        if uid in seen_over:
            continue
        seen_over.add(uid)
        a = overdue_archives.get(uid)
        if not a:
            continue
        followup_abnormal.append({
            "archive_id": str(a.id),
            "patient_name": a.name,
            "phone": a.phone,
            "pending_action": f"逾期随访：{row.FollowupTask.name}",
            "risk_tag": "随访异常",
            "recent_visit_at": str(row.FollowupTask.scheduled_date),
            "latest_status": "OVERDUE",
        })
        if len(followup_abnormal) >= 10:
            break

    return ok({
        "reassess_today": reassess_today[:10],
        "recall_triggered": recall_triggered[:10],
        "followup_abnormal": followup_abnormal[:10],
        "counts": {
            "reassess_today": len(reassess_today),
            "recall_triggered": len(recall_triggered),
            "followup_abnormal": len(followup_abnormal),
        },
    })


# ══════════════════════════════════════════════════════════════════════════════
# H. Feedback — 患者反馈摘要（最近打卡记录）
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/patient/{patient_id}/feedback")
async def get_patient_feedback(
    patient_id: str,
    limit: int = Query(default=5, ge=1, le=20),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    获取患者最近的随访打卡反馈（CheckIn记录）。
    返回最近 N 条带备注或异常值的打卡记录，作为患者反馈摘要。
    """
    from app.models.followup import CheckIn
    aid = _parse_uuid(patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    if not archive.user_id:
        return ok({"patient_id": patient_id, "total": 0, "items": []})

    checkins = (await db.execute(
        select(CheckIn)
        .where(CheckIn.user_id == archive.user_id)
        .order_by(desc(CheckIn.checked_at))
        .limit(limit)
    )).scalars().all()

    items = []
    for c in checkins:
        items.append({
            "checkin_id": str(c.id),
            "status": c.status.value,
            "value": c.value,
            "note": c.note or "",
            "checked_at": c.checked_at.isoformat() if c.checked_at else None,
            "created_at": c.created_at.isoformat(),
        })

    return ok({
        "patient_id": patient_id,
        "total": len(items),
        "items": items,
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


# ── F. Plugin Agent Stream ────────────────────────────────────────────────────

class PluginAgentRequest(BaseModel):
    query: str
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None


@router.post("/agent/stream")
async def plugin_agent_stream(
    body: PluginAgentRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_PRO),
):
    """
    Chrome 插件专用 SSE Agent 端点。
    使用服务器本地配置的 ANTHROPIC_API_KEY 和 ANTHROPIC_BASE_URL。
    事件格式与 /tools/agent/stream 相同。
    """
    from app.services.agent_service import run_agent_stream

    # 若提供了患者信息，拼入查询前缀方便 agent 定位
    query = body.query
    if body.patient_name:
        query = f"[当前患者：{body.patient_name}，档案ID：{body.patient_id or '未知'}] {query}"

    async def generate() -> AsyncIterator[str]:
        try:
            async for event in run_agent_stream(query, db, current_user):
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:
            err = {"type": "error", "message": f"Agent 执行出错：{exc}"}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# I. Package Recommendation — Step 12 套餐推荐
# ══════════════════════════════════════════════════════════════════════════════

_PACKAGE_TEMPLATES = {
    "online": {
        "name": "线上管理包",
        "cycle": "3个月",
        "items": ["每周线上随访（1次）", "指标智能监测", "中医健康日报推送", "在线问诊优先响应"],
        "reason_template": "适合{risk}风险患者，居家自我管理为主，成本较低",
        "script_template": "我们的线上管理包可以帮您在家就能得到专业指导，每周都有医生跟踪您的健康数据，有问题随时在线咨询。",
    },
    "onsite": {
        "name": "到院项目疗程",
        "cycle": "1个月",
        "items": ["针灸调理（每周2次）", "推拿理疗", "中药熏蒸", "体质专项评估"],
        "reason_template": "适合{constitution}体质患者，到院疗程针对性强",
        "script_template": "针对您的体质，我们设计了专属的到院疗程，通过针灸、推拿等方法来改善您的体质状态，效果会更直接。",
    },
    "comprehensive": {
        "name": "综合管理包",
        "cycle": "6个月",
        "items": ["每月到院随访（1次）", "每周线上指导（1次）", "个性化中药方案", "节气保健提醒", "年度健康评估"],
        "reason_template": "适合{risk}风险+慢病患者，线上线下结合，全方位管理",
        "script_template": "综合管理包是我们最全面的方案，结合线上监测和定期到院，特别适合您这种情况，能帮助您更好地控制病情，改善生活质量。",
    },
}


@router.get("/patient/{patient_id}/package-recommendation")
async def get_package_recommendation(
    patient_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    套餐推荐：基于风险等级 + 体质 + 慢病 → 匹配推荐套餐（3档）。
    """
    aid = _parse_uuid(patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    # 读取体质
    constitution_type = ""
    if archive.user_id:
        ca = (await db.execute(
            select(ConstitutionAssessment)
            .where(ConstitutionAssessment.user_id == archive.user_id)
            .order_by(desc(ConstitutionAssessment.created_at))
            .limit(1)
        )).scalar_one_or_none()
        if ca and ca.main_type:
            constitution_type = _BODY_TYPE_CN.get(ca.main_type.value if hasattr(ca.main_type, 'value') else str(ca.main_type), str(ca.main_type))

    # 读取慢病数量
    disease_count = 0
    if archive.user_id:
        disease_count = await db.scalar(
            select(func.count(ChronicDiseaseRecord.id))
            .where(ChronicDiseaseRecord.user_id == archive.user_id)
        ) or 0

    # 读取预警（推断风险）
    risk_level = "LOW"
    if archive.user_id:
        open_alerts = await db.scalar(
            select(func.count(AlertEvent.id))
            .where(AlertEvent.user_id == archive.user_id, AlertEvent.status == AlertStatus.OPEN)
        ) or 0
        if open_alerts >= 2 or disease_count >= 2:
            risk_level = "HIGH"
        elif open_alerts >= 1 or disease_count >= 1:
            risk_level = "MEDIUM"

    risk_cn = {"HIGH": "高", "MEDIUM": "中", "LOW": "低"}.get(risk_level, "中")
    const_cn = constitution_type or "气虚质"

    packages = []
    for tier, tpl in _PACKAGE_TEMPLATES.items():
        packages.append({
            "tier": tier,
            "name": tpl["name"],
            "cycle": tpl["cycle"],
            "items": tpl["items"],
            "reason": tpl["reason_template"].format(risk=risk_cn, constitution=const_cn),
            "script": tpl["script_template"],
            "recommended": (
                (risk_level == "LOW" and tier == "online") or
                (risk_level == "MEDIUM" and tier == "onsite") or
                (risk_level == "HIGH" and tier == "comprehensive")
            ),
        })

    return ok({
        "patient_id": patient_id,
        "risk_level": risk_level,
        "constitution_type": constitution_type,
        "disease_count": disease_count,
        "packages": packages,
    })


# ══════════════════════════════════════════════════════════════════════════════
# J. AI 驱动型插件接口（P0-P4）
# ══════════════════════════════════════════════════════════════════════════════

async def _ai_call(system_prompt: str, user_content: str, *, max_tokens: int = 512) -> str | None:
    """
    统一 AI 调用：支持 Zhipu/GLM（OpenAI 兼容格式）和 Anthropic Claude。
    无可用 API 时返回 None。
    """
    from app.config import settings
    api_key = settings.anthropic_api_key
    base_url = settings.anthropic_base_url
    model = settings.anthropic_model

    if not api_key:
        return None
    try:
        if base_url:
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    json={
                        "model": model,
                        "max_tokens": max_tokens,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                    },
                )
                if resp.status_code != 200:
                    return None
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
        else:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=api_key)
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )
            return response.content[0].text.strip()
    except Exception:
        return None


# ── P0: 患者一键摘要 ───────────────────────────────────────────────────────────

@router.get("/patient/{patient_id}/brief")
async def get_patient_brief(
    patient_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    患者一键摘要（AI 驱动）：
    汇聚档案 + 近期指标 + 风险标签 + 当前方案，
    由 AI 生成 2-3 句临床简报 + 3 条关键行动项。
    无 API KEY 时返回纯结构化数据（无 AI 摘要）。
    """
    aid = _parse_uuid(patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    user_id = archive.user_id
    today = date.today()
    cutoff_30 = today - timedelta(days=30)
    plan_patient_id = user_id if user_id else archive.id

    ca_res, dis_res, alert_res, plan_res, ind_res = await asyncio.gather(
        db.execute(
            select(ConstitutionAssessment)
            .where(ConstitutionAssessment.user_id == user_id)
            .order_by(desc(ConstitutionAssessment.scored_at))
            .limit(1)
        ) if user_id else asyncio.sleep(0),
        db.execute(
            select(ChronicDiseaseRecord)
            .where(ChronicDiseaseRecord.user_id == user_id, ChronicDiseaseRecord.is_active == True)
        ) if user_id else asyncio.sleep(0),
        db.execute(
            select(AlertEvent)
            .where(AlertEvent.user_id == user_id, AlertEvent.status == AlertStatus.OPEN)
            .order_by(desc(AlertEvent.created_at)).limit(5)
        ) if user_id else asyncio.sleep(0),
        db.execute(
            select(GuidanceRecord)
            .where(
                GuidanceRecord.patient_id == plan_patient_id,
                GuidanceRecord.guidance_type == GuidanceType.GUIDANCE,
                GuidanceRecord.status == GuidanceStatus.PUBLISHED,
            )
            .order_by(desc(GuidanceRecord.created_at)).limit(1)
        ),
        db.execute(
            select(HealthIndicator)
            .where(HealthIndicator.user_id == user_id, HealthIndicator.recorded_at >= cutoff_30)
            .order_by(desc(HealthIndicator.recorded_at)).limit(10)
        ) if user_id else asyncio.sleep(0),
    )

    ca       = ca_res.scalar_one_or_none()    if user_id and hasattr(ca_res, "scalar_one_or_none") else None
    diseases = list(dis_res.scalars().all())  if user_id and hasattr(dis_res, "scalars") else []
    alerts   = list(alert_res.scalars().all()) if user_id and hasattr(alert_res, "scalars") else []
    plan     = plan_res.scalar_one_or_none()
    indics   = list(ind_res.scalars().all())   if user_id and hasattr(ind_res, "scalars") else []

    age = None
    if archive.birth_date:
        age = today.year - archive.birth_date.year - (
            (today.month, today.day) < (archive.birth_date.month, archive.birth_date.day)
        )

    const_cn = _BODY_TYPE_CN.get(ca.main_type.value, "") if ca and ca.main_type else ""
    disease_list = [_DISEASE_CN.get(d.disease_type.value, d.disease_type.value) for d in diseases]
    alert_items = [
        {"severity": e.severity.value, "message": e.message, "at": e.created_at.isoformat()[:10]}
        for e in alerts
    ]

    indicator_summary: dict[str, dict] = {}
    for ind in indics:
        key = ind.indicator_type.value if hasattr(ind.indicator_type, "value") else str(ind.indicator_type)
        if key not in indicator_summary:
            vals = ind.values or {}
            if key == "BLOOD_PRESSURE":
                display = f"{vals.get('systolic','?')}/{vals.get('diastolic','?')} mmHg"
            elif key == "BLOOD_GLUCOSE":
                display = f"{vals.get('value','?')} mmol/L"
            elif key == "WEIGHT":
                display = f"{vals.get('value','?')} kg"
            else:
                display = str(vals.get("value", str(vals)))
            indicator_summary[key] = {
                "type_cn": _INDICATOR_CN.get(key, key),
                "display": display,
                "at": ind.recorded_at.isoformat()[:10] if ind.recorded_at else "",
            }

    plan_info = None
    if plan:
        plan_info = {
            "plan_id": str(plan.id),
            "title": plan.title,
            "created_at": plan.created_at.isoformat()[:10],
            "content_preview": (plan.content or "")[:200],
        }

    allergy_raw = archive.allergy_history
    if isinstance(allergy_raw, list):
        allergy_str = "、".join(str(a) for a in allergy_raw if a) or "无"
    else:
        allergy_str = str(allergy_raw) if allergy_raw else "无"

    gender_cn = "男" if archive.gender == "male" else ("女" if archive.gender == "female" else "未知")
    age_str = f"{age}岁" if age else "年龄未知"
    patient_text = (
        f"患者：{archive.name}，{gender_cn}，{age_str}\n"
        f"中医体质：{const_cn or '未评估'}\n"
        f"慢病诊断：{'、'.join(disease_list) or '无'}\n"
        f"当前方案：{plan_info['title'] if plan_info else '无'}\n"
        f"近期异常预警（{len(alert_items)}条）：{'；'.join(e['message'] for e in alert_items[:3]) if alert_items else '无'}\n"
        f"过敏史：{allergy_str}"
    )

    system_brief = (
        "你是中医慢病管理平台的临床决策助手。\n"
        "根据患者摘要，生成一份临床简报，格式为JSON：\n"
        '{"summary": "2-3句话的临床简报", "actions": ["行动建议1", "行动建议2", "行动建议3"]}\n'
        "summary 说明患者当前主要健康状态和管理重点；actions 每条15字以内，具体可操作。\n"
        "只输出JSON，不要有任何额外文字或代码块标记。"
    )

    ai_raw = await _ai_call(system_brief, patient_text, max_tokens=400)
    ai_brief = None
    if ai_raw:
        try:
            json_match = re.search(r'\{.*\}', ai_raw, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                if isinstance(parsed.get("summary"), str) and isinstance(parsed.get("actions"), list):
                    ai_brief = {
                        "summary": parsed["summary"].strip(),
                        "actions": [str(a).strip() for a in parsed["actions"][:3]],
                    }
        except Exception:
            pass

    return ok({
        "patient": {
            "patient_id": patient_id,
            "name": archive.name,
            "gender": archive.gender,
            "age": age,
            "phone": archive.phone,
            "constitution_cn": const_cn,
            "diseases": disease_list,
            "allergy": allergy_str,
            "archive_type": archive.archive_type.value if archive.archive_type else None,
        },
        "current_plan": plan_info,
        "alerts": alert_items,
        "indicators": list(indicator_summary.values()),
        "ai_brief": ai_brief,
    })


# ── P2: 方案变化建议 ───────────────────────────────────────────────────────────

@router.get("/plan/{plan_id}/delta-suggestion")
async def get_plan_delta_suggestion(
    plan_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    方案变化建议（AI 驱动）：
    基于当前方案内容 + 患者近30天指标变化，
    AI 生成 3-5 条具体的调整建议。
    """
    pid = _parse_uuid(plan_id)
    if not pid:
        return fail("VALIDATION_ERROR", "plan_id 格式无效")

    plan = await db.get(GuidanceRecord, pid)
    if not plan:
        return fail("NOT_FOUND", "方案不存在", status_code=404)

    patient_id = plan.patient_id
    today = date.today()
    cutoff = today - timedelta(days=30)

    archive = (await db.execute(
        select(PatientArchive).where(
            or_(PatientArchive.user_id == patient_id, PatientArchive.id == patient_id),
            PatientArchive.is_deleted == False,
        )
    )).scalar_one_or_none()

    indicators = []
    if archive:
        uid = archive.user_id or archive.id
        indicators = list((await db.execute(
            select(HealthIndicator)
            .where(HealthIndicator.user_id == uid, HealthIndicator.recorded_at >= cutoff)
            .order_by(desc(HealthIndicator.recorded_at)).limit(15)
        )).scalars().all())

    patient_name = archive.name if archive else "患者"
    ind_lines = []
    for ind in indicators:
        key = ind.indicator_type.value if hasattr(ind.indicator_type, "value") else str(ind.indicator_type)
        cn = _INDICATOR_CN.get(key, key)
        at = ind.recorded_at.isoformat()[:10] if ind.recorded_at else ""
        vals = ind.values or {}
        if key == "BLOOD_PRESSURE":
            val_str = f"{vals.get('systolic','?')}/{vals.get('diastolic','?')} mmHg"
        elif key == "BLOOD_GLUCOSE":
            val_str = f"{vals.get('value','?')} mmol/L"
        elif key == "WEIGHT":
            val_str = f"{vals.get('value','?')} kg"
        else:
            val_str = str(vals.get("value", str(vals)))
        ind_lines.append(f"{at} {cn}: {val_str}")

    user_text = (
        f"患者：{patient_name}\n"
        f"当前方案（摘要）：\n{(plan.content or '')[:800]}\n\n"
        f"近30天健康指标：\n{chr(10).join(ind_lines) if ind_lines else '无近期指标记录'}"
    )

    system_delta = (
        "你是中医慢病管理平台的临床决策助手。\n"
        "基于患者当前方案和近期指标变化，判断哪些内容需要调整，输出JSON：\n"
        '{"need_update": true/false, "reason": "判断依据（1句话）", '
        '"suggestions": [{"field": "调整项目", "content": "具体建议（20字以内）"}]}\n'
        "suggestions 最多5条，只输出JSON。"
    )

    ai_raw = await _ai_call(system_delta, user_text, max_tokens=512)
    ai_result = None
    if ai_raw:
        try:
            json_match = re.search(r'\{.*\}', ai_raw, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                if "suggestions" in parsed:
                    ai_result = {
                        "need_update": bool(parsed.get("need_update", True)),
                        "reason": str(parsed.get("reason", "")).strip(),
                        "suggestions": [
                            {"field": str(s.get("field", "")).strip(), "content": str(s.get("content", "")).strip()}
                            for s in parsed["suggestions"][:5]
                            if isinstance(s, dict)
                        ],
                    }
        except Exception:
            pass

    if ai_result is None:
        ai_result = {
            "need_update": len(indicators) > 0,
            "reason": "AI 暂不可用，建议人工复核近期指标",
            "suggestions": [
                {"field": "指标复核", "content": f"近期有 {len(indicators)} 条指标，建议核对是否在目标范围内"}
            ] if indicators else [
                {"field": "方案评估", "content": "建议医生根据患者近况人工评估是否需要调整"}
            ],
        }

    return ok({
        "plan_id": plan_id,
        "plan_title": plan.title,
        "patient_name": patient_name,
        "indicator_count": len(indicators),
        "delta_suggestion": ai_result,
    })


# ── P3: 随访重点建议 ───────────────────────────────────────────────────────────

@router.get("/followup/{patient_id}/focus")
async def get_followup_focus(
    patient_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    随访重点（AI 驱动）：
    基于患者依从性 + 近期指标 + 当前方案，
    AI 生成本次随访应重点关注的 3-5 个问题。
    """
    aid = _parse_uuid(patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    user_id = archive.user_id
    today = date.today()
    cutoff_30 = today - timedelta(days=30)

    adherence_text = "无随访记录"
    if user_id:
        past_tasks = (await db.execute(
            select(FollowupTask)
            .join(FollowupPlan, FollowupTask.plan_id == FollowupPlan.id)
            .where(
                FollowupPlan.user_id == user_id,
                FollowupTask.scheduled_date < today,
                FollowupTask.scheduled_date >= cutoff_30,
                FollowupTask.required == True,
            )
        )).scalars().all()
        if past_tasks:
            done = (await db.execute(
                select(func.count()).select_from(CheckIn).where(
                    CheckIn.task_id.in_([t.id for t in past_tasks]),
                    CheckIn.status == "DONE",
                )
            )).scalar() or 0
            rate = round(done / len(past_tasks) * 100)
            adherence_text = f"近30天随访完成率 {rate}%（{done}/{len(past_tasks)}）"

    open_alerts = []
    if user_id:
        open_alerts = list((await db.execute(
            select(AlertEvent)
            .where(AlertEvent.user_id == user_id, AlertEvent.status == AlertStatus.OPEN)
            .order_by(desc(AlertEvent.created_at)).limit(5)
        )).scalars().all())

    plan_patient_id = user_id if user_id else archive.id
    plan = (await db.execute(
        select(GuidanceRecord)
        .where(
            GuidanceRecord.patient_id == plan_patient_id,
            GuidanceRecord.guidance_type == GuidanceType.GUIDANCE,
            GuidanceRecord.status == GuidanceStatus.PUBLISHED,
        )
        .order_by(desc(GuidanceRecord.created_at)).limit(1)
    )).scalar_one_or_none()

    diseases = []
    if user_id:
        diseases = list((await db.execute(
            select(ChronicDiseaseRecord)
            .where(ChronicDiseaseRecord.user_id == user_id, ChronicDiseaseRecord.is_active == True)
        )).scalars().all())

    disease_str = "、".join(_DISEASE_CN.get(d.disease_type.value, d.disease_type.value) for d in diseases) or "无"
    alert_str = "；".join(e.message for e in open_alerts) if open_alerts else "无"
    plan_str = (plan.title + "（" + (plan.content or "")[:100] + "...）") if plan else "无"

    user_text = (
        f"患者：{archive.name}\n"
        f"慢病：{disease_str}\n"
        f"依从性：{adherence_text}\n"
        f"近期未处置预警：{alert_str}\n"
        f"当前方案：{plan_str}"
    )

    system_focus = (
        "你是中医慢病随访专家。根据患者情况，生成本次随访的重点关注问题，JSON格式：\n"
        '{"focus_items": [{"question": "具体询问内容（20字以内）", "reason": "关注原因（15字以内）", "priority": "high/medium/low"}]}\n'
        "输出3-5条，按优先级排序，只输出JSON。"
    )

    ai_raw = await _ai_call(system_focus, user_text, max_tokens=400)
    focus_items = None
    if ai_raw:
        try:
            json_match = re.search(r'\{.*\}', ai_raw, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                items = parsed.get("focus_items", [])
                if isinstance(items, list) and items:
                    focus_items = [
                        {
                            "question": str(fi.get("question", "")).strip(),
                            "reason": str(fi.get("reason", "")).strip(),
                            "priority": str(fi.get("priority", "medium")).lower(),
                        }
                        for fi in items[:5]
                        if isinstance(fi, dict) and fi.get("question")
                    ]
        except Exception:
            pass

    if not focus_items:
        focus_items = []
        if open_alerts:
            focus_items.append({
                "question": f"近期{open_alerts[0].message[:20]}是否有改善？",
                "reason": "存在未处置预警",
                "priority": "high",
            })
        focus_items.append({
            "question": "近期主要症状有无变化？",
            "reason": "常规随访问诊",
            "priority": "medium",
        })
        focus_items.append({
            "question": "饮食、运动、服药情况如何？",
            "reason": "依从性评估",
            "priority": "medium",
        })

    return ok({
        "patient_id": patient_id,
        "patient_name": archive.name,
        "adherence_text": adherence_text,
        "open_alert_count": len(open_alerts),
        "focus_items": focus_items,
    })


# ── P4: 召回话术 ───────────────────────────────────────────────────────────────

@router.get("/recall/{patient_id}/script")
async def get_recall_script(
    patient_id: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user=Depends(_PRO),
):
    """
    召回话术生成（AI 驱动）：
    基于患者情况，生成个性化的电话召回话术。
    包含：开场白 + 关注要点 + 预约引导语。
    """
    aid = _parse_uuid(patient_id)
    if not aid:
        return fail("VALIDATION_ERROR", "patient_id 格式无效")

    archive = await db.get(PatientArchive, aid)
    if not archive or archive.is_deleted:
        return fail("NOT_FOUND", "患者档案不存在", status_code=404)

    user_id = archive.user_id
    today = date.today()
    cutoff = today - timedelta(days=30)

    recall_reasons = []
    if user_id:
        alerts = list((await db.execute(
            select(AlertEvent)
            .where(AlertEvent.user_id == user_id, AlertEvent.status == AlertStatus.OPEN)
            .order_by(desc(AlertEvent.created_at)).limit(3)
        )).scalars().all())
        recall_reasons = [e.message for e in alerts]

    diseases = []
    if user_id:
        diseases = list((await db.execute(
            select(ChronicDiseaseRecord)
            .where(ChronicDiseaseRecord.user_id == user_id, ChronicDiseaseRecord.is_active == True)
        )).scalars().all())

    disease_str = "、".join(_DISEASE_CN.get(d.disease_type.value, d.disease_type.value) for d in diseases) or "慢病管理"

    adherence_rate = None
    if user_id:
        tasks = list((await db.execute(
            select(FollowupTask)
            .join(FollowupPlan, FollowupTask.plan_id == FollowupPlan.id)
            .where(
                FollowupPlan.user_id == user_id,
                FollowupTask.scheduled_date < today,
                FollowupTask.scheduled_date >= cutoff,
                FollowupTask.required == True,
            )
        )).scalars().all())
        if tasks:
            done = (await db.execute(
                select(func.count()).select_from(CheckIn).where(
                    CheckIn.task_id.in_([t.id for t in tasks]),
                    CheckIn.status == "DONE",
                )
            )).scalar() or 0
            adherence_rate = round(done / len(tasks) * 100)

    gender_cn = "先生" if archive.gender == "male" else "女士"
    recall_str = "；".join(recall_reasons[:2]) if recall_reasons else "定期随访复诊"
    adh_str = f"近期随访完成率 {adherence_rate}%" if adherence_rate is not None else "随访记录不足"

    user_text = (
        f"患者姓名：{archive.name}\n"
        f"称谓：{archive.name}{gender_cn}\n"
        f"慢病情况：{disease_str}\n"
        f"召回原因：{recall_str}\n"
        f"依从性：{adh_str}"
    )

    system_script = (
        "你是中医慢病管理中心的随访专员。根据患者情况，生成温和专业的电话召回话术，JSON格式：\n"
        '{"opening": "开场白（30字以内）", "concern_points": ["关注点1", "关注点2", "关注点3"], '
        '"appointment_guide": "预约引导语（40字以内）", "closing": "结束语（20字以内）"}\n'
        "语气温和、专业，避免让患者感到恐慌，只输出JSON。"
    )

    ai_raw = await _ai_call(system_script, user_text, max_tokens=512)
    script = None
    if ai_raw:
        try:
            json_match = re.search(r'\{.*\}', ai_raw, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                if parsed.get("opening"):
                    script = {
                        "opening": str(parsed.get("opening", "")).strip(),
                        "concern_points": [str(p).strip() for p in (parsed.get("concern_points") or [])[:3]],
                        "appointment_guide": str(parsed.get("appointment_guide", "")).strip(),
                        "closing": str(parsed.get("closing", "")).strip(),
                    }
        except Exception:
            pass

    if script is None:
        script = {
            "opening": f"您好，请问是{archive.name}{gender_cn}吗？我是{disease_str}健康管理中心的随访专员。",
            "concern_points": recall_reasons[:2] or [f"{disease_str}定期复诊提醒"],
            "appointment_guide": "方便的话，建议您近期到院复查，医生会根据您的情况调整管理方案。",
            "closing": "祝您健康，有问题随时联系我们。",
        }

    return ok({
        "patient_id": patient_id,
        "patient_name": archive.name,
        "recall_reason_count": len(recall_reasons),
        "script": script,
    })
