"""
Assistant Service: 计划-执行分离架构
POST /assistant/plan - 意图识别 + 生成执行计划
POST /assistant/execute - 执行计划并返回结果
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.archive import PatientArchive
from app.models.enums import (
    AlertStatus,
    CheckInStatus,
    DiseaseType,
    FollowupStatus,
    UserRole,
)
from app.models.followup import CheckIn, FollowupPlan, FollowupTask
from app.models.guidance import GuidanceRecord, GuidanceStatus, GuidanceType
from app.models.user import User
from app.services.audit_service import log_action

# ── 系统提示 ────────────────────────────────────────────────────────────────

_PLANNER_PROMPT = """你是「治未病平台」的智能助手，负责将医生的自然语言指令转换为结构化执行计划。

你的任务：
1. 识别用户意图（CreateChildProfile/CreateFollowupTask/GenerateTCMPlan等）
2. 提取必需参数
3. 生成执行步骤序列
4. 评估风险等级

支持的意图类型：
- CreateChildProfile: 新建儿童档案
- CreateFollowupTask: 创建随访任务
- GenerateTCMPlan: 生成中医调理方案
- SearchPatient: 搜索患者
- GetAlerts: 查询预警
- AckAlert: 确认预警

输出格式（严格JSON）：
{
  "intent": "CreateChildProfile",
  "arguments": {"name": "张小明", "birth_date": "2020-01-01", ...},
  "missing_fields": ["phone"],
  "steps": [
    {"tool": "PatientTool.create_child_profile", "args": {...}},
    {"tool": "ArchiveTool.create_tcm_archive", "args": {...}}
  ],
  "risk_level": "low"
}

规则：
- 如果缺少必需字段，在 missing_fields 中列出
- risk_level: low（查询）/medium（创建）/high（删除/修改关键数据）
- 使用中文回答
"""

# ── 工具定义 ────────────────────────────────────────────────────────────────

ASSISTANT_TOOLS = [
    {
        "name": "generate_plan",
        "description": "生成结构化执行计划",
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": [
                        "CreateChildProfile",
                        "CreateFollowupTask",
                        "GenerateTCMPlan",
                        "SearchPatient",
                        "GetAlerts",
                        "AckAlert",
                    ],
                },
                "arguments": {"type": "object"},
                "missing_fields": {"type": "array", "items": {"type": "string"}},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string"},
                            "args": {"type": "object"},
                        },
                        "required": ["tool", "args"],
                    },
                },
                "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": ["intent", "arguments", "steps", "risk_level"],
        },
    }
]


# ── 工具执行器 ───────────────────────────────────────────────────────────────


async def _tool_search_patient(db: AsyncSession, args: dict) -> dict:
    """搜索患者"""
    name = args.get("name", "").strip()
    phone = args.get("phone", "").strip()

    filters = []
    if name:
        filters.append(PatientArchive.name.contains(name))
    if phone:
        filters.append(PatientArchive.phone == phone)

    if not filters:
        return {"error": "请提供患者姓名或手机号"}

    result = await db.execute(select(PatientArchive).where(and_(*filters)).limit(5))
    archives = result.scalars().all()

    if not archives:
        return {"error": f"未找到患者: {name}"}

    return {
        "count": len(archives),
        "items": [
            {
                "id": str(a.id).replace("-", ""),
                "name": a.name,
                "phone": a.phone,
                "gender": a.gender,
                "birth_date": str(a.birth_date) if a.birth_date else None,
            }
            for a in archives
        ],
    }


async def _tool_create_child_profile(
    db: AsyncSession, current_user: Any, args: dict
) -> dict:
    """创建儿童档案"""
    from app.models.enums import ArchiveType

    name = args.get("name", "").strip()
    if not name:
        return {"error": "姓名不能为空"}

    birth_date_str = args.get("birth_date")
    if not birth_date_str:
        return {"error": "出生日期不能为空"}

    try:
        birth_date = datetime.strptime(birth_date_str, "%Y-%m-%d").date()
    except ValueError:
        return {"error": "出生日期格式错误，请使用 YYYY-MM-DD"}

    gender_str = args.get("gender", "male").lower()
    gender = "male" if gender_str == "male" else "female"

    archive = PatientArchive(
        id=uuid.uuid4(),
        name=name,
        gender=gender,
        birth_date=birth_date,
        phone=args.get("phone", ""),
        archive_type=ArchiveType.CHILD,
        user_id=None,
    )
    db.add(archive)
    await db.flush()

    return {
        "success": True,
        "archive_id": str(archive.id).replace("-", ""),
        "name": name,
        "birth_date": str(birth_date),
    }


async def _tool_create_followup_task(
    db: AsyncSession, current_user: Any, args: dict
) -> dict:
    """创建随访任务"""
    patient_name = args.get("patient_name", "").strip()
    if not patient_name:
        return {"error": "患者姓名不能为空"}

    # 查找患者
    result = await db.execute(
        select(PatientArchive).where(PatientArchive.name == patient_name).limit(1)
    )
    archive = result.scalar_one_or_none()

    if not archive:
        return {"error": f"未找到患者：{patient_name}"}

    # 解析疾病类型
    disease_str = args.get("disease_type", "高血压")
    disease_map = {
        "高血压": DiseaseType.HYPERTENSION,
        "糖尿病": DiseaseType.DIABETES,
        "冠心病": DiseaseType.CHD,
        "脑卒中": DiseaseType.STROKE,
        "慢阻肺": DiseaseType.COPD,
        "肿瘤": DiseaseType.TUMOR,
    }
    disease_type = disease_map.get(disease_str, DiseaseType.HYPERTENSION)

    # 解析日期
    start_date = datetime.now().date()
    end_date = start_date + timedelta(days=90)
    frequency_days = args.get("frequency_days", 7)

    # 创建随访计划
    plan = FollowupPlan(
        id=uuid.uuid4(),
        user_id=archive.user_id if archive.user_id else archive.id,
        disease_type=disease_type,
        start_date=start_date,
        end_date=end_date,
        frequency_days=frequency_days,
        status=FollowupStatus.ACTIVE,
        created_by_id=current_user.id,
    )
    db.add(plan)

    # 生成随访任务
    current = start_date
    task_count = 0
    while current <= end_date and task_count < 50:
        task = FollowupTask(
            id=uuid.uuid4(),
            plan_id=plan.id,
            scheduled_date=current,
        )
        db.add(task)

        checkin = CheckIn(
            id=uuid.uuid4(),
            task_id=task.id,
            scheduled_date=current,
            status=CheckInStatus.PENDING,
        )
        db.add(checkin)

        current += timedelta(days=frequency_days)
        task_count += 1

    await db.flush()

    return {
        "success": True,
        "plan_id": str(plan.id),
        "patient": archive.name,
        "disease": disease_type.value,
        "task_count": task_count,
    }


async def _tool_generate_tcm_plan(
    db: AsyncSession, current_user: Any, args: dict
) -> dict:
    """生成并保存中医调理方案"""
    archive_id_str = args.get("archive_id", "").strip()
    if not archive_id_str:
        return {"error": "档案ID不能为空"}

    try:
        aid = uuid.UUID(archive_id_str)
    except ValueError:
        return {"error": "档案ID格式无效"}

    result = await db.execute(select(PatientArchive).where(PatientArchive.id == aid))
    archive = result.scalar_one_or_none()
    if not archive:
        return {"error": "患者档案不存在"}

    # 生成方案内容（简化版）
    plan_content = f"""## {archive.name} 的中医调理方案

