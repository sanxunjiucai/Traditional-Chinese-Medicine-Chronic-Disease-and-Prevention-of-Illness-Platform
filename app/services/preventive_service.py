"""
治未病·预防保健方案 业务服务层

核心能力：
1. extract_lifestyle_from_dialogue  — 从对话文本提取生活方式条目（AI）
2. upsert_lifestyle_profile         — 创建/更新生活方式档案
3. generate_tcm_traits              — 生成中医特征评估（AI）
4. generate_future_risks            — 生成未来风险推断（AI）
5. recommend_packages               — 推荐套餐方案（规则 + AI）
6. build_plan_draft                 — 构建方案草稿
7. preview_plan                     — 聚合方案预览数据
8. confirm_plan                     — 确认方案（锁版本）
9. distribute_plan                  — 分发到各渠道
10. create_followups_from_plan      — 自动生成随访任务
11. archive_old_plans               — 归档旧方案
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.enums import (
    DistributionChannel, DistributionStatus,
    IntentStatus, IntentType,
    LifestyleSource,
    PreventivePlanStatus,
    PreventiveTaskStatus, PreventiveTaskType,
)
from app.models.health import ChronicDiseaseRecord, HealthIndicator, HealthProfile
from app.models.constitution import ConstitutionAssessment
from app.models.preventive import (
    LifestyleProfile, PlanDistribution, PatientIntent,
    PreventiveFollowUpTask, PreventivePlan, RiskInference, TcmTraitAssessment,
)
from app.models.user import User

# ── 体质/证候中文映射 ─────────────────────────────────────────────────────────

_BODY_TYPE_CN = {
    "BALANCED": "平和质",
    "QI_DEFICIENCY": "气虚质",
    "YANG_DEFICIENCY": "阳虚质",
    "YIN_DEFICIENCY": "阴虚质",
    "PHLEGM_DAMPNESS": "痰湿质",
    "DAMP_HEAT": "湿热质",
    "BLOOD_STASIS": "血瘀质",
    "QI_STAGNATION": "气郁质",
    "SPECIAL_DIATHESIS": "特禀质",
}

_RISK_RULES = [
    {"key": "smoking", "value": "yes",    "risk": "肺癌", "probability": 0.18, "timeframe": "10年"},
    {"key": "smoking", "value": "yes",    "risk": "冠心病", "probability": 0.15, "timeframe": "10年"},
    {"key": "bmi",     "ge": 28,          "risk": "2型糖尿病", "probability": 0.22, "timeframe": "5年"},
    {"key": "bmi",     "ge": 28,          "risk": "高血压", "probability": 0.25, "timeframe": "5年"},
    {"key": "exercise","value": "sedentary","risk": "代谢综合征", "probability": 0.20, "timeframe": "5年"},
    {"key": "sleep",   "le": 6,           "risk": "心血管疾病", "probability": 0.12, "timeframe": "10年"},
    {"key": "stress",  "value": "high",   "risk": "抑郁症", "probability": 0.16, "timeframe": "3年"},
]

# ── AI 调用（降级为规则引擎） ──────────────────────────────────────────────────

async def _call_llm(prompt: str, system: str = "") -> str:
    """调用 Claude API；无 API KEY 时返回空字符串触发规则引擎降级。"""
    if not settings.anthropic_api_key:
        return ""
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=system or "你是一名专业的中医预防保健医师助手，请用 JSON 格式回复。",
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text if msg.content else ""
    except Exception:
        return ""


def _extract_json(text: str) -> Any:
    """从 LLM 输出中提取 JSON 对象/数组。"""
    import re
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1)
    try:
        return json.loads(text.strip())
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 1. 生活方式档案
# ══════════════════════════════════════════════════════════════════════════════

async def extract_lifestyle_from_dialogue(dialogue_text: str) -> list[dict]:
    """
    从对话文本中 AI 提取生活方式条目。
    返回 [{key, label, value, unit, confidence, evidence}]
    """
    prompt = f"""请从以下医患对话中提取患者的生活方式信息，以 JSON 数组格式返回。
