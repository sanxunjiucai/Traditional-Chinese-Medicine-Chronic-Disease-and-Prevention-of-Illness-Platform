"""
AI 风险检测引擎

核心能力：
1. analyze_patient_risk  — 综合分析患者数据，识别风险等级和因素
2. generate_tcm_plan     — 基于风险结果生成中医调理方案（大模型）
3. auto_scan_and_alert   — 从临床文档提取指标，与规则匹配，自动创建预警

无 ANTHROPIC_API_KEY 时自动降级为规则引擎（不调用大模型）。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.archive import PatientArchive
from app.models.clinical import ClinicalDocument
from app.models.constitution import ConstitutionAssessment
from app.models.health import ChronicDiseaseRecord


async def _llm_call(system: str, user: str, max_tokens: int = 512) -> str:
    """统一大模型调用：GLM（OpenAI 兼容）或 Claude 官方 SDK。"""
    api_key  = settings.anthropic_api_key
    base_url = settings.anthropic_base_url
    model    = settings.anthropic_model or "glm-4-air"

    if base_url:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    else:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=model or "claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text.strip()

# ── 体质中文名称映射 ─────────────────────────────────────────────────────────

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

_DISEASE_CN = {
    "HYPERTENSION": "高血压",
    "DIABETES_T2": "2型糖尿病",
    "DYSLIPIDEMIA": "血脂异常",
    "COPD": "慢阻肺",
    "CORONARY_HEART_DISEASE": "冠心病",
    "CEREBROVASCULAR_DISEASE": "脑血管病",
    "CHRONIC_KIDNEY_DISEASE": "慢性肾病",
    "FATTY_LIVER": "脂肪肝",
    "OSTEOPOROSIS": "骨质疏松",
    "GOUT": "痛风",
}


# ── 数据采集层 ────────────────────────────────────────────────────────────────

async def _fetch_lab_reports(db: AsyncSession, archive_id: uuid.UUID) -> list[dict]:
    """获取最近 60 天检验报告"""
    result = await db.execute(
        select(ClinicalDocument)
        .where(
            and_(
                ClinicalDocument.archive_id == archive_id,
                ClinicalDocument.doc_type == "LAB_REPORT",
            )
        )
        .order_by(desc(ClinicalDocument.doc_date))
        .limit(5)
    )
    docs = result.scalars().all()
    items = []
    for d in docs:
        content = d.content or {}
        items.append({
            "date": str(d.doc_date.date()) if d.doc_date else None,
            "dept": d.dept,
            "items": content.get("items", []),
        })
    return items


async def _fetch_constitution(db: AsyncSession, archive_id: uuid.UUID) -> dict | None:
    """获取最新体质评估结果"""
    # constitution_assessments 通过 user_id 关联，需先找到 archive 对应 user
    archive_r = await db.execute(
        select(PatientArchive).where(PatientArchive.id == archive_id)
    )
    archive = archive_r.scalar_one_or_none()
    if not archive or not archive.user_id:
        return None

    result = await db.execute(
        select(ConstitutionAssessment)
        .where(ConstitutionAssessment.user_id == archive.user_id)
        .order_by(desc(ConstitutionAssessment.created_at))
        .limit(1)
    )
    assessment = result.scalar_one_or_none()
    if not assessment:
        return None
    return {
        "main_type": _BODY_TYPE_CN.get(assessment.main_type.value, assessment.main_type.value),
        "completed_at": str(assessment.created_at.date()) if assessment.created_at else None,
    }


async def _fetch_chronic_diseases(db: AsyncSession, archive_id: uuid.UUID) -> list[str]:
    """获取活跃慢病记录"""
    archive_r = await db.execute(
        select(PatientArchive).where(PatientArchive.id == archive_id)
    )
    archive = archive_r.scalar_one_or_none()
    if not archive or not archive.user_id:
        return []

    result = await db.execute(
        select(ChronicDiseaseRecord).where(
            and_(
                ChronicDiseaseRecord.user_id == archive.user_id,
                ChronicDiseaseRecord.is_active == True,  # noqa: E712
            )
        )
    )
    records = result.scalars().all()
    return [_DISEASE_CN.get(r.disease_type.value, r.disease_type.value) for r in records]


# ── 规则引擎降级版（无 API Key 时）────────────────────────────────────────────

def _rule_based_analysis(
    lab_reports: list[dict],
    constitution: dict | None,
    diseases: list[str],
) -> dict:
    """基于规则的风险分析（降级方案）"""
    risk_factors = []
    risk_evidence: list[dict] = []  # 结构化溯源证据（供插件展开）
    risk_level = "LOW"

    # 检验报告关键指标规则
    for report in lab_reports:
        report_date = report.get("date") or ""
        for item in report.get("items", []):
            name = item.get("name", "")
            value = item.get("value")
            unit = item.get("unit", "")
            flag = item.get("flag", "")
            ref = item.get("reference_range", "")

            direction = None
            sev = "MEDIUM"
            if flag in ("H", "HH", "↑"):
                direction = "偏高"
                sev = "HIGH" if flag == "HH" else "MEDIUM"
                risk_factors.append(f"{name} 偏高（{value}{unit}）")
                if flag == "HH":
                    risk_level = "HIGH"
                elif risk_level == "LOW":
                    risk_level = "MEDIUM"
            elif flag in ("L", "LL", "↓"):
                direction = "偏低"
                sev = "MEDIUM"
                risk_factors.append(f"{name} 偏低（{value}{unit}）")
                if risk_level == "LOW":
                    risk_level = "MEDIUM"

            if direction:
                risk_evidence.append({
                    "factor": f"{name}{direction}",
                    "value": f"{value}{unit}",
                    "reference": ref or "—",
                    "source": "检验报告",
                    "date": report_date,
                    "severity": sev,
                })

    # 慢病加权
    if len(diseases) >= 2:
        risk_factors.append(f"多种慢病并存：{', '.join(diseases)}")
        if risk_level == "LOW":
            risk_level = "MEDIUM"
        risk_evidence.append({
            "factor": "多种慢病并存",
            "value": "、".join(diseases),
            "reference": "建议综合管理",
            "source": "慢病档案",
            "date": "",
            "severity": "MEDIUM",
        })

    # 体质证据
    if constitution:
        risk_evidence.append({
            "factor": f"体质：{constitution['main_type']}",
            "value": constitution["main_type"],
            "reference": "中医体质辨识",
            "source": "体质评估",
            "date": constitution.get("completed_at") or "",
            "severity": "LOW",
        })

    if not risk_factors:
        risk_factors = ["暂未发现明显异常指标"]

    constitution_info = f"体质类型：{constitution['main_type']}" if constitution else "暂无体质评估"
    diseases_info = f"慢病史：{', '.join(diseases)}" if diseases else "无明确慢病记录"

    return {
        "risk_level": risk_level,
        "risk_factors": risk_factors,
        "risk_evidence": risk_evidence,
        "constitution": constitution_info,
        "diseases": diseases_info,
        "suggested_tcm_plan": _default_plan(constitution, diseases),
        "raw_summary": f"规则引擎分析（无AI）：风险等级 {risk_level}，发现 {len(risk_factors)} 项风险因素。",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "engine": "rule",
    }


_BODY_TYPE_ADVICE: dict[str, dict[str, list[str]]] = {
    "痰湿质": {
        "diet": ["减少甜食、油腻、生冷食物", "多食薏米、冬瓜、赤小豆、山药", "控制食量，晚餐宜少"],
        "exercise": ["每日有氧运动 40 分钟，如快走、游泳", "避免久坐，每小时起身活动"],
        "tcm": ["足三里、丰隆穴按揉，每次 3 分钟", "练习八段锦第三式「调理脾胃须单举」"],
    },
    "气虚质": {
        "diet": ["多食山药、大枣、黄芪煮粥", "忌生冷、辛辣，少量多餐", "可食黄芪炖鸡汤补气"],
        "exercise": ["散步为主，避免剧烈运动", "每日练习太极拳 20 分钟"],
        "tcm": ["按揉气海、关元穴各 3 分钟", "艾灸足三里，每周 2 次"],
    },
    "阳虚质": {
        "diet": ["多食羊肉、韭菜、生姜、肉桂", "忌寒凉食物及冷饮", "可食当归生姜羊肉汤"],
        "exercise": ["避免大汗淋漓，选择温和运动", "每日晒背 15 分钟"],
        "tcm": ["艾灸肾俞、命门穴，每次 15 分钟", "按揉涌泉穴，每晚睡前各 100 次"],
    },
    "阴虚质": {
        "diet": ["多食百合、银耳、枸杞、沙参", "忌辛辣、烟酒、油炸食品", "可食冰糖银耳莲子羹"],
        "exercise": ["适合游泳、太极，避免高强度出汗", "保证充足睡眠，午休 30 分钟"],
        "tcm": ["按揉三阴交、太溪穴各 3 分钟", "睡前温水泡脚 20 分钟"],
    },
    "血瘀质": {
        "diet": ["多食黑木耳、山楂、红花茶", "忌生冷油腻，戒烟限酒", "可食桃仁粥、红曲米饭"],
        "exercise": ["每日有氧运动 30 分钟促进血液循环", "练习八段锦、五禽戏"],
        "tcm": ["按揉血海、膈俞穴各 3 分钟", "热水泡脚后按摩小腿内侧"],
    },
    "湿热质": {
        "diet": ["多食绿豆、苦瓜、冬瓜、薏仁", "忌辛辣、烧烤、饮酒", "可饮薏仁赤小豆茶"],
        "exercise": ["每日运动 30-60 分钟，以出微汗为宜", "避免在湿热环境中长时间停留"],
        "tcm": ["按揉阴陵泉、曲池穴各 3 分钟", "练习六字诀中的「呵」字功"],
    },
    "气郁质": {
        "diet": ["多食佛手、玫瑰花茶、陈皮", "忌浓茶、咖啡，少食辛辣", "可食柴胡疏肝散药膳粥"],
        "exercise": ["鼓励户外有氧运动，增加社交活动", "每日散步 30 分钟，深呼吸练习"],
        "tcm": ["按揉太冲、膻中穴各 3 分钟", "练习八段锦第一式「两手托天理三焦」"],
    },
}

_DISEASE_ADVICE: dict[str, list[str]] = {
    "高血压": [
        "严格限盐，每日食盐 < 5g，拒绝腌制食品",
        "每日测量血压并记录，收缩压控制目标 < 140mmHg",
        "遵医嘱规律服药，不可自行停药",
        "保持情绪稳定，避免激动、紧张",
    ],
    "2型糖尿病": [
        "严格控制碳水摄入，主食粗细搭配（GI < 60）",
        "每日监测空腹及餐后血糖，HbA1c 目标 < 7.0%",
        "按时使用降糖药物，警惕低血糖反应",
        "每年检查眼底、肾功能、足部神经",
    ],
}


def _default_plan(constitution: dict | None, diseases: list[str]) -> str:
    """生成基于规则的详细调理方案（AI 不可用时的兜底方案）"""
    body_type = constitution["main_type"] if constitution else ""
    advice = _BODY_TYPE_ADVICE.get(body_type, {})

    lines = [
        f"## 中医调理方案（{body_type or '通用'}）",
        "",
        "### 一、综合评估摘要",
        f"患者体质类型为**{body_type or '待辨识'}**" + (f"，合并 {len(diseases)} 种慢性疾病（{' / '.join(diseases)}）" if diseases else "") + "，需针对性调护，防止疾病进展。",
        "",
        "### 二、饮食调养",
    ]
    for item in advice.get("diet", ["清淡饮食，减少肥甘厚腻", "多食蔬菜、粗粮", "控制盐分及总热量摄入"]):
        lines.append(f"- {item}")

    lines += ["", "### 三、运动锻炼"]
    for item in advice.get("exercise", ["每日步行 30 分钟，保持规律作息", "可适当练习太极拳、八段锦"]):
        lines.append(f"- {item}")

    lines += ["", "### 四、中医特色疗法"]
    for item in advice.get("tcm", ["保持情志舒畅，避免过度劳累", "定期接受中医调理"]):
        lines.append(f"- {item}")

    lines += [
        "",
        "### 五、生活起居",
        "- 规律作息，每日 22:00 前入睡，保证 7-8 小时睡眠",
        "- 戒烟限酒，减少久坐，每小时起身活动 5 分钟",
        "- 保持积极乐观的心态，适当参加社交活动",
    ]

    if diseases:
        lines += ["", "### 六、慢病重点管理"]
        for disease in diseases:
            disease_advice = _DISEASE_ADVICE.get(disease, [])
            if disease_advice:
                lines.append(f"**{disease}：**")
                for item in disease_advice:
                    lines.append(f"- {item}")
            else:
                lines.append(f"- {disease}：遵医嘱规律复诊，监测相关指标")

    lines += [
        "",
        "### 七、随访建议",
        f"- 建议 **{7 if diseases else 30} 天**后复诊，评估方案执行效果",
        "- 如出现不适症状（如头晕、胸闷、血糖/血压异常），请立即就医",
        "- 每 3 个月复查相关慢病指标（血糖、血压、血脂等）",
    ]

    return "\n".join(lines)


# ── AI 分析（有 API Key 时）──────────────────────────────────────────────────

async def _ai_analyze(
    lab_reports: list[dict],
    constitution: dict | None,
    diseases: list[str],
    patient_name: str,
    extra_context: str = "",
) -> dict:
    """调用大模型进行风险分析"""
    constitution_str = f"{constitution['main_type']}（{constitution['completed_at']}）" if constitution else "暂无"
    diseases_str = "、".join(diseases) if diseases else "无"

    # 格式化检验数据
    lab_str_parts = []
    for rpt in lab_reports[:3]:
        items_str = "、".join(
            f"{i.get('name')}={i.get('value')}{i.get('unit','')}{'↑' if i.get('flag') in ('H','HH') else '↓' if i.get('flag') in ('L','LL') else ''}"
            for i in rpt.get("items", [])[:10]
        )
        lab_str_parts.append(f"【{rpt.get('date')}】{items_str}")
    lab_str = "\n".join(lab_str_parts) if lab_str_parts else "暂无检验数据"

    prompt = f"""你是一位中医治未病专家，请根据以下患者信息进行风险评估：