### 体质分析
根据档案信息，建议进行体质辨识评估。

### 调理建议
1. 饮食调理：清淡饮食，避免辛辣刺激
2. 起居调理：规律作息，早睡早起
3. 运动调理：适度运动，如太极、八段锦
4. 情志调理：保持心情舒畅

### 随访计划
建议每周随访一次，持续3个月。
"""

    # 保存为指导记录
    record = GuidanceRecord(
        patient_id=archive.user_id if archive.user_id else aid,
        doctor_id=current_user.id,
        guidance_type=GuidanceType.GUIDANCE,
        title=f"{archive.name}的中医调理方案",
        content=plan_content,
        status=GuidanceStatus.PUBLISHED,
        is_read=False,
    )
    db.add(record)
    await db.flush()

    return {
        "success": True,
        "record_id": str(record.id),
        "patient": archive.name,
        "plan_content": plan_content,
    }


# ── 工具分发 ─────────────────────────────────────────────────────────────────


async def _execute_tool(
    tool_name: str, args: dict, db: AsyncSession, current_user: Any
) -> dict:
    """执行单个工具"""
    # 标准化工具名称映射
    if "search" in tool_name.lower() and "patient" in tool_name.lower():
        return await _tool_search_patient(db, args)
    elif "create_child_profile" in tool_name.lower():
        return await _tool_create_child_profile(db, current_user, args)
    elif "followup" in tool_name.lower() and "task" in tool_name.lower():
        return await _tool_create_followup_task(db, current_user, args)
    elif "tcm" in tool_name.lower() and "plan" in tool_name.lower():
        return await _tool_generate_tcm_plan(db, current_user, args)
    else:
        return {"error": f"未知工具: {tool_name}"}


# ── 主入口 ────────────────────────────────────────────────────────────────────


async def generate_plan(
    query: str, db: AsyncSession, current_user: Any, context: dict
) -> dict:
    """生成执行计划"""
    if not settings.anthropic_api_key:
        return {"error": "API key 未配置"}

    import httpx

    base_url = settings.anthropic_base_url
    model    = settings.anthropic_model or "glm-4-air"
    user_msg = f"用户指令：{query}\n\n上下文：{json.dumps(context, ensure_ascii=False)}\n\n请严格按 JSON 格式输出，不要其他文字。"

    try:
        if base_url:
            # OpenAI 兼容格式（GLM 等）
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {settings.anthropic_api_key}",
                    },
                    json={
                        "model": model,
                        "max_tokens": 2048,
                        "messages": [
                            {"role": "system", "content": _PLANNER_PROMPT},
                            {"role": "user",   "content": user_msg},
                        ],
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                try:
                    start = content.find("{")
                    end = content.rfind("}") + 1
                    return json.loads(content[start:end])
                except Exception:
                    return {"error": "未能解析计划 JSON"}
        else:
            # Anthropic 官方 SDK（Claude）
            import anthropic
            messages = [{"role": "user", "content": user_msg}]
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            response = await client.messages.create(
                model=model or "claude-haiku-4-5-20251001",
                max_tokens=2048,
                system=_PLANNER_PROMPT,
                tools=ASSISTANT_TOOLS,
                messages=messages,
            )
            tools = [b for b in response.content if b.type == "tool_use"]
            if tools:
                return tools[0].input
            return {"error": "未能生成计划"}
    except Exception as e:
        return {"error": f"生成计划失败：{str(e)}"}


async def execute_plan(
    plan: dict, db: AsyncSession, current_user: Any, dry_run: bool = False
) -> dict:
    """执行计划"""
    exec_id = str(uuid.uuid4())
    executed_steps = []
    created_entities = {}
    ui_actions = []
    context = {}  # 步骤间共享上下文

    try:
        for step in plan.get("steps", []):
            tool_name = step["tool"]
            args = step["args"].copy()

            # 如果是搜索患者后创建任务，自动传递患者名称
            if "followup" in tool_name.lower() and not args.get("patient_name"):
                if context.get("patient_name"):
                    args["patient_name"] = context["patient_name"]

            if dry_run:
                executed_steps.append({"tool": tool_name, "ok": True, "output": {"dry_run": True}})
                continue

            output = await _execute_tool(tool_name, args, db, current_user)

            if "error" in output:
                executed_steps.append({"tool": tool_name, "ok": False, "output": output})
                await db.rollback()
                return {
                    "status": "failed",
                    "executed_steps": executed_steps,
                    "created_entities": created_entities,
                    "ui_actions": ui_actions,
                    "summary": f"执行失败：{output['error']}",
                }

            executed_steps.append({"tool": tool_name, "ok": True, "output": output})

            # 收集上下文：搜索患者结果
            if "search" in tool_name.lower() and output.get("items"):
                context["patient_name"] = output["items"][0]["name"]
                context["patient_id"] = output["items"][0]["id"]

            # 收集创建的实体
            if "archive_id" in output:
                created_entities["archive_id"] = output["archive_id"]
            if "plan_id" in output:
                created_entities["plan_id"] = output["plan_id"]
            if "record_id" in output:
                created_entities["record_id"] = output["record_id"]

        # 生成 UI 动作
        intent = plan.get("intent")
        if intent == "CreateChildProfile" and "archive_id" in created_entities:
            ui_actions.append({"type": "navigate", "path": f"/gui/admin/archive/{created_entities['archive_id']}"})
        elif intent == "CreateFollowupTask" and "plan_id" in created_entities:
            ui_actions.append({"type": "navigate", "path": "/gui/admin/followup"})

        # 记录审计日志
        await log_action(
            db,
            action="ASSISTANT_EXECUTE",
            resource_type="AssistantPlan",
            user_id=current_user.id,
            resource_id=exec_id,
            old_values=None,
            new_values={"intent": plan.get("intent"), "created_entities": created_entities},
        )

        await db.commit()

        return {
            "status": "success",
            "executed_steps": executed_steps,
            "created_entities": created_entities,
            "ui_actions": ui_actions,
            "summary": f"成功执行 {len(executed_steps)} 个步骤",
        }

    except Exception as e:
        await db.rollback()
        return {
            "status": "failed",
            "executed_steps": executed_steps,
            "created_entities": created_entities,
            "ui_actions": ui_actions,
            "summary": f"执行异常：{str(e)}",
        }