每个条目包含：key（英文标识）, label（中文名称）, value（值）, unit（单位，可选）,
confidence（置信度 0-1）, evidence（证据原文片段）。

常见 key：smoking, drinking, exercise, sleep, diet, stress, bmi, waist,
work_type, commute, screen_time, meditation 等。

对话内容：
{dialogue_text}

请只返回 JSON 数组，不要其他文字。"""

    raw = await _call_llm(prompt)
    parsed = _extract_json(raw) if raw else None
    if parsed and isinstance(parsed, list):
        return parsed

    # 规则引擎降级：关键词匹配
    items = []
    text_lower = dialogue_text.lower()
    if any(w in text_lower for w in ["吸烟", "抽烟", "抽了", "每天烟"]):
        items.append({"key": "smoking", "label": "吸烟", "value": "yes",
                       "confidence": 0.8, "evidence": "对话中提及吸烟"})
    if any(w in text_lower for w in ["喝酒", "饮酒", "啤酒", "白酒"]):
        items.append({"key": "drinking", "label": "饮酒", "value": "yes",
                       "confidence": 0.8, "evidence": "对话中提及饮酒"})
    if any(w in text_lower for w in ["不运动", "很少运动", "久坐", "不锻炼"]):
        items.append({"key": "exercise", "label": "运动习惯", "value": "sedentary",
                       "confidence": 0.7, "evidence": "对话中提及缺乏运动"})
    if any(w in text_lower for w in ["睡不好", "失眠", "睡眠差", "睡眠浅"]):
        items.append({"key": "sleep", "label": "睡眠质量", "value": "poor",
                       "confidence": 0.8, "evidence": "对话中提及睡眠问题"})
    if any(w in text_lower for w in ["压力大", "焦虑", "紧张", "工作压力"]):
        items.append({"key": "stress", "label": "压力水平", "value": "high",
                       "confidence": 0.7, "evidence": "对话中提及高压力"})
    return items


async def upsert_lifestyle_profile(
    db: AsyncSession,
    patient_id: uuid.UUID,
    items: list[dict],
    source: LifestyleSource = LifestyleSource.MANUAL,
    encounter_id: str | None = None,
    raw_dialogue: str | None = None,
    created_by: uuid.UUID | None = None,
) -> LifestyleProfile:
    """创建生活方式档案（每次就诊建新档，不覆盖历史）。"""
    profile = LifestyleProfile(
        patient_id=patient_id,
        encounter_id=encounter_id,
        source=source,
        items=items,
        raw_dialogue=raw_dialogue,
        created_by=created_by,
    )
    db.add(profile)
    await db.flush()
    return profile


# ══════════════════════════════════════════════════════════════════════════════
# 2. 中医特征评估
# ══════════════════════════════════════════════════════════════════════════════

async def generate_tcm_traits(
    db: AsyncSession,
    patient_id: uuid.UUID,
    lifestyle_profile_id: uuid.UUID | None = None,
    symptom_items: list[dict] | None = None,
    dialogue_text: str | None = None,
    encounter_id: str | None = None,
    created_by: uuid.UUID | None = None,
) -> TcmTraitAssessment:
    """AI 生成中医特征评估。无 API KEY 时基于生活方式规则推断。"""

    # 获取生活方式条目
    lifestyle_items: list[dict] = []
    if lifestyle_profile_id:
        lp = await db.get(LifestyleProfile, lifestyle_profile_id)
        if lp:
            lifestyle_items = lp.items or []

    # 获取历史体质评估（辅助参考）
    hist_r = await db.execute(
        select(ConstitutionAssessment)
        .where(ConstitutionAssessment.user_id == patient_id)
        .order_by(ConstitutionAssessment.scored_at.desc())
        .limit(1)
    )
    hist_assessment = hist_r.scalar_one_or_none()

    context_parts = []
    if lifestyle_items:
        context_parts.append("生活方式：" + json.dumps(lifestyle_items, ensure_ascii=False))
    if symptom_items:
        context_parts.append("症状：" + json.dumps(symptom_items, ensure_ascii=False))
    if dialogue_text:
        context_parts.append(f"对话摘要：{dialogue_text[:500]}")
    if hist_assessment and hist_assessment.main_type:
        context_parts.append(f"历史体质评估：{_BODY_TYPE_CN.get(hist_assessment.main_type.value, '')}")

    prompt = f"""请根据以下患者信息，评估中医证候特征，以 JSON 格式返回。