患者：{patient_name}
体质辨识：{constitution_str}
慢病史：{diseases_str}
近期检验报告：
{lab_str}
{f'四诊信息：{extra_context}' if extra_context else ''}
请输出 JSON 格式（不要有任何其他文字）：
{{
  "risk_level": "HIGH 或 MEDIUM 或 LOW",
  "risk_factors": ["风险因素1", "风险因素2", ...],
  "raw_summary": "简要分析（100字以内）"
}}"""

    text = await _llm_call(
        system="你是一位中医治未病专家，请严格按 JSON 格式输出，不要有任何其他文字。",
        user=prompt,
        max_tokens=512,
    )

    # 提取 JSON
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        data = json.loads(text[start:end])
    except Exception:
        data = {"risk_level": "MEDIUM", "risk_factors": ["AI解析异常，请人工复核"], "raw_summary": text[:200]}

    constitution_info = f"体质类型：{constitution['main_type']}" if constitution else "暂无体质评估"
    diseases_info = f"慢病史：{diseases_str}"

    # AI 模式：用规则引擎生成结构化证据（AI 不返回 evidence）
    rule_result = _rule_based_analysis(lab_reports, constitution, diseases)

    return {
        "risk_level": data.get("risk_level", "MEDIUM"),
        "risk_factors": data.get("risk_factors", []),
        "risk_evidence": rule_result.get("risk_evidence", []),  # 规则引擎生成的结构化证据
        "constitution": constitution_info,
        "diseases": diseases_info,
        "suggested_tcm_plan": "",  # 由 generate_tcm_plan 单独生成
        "raw_summary": data.get("raw_summary", ""),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "engine": "ai",
    }


# ── 公开接口 ──────────────────────────────────────────────────────────────────

async def analyze_patient_risk(
    db: AsyncSession,
    archive_id: uuid.UUID,
    extra_context: str = "",
) -> dict:
    """
    综合分析患者风险。
    返回：{risk_level, risk_factors, constitution, diseases, suggested_tcm_plan, raw_summary, analyzed_at, engine}
    """
    # 1. 采集数据
    lab_reports = await _fetch_lab_reports(db, archive_id)
    constitution = await _fetch_constitution(db, archive_id)
    diseases = await _fetch_chronic_diseases(db, archive_id)

    # 获取患者姓名
    archive_r = await db.execute(select(PatientArchive).where(PatientArchive.id == archive_id))
    archive = archive_r.scalar_one_or_none()
    patient_name = archive.name if archive else "患者"

    # 2. 分析
    if settings.anthropic_api_key:
        try:
            result = await _ai_analyze(lab_reports, constitution, diseases, patient_name, extra_context)
        except Exception:
            result = _rule_based_analysis(lab_reports, constitution, diseases)
    else:
        result = _rule_based_analysis(lab_reports, constitution, diseases)

    if extra_context:
        result["sizhen_context"] = extra_context

    return result


async def generate_tcm_plan(
    db: AsyncSession,
    archive_id: uuid.UUID,
    risk_result: dict | None = None,
    extra_context: str = "",
) -> str:
    """
    生成完整中医调理方案（Markdown 格式）。
    risk_result 为 analyze_patient_risk 的返回值，若为 None 则先调用分析。
    """
    if risk_result is None:
        risk_result = await analyze_patient_risk(db, archive_id)

    if not settings.anthropic_api_key:
        archive_r = await db.execute(select(PatientArchive).where(PatientArchive.id == archive_id))
        archive = archive_r.scalar_one_or_none()
        constitution_mock = {"main_type": risk_result.get("constitution", "").replace("体质类型：", "")}
        diseases = risk_result.get("diseases", "").replace("慢病史：", "").split("、") if "慢病史：" in risk_result.get("diseases", "") else []
        return _default_plan(constitution_mock if constitution_mock["main_type"] else None, diseases)

    import anthropic

    risk_level_map = {"HIGH": "高风险", "MEDIUM": "中风险", "LOW": "低风险"}
    risk_cn = risk_level_map.get(risk_result.get("risk_level", "MEDIUM"), "中风险")
    factors_str = "\n".join(f"- {f}" for f in risk_result.get("risk_factors", []))

    prompt = f"""你是中医治未病专家，请为以下患者制定个性化中医调理方案：