{chr(10).join(context_parts)}

返回格式：
{{
  "primary_trait": "主要证候（如：气虚证、肝郁气滞等）",
  "traits": [
    {{
      "trait": "证候名称",
      "level": "轻/中/重",
      "score": 75,
      "evidence_items": ["依据1", "依据2"]
    }}
  ],
  "secondary_traits": ["次要证候1", "次要证候2"]
}}"""

    raw = await _call_llm(prompt)
    parsed = _extract_json(raw) if raw else None

    if parsed and isinstance(parsed, dict):
        primary_trait = parsed.get("primary_trait", "")
        traits = parsed.get("traits", [])
        secondary_traits = parsed.get("secondary_traits", [])
    else:
        # 规则引擎降级
        primary_trait, traits, secondary_traits = _rule_tcm_traits(lifestyle_items, symptom_items or [])

    assessment = TcmTraitAssessment(
        patient_id=patient_id,
        lifestyle_profile_id=lifestyle_profile_id,
        encounter_id=encounter_id,
        primary_trait=primary_trait,
        traits=traits,
        secondary_traits=secondary_traits,
        dialogue_text=dialogue_text,
        symptom_items=symptom_items or [],
        created_by=created_by,
    )
    db.add(assessment)
    await db.flush()
    return assessment


def _rule_tcm_traits(lifestyle_items: list[dict], symptom_items: list[dict]) -> tuple:
    """规则引擎推断中医证候（降级使用）。"""
    item_map = {i.get("key", ""): i.get("value", "") for i in lifestyle_items}
    traits = []
    secondary = []

    if item_map.get("stress") == "high" or any(
        s.get("name") in ("焦虑", "情绪波动", "烦躁") for s in symptom_items
    ):
        traits.append({"trait": "肝郁气滞", "level": "中", "score": 70,
                        "evidence_items": ["情绪压力大", "容易烦躁"]})
        secondary.append("气机不畅")

    if item_map.get("sleep") in ("poor", "bad") or any(
        s.get("name") in ("失眠", "多梦") for s in symptom_items
    ):
        traits.append({"trait": "心脾两虚", "level": "轻", "score": 55,
                        "evidence_items": ["睡眠不佳", "易疲劳"]})

    if item_map.get("exercise") == "sedentary":
        traits.append({"trait": "气虚质", "level": "轻", "score": 60,
                        "evidence_items": ["缺乏运动", "活动量少"]})
        secondary.append("痰湿内蕴")

    if item_map.get("smoking") == "yes":
        traits.append({"trait": "肺气阴虚", "level": "轻", "score": 50,
                        "evidence_items": ["长期吸烟", "耗伤肺气"]})

    if not traits:
        traits.append({"trait": "平和质", "level": "轻", "score": 80,
                        "evidence_items": ["生活方式较均衡"]})
        primary = "平和质"
    else:
        primary = traits[0]["trait"]

    return primary, traits, secondary


# ══════════════════════════════════════════════════════════════════════════════
# 3. 未来风险推断
# ══════════════════════════════════════════════════════════════════════════════

async def generate_future_risks(
    db: AsyncSession,
    patient_id: uuid.UUID,
    lifestyle_profile_id: uuid.UUID | None = None,
    vitals: dict | None = None,
    encounter_id: str | None = None,
    created_by: uuid.UUID | None = None,
) -> RiskInference:
    """AI 推断未来健康风险。"""

    # 获取生活方式 + 慢病史 + 健康指标
    lifestyle_items: list[dict] = []
    if lifestyle_profile_id:
        lp = await db.get(LifestyleProfile, lifestyle_profile_id)
        if lp:
            lifestyle_items = lp.items or []

    disease_r = await db.execute(
        select(ChronicDiseaseRecord).where(
            and_(ChronicDiseaseRecord.user_id == patient_id,
                 ChronicDiseaseRecord.is_active == True)  # noqa: E712
        )
    )
    diseases = disease_r.scalars().all()

    context_parts = []
    if lifestyle_items:
        context_parts.append("生活方式：" + json.dumps(lifestyle_items, ensure_ascii=False))
    if diseases:
        context_parts.append("现有慢病：" + "、".join(d.disease_type.value for d in diseases))
    if vitals:
        context_parts.append("体征数据：" + json.dumps(vitals, ensure_ascii=False))

    prompt = f"""请根据以下患者信息，推断未来5-10年的健康风险，以 JSON 格式返回。

{chr(10).join(context_parts)}

返回格式：
{{
  "risks": [
    {{
      "category": "疾病类别",
      "probability": 0.15,
      "severity": "高/中/低",
      "timeframe": "5年/10年",
      "rationale": "风险依据"
    }}
  ],
  "rationale_chain": ["推理步骤1", "推理步骤2"]
}}"""

    raw = await _call_llm(prompt)
    parsed = _extract_json(raw) if raw else None

    if parsed and isinstance(parsed, dict):
        risks = parsed.get("risks", [])
        rationale_chain = parsed.get("rationale_chain", [])
    else:
        risks, rationale_chain = _rule_risks(lifestyle_items, diseases)

    inference = RiskInference(
        patient_id=patient_id,
        lifestyle_profile_id=lifestyle_profile_id,
        encounter_id=encounter_id,
        risks=risks,
        rationale_chain=rationale_chain,
        vitals_snapshot=vitals,
        created_by=created_by,
    )
    db.add(inference)
    await db.flush()
    return inference


def _rule_risks(lifestyle_items: list[dict], diseases: list) -> tuple:
    """规则引擎推断风险（降级）。"""
    item_map = {i.get("key", ""): i.get("value", "") for i in lifestyle_items}
    existing = {d.disease_type.value for d in diseases}
    risks = []
    chain = ["基于生活方式和现有慢病进行规则匹配"]

    for rule in _RISK_RULES:
        key = rule["key"]
        val = item_map.get(key, "")
        triggered = False
        if "value" in rule and val == rule["value"]:
            triggered = True
        elif "ge" in rule:
            try:
                triggered = float(val) >= rule["ge"]
            except (ValueError, TypeError):
                pass
        elif "le" in rule:
            try:
                triggered = float(val) <= rule["le"]
            except (ValueError, TypeError):
                pass
        if triggered and rule["risk"] not in existing:
            risks.append({
                "category": rule["risk"],
                "probability": rule["probability"],
                "severity": "高" if rule["probability"] >= 0.2 else "中",
                "timeframe": rule["timeframe"],
                "rationale": f"{key}={val} 触发风险规则",
            })

    if not risks:
        risks.append({"category": "心血管疾病", "probability": 0.08,
                       "severity": "低", "timeframe": "10年",
                       "rationale": "基础背景风险"})
    chain.append(f"匹配到 {len(risks)} 项风险因素")
    return risks, chain


# ══════════════════════════════════════════════════════════════════════════════
# 4. 套餐推荐
# ══════════════════════════════════════════════════════════════════════════════

_PACKAGE_TEMPLATES = [
    {
        "template_id": "PKG-LIVER-QI",
        "name": "疏肝理气调理方案",
        "target_traits": ["肝郁气滞", "气机不畅"],
        "target_risks": ["抑郁症", "心血管疾病"],
        "duration_weeks": 8,
        "items": ["针灸（肝俞/太冲）", "中药代茶饮（玫瑰花疏肝茶）", "情志疏导", "八段锦教学"],
        "price_range": [800, 1500],
        "description": "针对肝郁气滞体质，疏肝解郁、调畅气机",
    },
    {
        "template_id": "PKG-QI-DEF",
        "name": "益气健脾基础方案",
        "target_traits": ["气虚质", "心脾两虚"],
        "target_risks": ["代谢综合征", "2型糖尿病"],
        "duration_weeks": 12,
        "items": ["艾灸（足三里/关元）", "黄芪参汤代茶饮", "八段锦气功指导", "饮食调护方案"],
        "price_range": [600, 1200],
        "description": "补气健脾，提升免疫，改善气虚体质",
    },
    {
        "template_id": "PKG-CARDIO-PREV",
        "name": "心血管预防综合方案",
        "target_traits": ["痰湿质", "血瘀质"],
        "target_risks": ["冠心病", "高血压", "脑血管病"],
        "duration_weeks": 16,
        "items": ["穴位按摩（心俞/膈俞）", "丹参山楂代茶饮", "有氧运动处方", "血压监测方案"],
        "price_range": [1200, 2500],
        "description": "预防心脑血管疾病，活血化瘀，降脂降压",
    },
    {
        "template_id": "PKG-SLEEP",
        "name": "安神助眠调理方案",
        "target_traits": ["心脾两虚", "心肾不交"],
        "target_risks": ["抑郁症", "心血管疾病"],
        "duration_weeks": 6,
        "items": ["耳穴压豆（神门/心/肾）", "酸枣仁汤代茶饮", "睡前导引功法", "睡眠卫生指导"],
        "price_range": [400, 800],
        "description": "改善睡眠质量，养心安神，调节心肾",
    },
    {
        "template_id": "PKG-METRO",
        "name": "代谢综合征预防方案",
        "target_traits": ["痰湿质"],
        "target_risks": ["2型糖尿病", "高血压", "代谢综合征"],
        "duration_weeks": 12,
        "items": ["针灸减脂（丰隆/天枢）", "荷叶山楂代茶饮", "运动处方（每日30分钟）", "低GI饮食方案"],
        "price_range": [900, 1800],
        "description": "化痰祛湿，改善代谢，预防糖尿病",
    },
]


async def recommend_packages(
    db: AsyncSession,
    patient_id: uuid.UUID,
    tcm_assessment_id: uuid.UUID | None = None,
    risk_inference_id: uuid.UUID | None = None,
) -> list[dict]:
    """推荐适合的套餐方案，返回 [{template_id, score, rationale, ...}]"""

    # 获取特征 + 风险
    patient_traits: list[str] = []
    patient_risks: list[str] = []

    if tcm_assessment_id:
        ta = await db.get(TcmTraitAssessment, tcm_assessment_id)
        if ta:
            patient_traits = [t.get("trait", "") for t in (ta.traits or [])]
            if ta.primary_trait:
                patient_traits.insert(0, ta.primary_trait)
            patient_traits.extend(ta.secondary_traits or [])

    if risk_inference_id:
        ri = await db.get(RiskInference, risk_inference_id)
        if ri:
            patient_risks = [r.get("category", "") for r in (ri.risks or [])]

    # 评分匹配
    scored = []
    for tpl in _PACKAGE_TEMPLATES:
        score = 0
        rationale_parts = []
        for trait in tpl["target_traits"]:
            if any(trait in pt for pt in patient_traits):
                score += 40
                rationale_parts.append(f"匹配证候：{trait}")
        for risk in tpl["target_risks"]:
            if any(risk in pr for pr in patient_risks):
                score += 30
                rationale_parts.append(f"预防风险：{risk}")
        if score > 0:
            scored.append({
                **tpl,
                "score": min(score, 100),
                "rationale": "；".join(rationale_parts) or "基础推荐",
            })

    # 至少返回1个兜底推荐
    if not scored:
        scored = [{**_PACKAGE_TEMPLATES[0], "score": 60, "rationale": "基础调理方案推荐"}]

    return sorted(scored, key=lambda x: x["score"], reverse=True)


# ══════════════════════════════════════════════════════════════════════════════
# 5. 方案构建、预览、确认、分发
# ══════════════════════════════════════════════════════════════════════════════

async def build_plan_draft(
    db: AsyncSession,
    patient_id: uuid.UUID,
    lifestyle_profile_id: uuid.UUID | None = None,
    tcm_assessment_id: uuid.UUID | None = None,
    risk_inference_id: uuid.UUID | None = None,
    selected_packages: list[dict] | None = None,
    selected_items: list[dict] | None = None,
    doctor_note: str | None = None,
    encounter_id: str | None = None,
    created_by: uuid.UUID | None = None,
) -> PreventivePlan:
    """构建方案草稿，生成经济选项和患者可读话术。"""

    # 生成经济选项
    economic_options = _build_economic_options(selected_packages or [])

    # 生成患者可读话术（AI 或规则）
    patient_note = await _generate_patient_note(
        selected_packages or [], economic_options, doctor_note
    )

    # 归档旧草稿
    await archive_old_plans(db, patient_id)

    # 计算版本号
    latest_r = await db.execute(
        select(PreventivePlan)
        .where(PreventivePlan.patient_id == patient_id)
        .order_by(PreventivePlan.version.desc())
        .limit(1)
    )
    latest = latest_r.scalar_one_or_none()
    version = (latest.version + 1) if latest else 1

    plan = PreventivePlan(
        patient_id=patient_id,
        encounter_id=encounter_id,
        status=PreventivePlanStatus.DRAFT,
        version=version,
        summary_blocks={
            "lifestyle_profile_id": str(lifestyle_profile_id) if lifestyle_profile_id else None,
            "tcm_assessment_id": str(tcm_assessment_id) if tcm_assessment_id else None,
            "risk_inference_id": str(risk_inference_id) if risk_inference_id else None,
        },
        selected_packages=selected_packages or [],
        selected_items=selected_items or [],
        economic_options=economic_options,
        doctor_note=doctor_note,
        patient_readable_note=patient_note,
        created_by=created_by,
    )
    db.add(plan)
    await db.flush()
    return plan


def _build_economic_options(packages: list[dict]) -> list[dict]:
    """基于选中套餐生成三档经济方案。"""
    if not packages:
        return [
            {"tier": "基础", "duration_weeks": 4, "visits": 4,
             "price_range": [400, 600], "rationale": "适合初次体验，了解中医调理"},
            {"tier": "标准", "duration_weeks": 8, "visits": 8,
             "price_range": [800, 1200], "rationale": "推荐方案，效果稳定"},
            {"tier": "强化", "duration_weeks": 12, "visits": 14,
             "price_range": [1500, 2500], "rationale": "深度调理，适合慢性问题"},
        ]

    total_min = sum(p.get("price_range", [0, 0])[0] for p in packages)
    total_max = sum(p.get("price_range", [0, 0])[1] for p in packages)
    total_weeks = max((p.get("duration_weeks", 8) for p in packages), default=8)

    return [
        {
            "tier": "基础",
            "duration_weeks": max(4, total_weeks // 2),
            "visits": max(4, total_weeks // 2),
            "price_range": [int(total_min * 0.5), int(total_min * 0.8)],
            "rationale": "核心疗程，适合初次体验",
        },
        {
            "tier": "标准",
            "duration_weeks": total_weeks,
            "visits": total_weeks,
            "price_range": [total_min, int((total_min + total_max) / 2)],
            "rationale": "推荐方案，全程覆盖",
        },
        {
            "tier": "强化",
            "duration_weeks": int(total_weeks * 1.5),
            "visits": int(total_weeks * 1.5),
            "price_range": [int((total_min + total_max) / 2), total_max],
            "rationale": "深度调理，效果最优",
        },
    ]


async def _generate_patient_note(
    packages: list[dict], economic_options: list[dict], doctor_note: str | None
) -> str:
    """生成患者可读的方案介绍话术。"""
    pkg_names = "、".join(p.get("name", "") for p in packages[:3]) if packages else "个性化调理"

    prompt = f"""请为患者生成一段简洁、温和、专业的中医调理方案介绍（200字以内），