患者风险评估：{risk_cn}
{risk_result.get('constitution', '')}
{risk_result.get('diseases', '')}
主要风险因素：
{factors_str}
{f'补充说明：{extra_context}' if extra_context else ''}

请生成完整的中医调理方案，使用 Markdown 格式，包含以下章节：
1. 综合评估摘要（3-5句话）
2. 饮食调养（具体食物推荐/禁忌，各3-5条）
3. 运动锻炼（具体项目和频率）
4. 中医特色疗法（穴位保健/功法/药膳，各2-3条）
5. 生活起居（作息/情志调摄）
6. 随访建议（复诊周期和监测指标）

语言简洁实用，适合患者阅读。"""

    try:
        client2 = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)  # noqa: F841 kept for reference
        return await _llm_call(
            system="你是中医治未病专家，请用 Markdown 格式生成调理方案。",
            user=prompt,
            max_tokens=1500,
        )
    except Exception:
        # AI 调用失败时降级为规则引擎方案
        constitution_mock = {"main_type": risk_result.get("constitution", "").replace("体质类型：", "")}
        diseases = (
            risk_result.get("diseases", "").replace("慢病史：", "").split("、")
            if "慢病史：" in risk_result.get("diseases", "") else []
        )
        return _default_plan(constitution_mock if constitution_mock["main_type"] else None, diseases)


async def auto_scan_and_alert(
    db: AsyncSession,
    archive_id: uuid.UUID,
) -> list[dict]:
    """
    从最新 LAB_REPORT 提取异常指标，与 AlertRule 比对，
    对匹配规则自动创建 AlertEvent。
    返回新建的预警事件摘要列表。
    """
    from app.models.alert import AlertEvent, AlertRule
    from app.models.enums import AlertStatus
    from app.services.alert_engine import _all_conditions_met

    # 找最新检验报告
    result = await db.execute(
        select(ClinicalDocument)
        .where(
            and_(
                ClinicalDocument.archive_id == archive_id,
                ClinicalDocument.doc_type == "LAB_REPORT",
            )
        )
        .order_by(desc(ClinicalDocument.doc_date))
        .limit(1)
    )
    doc = result.scalar_one_or_none()
    if not doc or not doc.content:
        return []

    # 提取检验项并转为 {字段名: 值} 结构
    items = doc.content.get("items", [])
    indicator_values: dict[str, float] = {}
    for item in items:
        name = item.get("name", "")
        value = item.get("value")
        if name and value is not None:
            try:
                indicator_values[name] = float(value)
            except (TypeError, ValueError):
                pass

    if not indicator_values:
        return []

    # 加载所有激活规则（indicator_type 为 NULL 的通用规则）
    rules_result = await db.execute(
        select(AlertRule).where(AlertRule.is_active == True)  # noqa: E712
    )
    rules = rules_result.scalars().all()

    # 找到 archive 对应的 user_id（预警事件关联 user）
    archive_r = await db.execute(select(PatientArchive).where(PatientArchive.id == archive_id))
    archive = archive_r.scalar_one_or_none()
    if not archive or not archive.user_id:
        return []

    created = []
    for rule in rules:
        if not _all_conditions_met(indicator_values, rule.conditions):
            continue

        # 防重复：检查同规则同患者是否已有 OPEN 事件
        existing = await db.execute(
            select(AlertEvent).where(
                and_(
                    AlertEvent.user_id == archive.user_id,
                    AlertEvent.rule_id == rule.id,
                    AlertEvent.status == AlertStatus.OPEN,
                )
            ).limit(1)
        )
        if existing.scalar_one_or_none():
            continue

        # 渲染消息
        try:
            message = rule.message_template.format(**{
                k: v for k, v in indicator_values.items()
                if isinstance(v, (int, float, str))
            })
        except (KeyError, ValueError):
            message = f"检验指标异常，请及时复诊（规则：{rule.name}）"

        event = AlertEvent(
            user_id=archive.user_id,
            rule_id=rule.id,
            severity=rule.severity,
            status=AlertStatus.OPEN,
            trigger_value=indicator_values,
            message=message,
        )
        db.add(event)
        created.append({
            "rule_name": rule.name,
            "severity": rule.severity.value,
            "message": message,
        })

    if created:
        await db.flush()
        try:
            from app.services.followup_service import apply_followup_rules
            await apply_followup_rules(db, "ALERT_TRIGGERED", archive_id)
        except Exception:
            pass  # 随访规则失败不影响主流程

    return created