说明选择的调理方向和预期效果。不要过度承诺疗效。

调理方案：{pkg_names}
医生备注：{doctor_note or '无'}
推荐疗程：{economic_options[1].get('duration_weeks', 8) if len(economic_options) > 1 else 8}周

请直接输出话术文本，不要 JSON 格式。"""

    raw = await _call_llm(prompt, system="你是一名专业的中医健康顾问，请用亲切专业的语气给患者介绍调理方案。")
    if raw and len(raw) > 20:
        return raw.strip()

    return (
        f"您好！根据您的体质评估和生活方式分析，我们为您制定了「{pkg_names}」调理方案。"
        f"本方案通过中医特色疗法，从饮食、运动、情志等多维度帮助您改善体质、预防疾病。"
        f"建议疗程 {economic_options[1].get('duration_weeks', 8) if len(economic_options) > 1 else 8} 周，"
        f"如有疑问请随时联系您的健康管理医师。祝您身体健康！"
    )


async def preview_plan(db: AsyncSession, plan_id: uuid.UUID) -> dict:
    """聚合方案预览数据，供 UI 展示。"""
    plan = await db.get(PreventivePlan, plan_id)
    if not plan:
        return {}

    blocks = plan.summary_blocks or {}
    lifestyle_data = None
    tcm_data = None
    risk_data = None

    if lid := blocks.get("lifestyle_profile_id"):
        lp = await db.get(LifestyleProfile, uuid.UUID(lid))
        if lp:
            lifestyle_data = {"id": str(lp.id), "items": lp.items, "source": lp.source.value}

    if tid := blocks.get("tcm_assessment_id"):
        ta = await db.get(TcmTraitAssessment, uuid.UUID(tid))
        if ta:
            tcm_data = {
                "id": str(ta.id),
                "primary_trait": ta.primary_trait,
                "traits": ta.traits,
                "secondary_traits": ta.secondary_traits,
            }

    if rid := blocks.get("risk_inference_id"):
        ri = await db.get(RiskInference, uuid.UUID(rid))
        if ri:
            risk_data = {
                "id": str(ri.id),
                "risks": ri.risks,
                "rationale_chain": ri.rationale_chain,
            }

    # 获取患者信息
    user = await db.get(User, plan.patient_id)

    return {
        "plan": {
            "id": str(plan.id),
            "status": plan.status.value,
            "version": plan.version,
            "doctor_note": plan.doctor_note,
            "patient_readable_note": plan.patient_readable_note,
            "selected_packages": plan.selected_packages,
            "selected_items": plan.selected_items,
            "economic_options": plan.economic_options,
            "created_at": plan.created_at.isoformat(),
        },
        "patient": {"id": str(user.id), "name": user.name} if user else None,
        "lifestyle": lifestyle_data,
        "traits": tcm_data,
        "risks": risk_data,
        "packages": plan.selected_packages,
        "economic_options": plan.economic_options,
        "patient_script": plan.patient_readable_note,
    }


async def confirm_plan(
    db: AsyncSession, plan_id: uuid.UUID, doctor_id: uuid.UUID
) -> PreventivePlan:
    """确认方案，版本锁定，状态推进到 CONFIRMED。"""
    plan = await db.get(PreventivePlan, plan_id)
    if not plan:
        raise ValueError("方案不存在")
    if plan.status != PreventivePlanStatus.DRAFT:
        raise ValueError(f"方案状态为 {plan.status.value}，无法确认")

    plan.status = PreventivePlanStatus.CONFIRMED
    plan.confirmed_by = doctor_id
    plan.confirmed_at = datetime.now(timezone.utc)
    db.add(plan)
    await db.flush()
    return plan


async def distribute_plan(
    db: AsyncSession,
    plan_id: uuid.UUID,
    channels: list[DistributionChannel],
    his_mode: str = "COPY",
) -> list[dict]:
    """分发方案到各渠道，返回每个渠道的分发结果。"""
    plan = await db.get(PreventivePlan, plan_id)
    if not plan:
        raise ValueError("方案不存在")
    if plan.status not in (PreventivePlanStatus.CONFIRMED, PreventivePlanStatus.DISTRIBUTED):
        raise ValueError(f"方案状态为 {plan.status.value}，请先确认方案")

    results = []
    for ch in channels:
        dist = PlanDistribution(plan_id=plan_id, channel=ch, status=DistributionStatus.PENDING)
        db.add(dist)
        await db.flush()

        try:
            payload = await _dispatch_channel(plan, ch, his_mode)
            dist.status = DistributionStatus.SUCCESS
            dist.payload_ref = payload
            results.append({"channel": ch.value, "status": "SUCCESS", "payload": payload})
        except Exception as e:
            dist.status = DistributionStatus.FAILED
            dist.error_message = str(e)
            results.append({"channel": ch.value, "status": "FAILED", "error": str(e)})
        db.add(dist)

    if any(r["status"] == "SUCCESS" for r in results):
        plan.status = PreventivePlanStatus.DISTRIBUTED
        db.add(plan)

    await db.flush()
    return results


async def _dispatch_channel(plan: PreventivePlan, channel: DistributionChannel, his_mode: str) -> str:
    """各渠道分发适配器（占位实现）。"""
    if channel == DistributionChannel.HIS:
        summary = f"预防保健方案 v{plan.version}：{len(plan.selected_packages)} 个套餐"
        if his_mode == "WRITEBACK":
            return f"HIS_WRITEBACK:{plan.id}:{summary}"
        return f"HIS_COPY:{summary}"
    elif channel == DistributionChannel.H5:
        return f"H5_PUBLISHED:plan_id={plan.id}"
    elif channel == DistributionChannel.ADMIN:
        return f"ADMIN_INDEXED:plan_id={plan.id}"
    return f"CHANNEL_{channel.value}_OK"


# ══════════════════════════════════════════════════════════════════════════════
# 6. 随访任务生成
# ══════════════════════════════════════════════════════════════════════════════

_DEFAULT_FOLLOWUP_DAYS = [7, 14, 28]


async def create_followups_from_plan(
    db: AsyncSession,
    plan: PreventivePlan,
    ruleset_days: list[int] | None = None,
) -> list[PreventiveFollowUpTask]:
    """按方案自动生成随访任务（第 7/14/28 天）。"""
    days = ruleset_days or _DEFAULT_FOLLOWUP_DAYS
    tasks = []
    base = datetime.now(timezone.utc)

    task_types = [
        PreventiveTaskType.CHECKIN,
        PreventiveTaskType.ADHERENCE,
        PreventiveTaskType.EFFECT_FEEDBACK,
    ]

    for i, d in enumerate(days):
        ttype = task_types[min(i, len(task_types) - 1)]
        task = PreventiveFollowUpTask(
            patient_id=plan.patient_id,
            plan_id=plan.id,
            task_type=ttype,
            status=PreventiveTaskStatus.TODO,
            due_at=base + timedelta(days=d),
        )
        db.add(task)
        tasks.append(task)

    # 末次复诊
    final_weeks = max(
        (p.get("duration_weeks", 8) for p in plan.selected_packages), default=8
    )
    return_task = PreventiveFollowUpTask(
        patient_id=plan.patient_id,
        plan_id=plan.id,
        task_type=PreventiveTaskType.RETURN_VISIT,
        status=PreventiveTaskStatus.TODO,
        due_at=base + timedelta(weeks=final_weeks),
    )
    db.add(return_task)
    tasks.append(return_task)

    await db.flush()
    return tasks


async def archive_old_plans(db: AsyncSession, patient_id: uuid.UUID) -> None:
    """将患者旧的 DRAFT 方案归档。"""
    r = await db.execute(
        select(PreventivePlan).where(
            and_(
                PreventivePlan.patient_id == patient_id,
                PreventivePlan.status == PreventivePlanStatus.DRAFT,
            )
        )
    )
    for old in r.scalars().all():
        old.status = PreventivePlanStatus.ARCHIVED
        db.add(old)
    await db.flush()


# ══════════════════════════════════════════════════════════════════════════════
# 7. 意向/预约
# ══════════════════════════════════════════════════════════════════════════════

async def create_intent(
    db: AsyncSession,
    patient_id: uuid.UUID,
    plan_id: uuid.UUID | None,
    intent_type: IntentType,
    scheduled_at: datetime | None = None,
    location: str | None = None,
    contact: str | None = None,
    note: str | None = None,
) -> PatientIntent:
    intent = PatientIntent(
        patient_id=patient_id,
        plan_id=plan_id,
        type=intent_type,
        status=IntentStatus.PENDING,
        scheduled_at=scheduled_at,
        location=location,
        contact=contact,
        note=note,
    )
    db.add(intent)
    await db.flush()
    return intent
