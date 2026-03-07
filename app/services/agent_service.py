"""
Agent Service: 解析自然语言意图，通过 Claude tool-use 调用平台所有 API，返回结构化结果。
支持动态调用 /tools/ 下的所有接口，无需为每个功能单独编写工具函数。
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.alert import AlertEvent
from app.models.enums import AlertStatus, CheckInStatus, FollowupStatus, UserRole
from app.models.followup import CheckIn, FollowupPlan, FollowupTask
from app.models.user import User
from app.services.audit_service import log_action

# ── 系统提示 ────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """你是「治未病平台」的智能医疗助手，可以调用平台所有 API 帮助医生完成操作。

你可以：
- 搜索患者、查看档案
- 新建居民档案（任何类型：普通居民/老年人/儿童/女性/重点关注）
- 创建/查询随访计划、干预计划、宣教内容
- 查看预警、统计数据
- 创建体质评估、健康评估
- 管理标签、查看审计日志
- 执行任何平台支持的操作

规则：
- 使用中文回答，语言简洁友好
- 先调用 call_api 工具执行操作，再根据结果生成回复
- 如果用户意图不明确，先搜索患者确认身份
- 新建档案时，姓名必填，其他字段若用户未提供则使用合理默认值（archive_type 默认 NORMAL）
- 创建任务时使用合理的默认值
"""

# ── 工具定义（Claude tool schema）───────────────────────────────────────────

AGENT_TOOLS = [
    {
        "name": "search_patient",
        "description": "按姓名或手机号搜索患者，返回患者档案 ID",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "患者姓名"},
                "phone": {"type": "string", "description": "手机号（可选）"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_alert_list",
        "description": "查询预警列表",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["OPEN", "ACKED", "CLOSED"], "description": "预警状态"},
                "severity": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"], "description": "严重程度"},
                "limit": {"type": "integer", "description": "返回数量，默认10"}
            }
        }
    },
    {
        "name": "get_followup_overview",
        "description": "查询随访计划概览",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}}
    },
    {
        "name": "get_stats_overview",
        "description": "查询系统统计概览",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "create_followup_task",
        "description": "为患者创建随访任务",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string", "description": "患者姓名"},
                "disease_type": {"type": "string", "description": "疾病类型：高血压/糖尿病/冠心病/脑卒中/慢阻肺/肿瘤"},
                "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD"},
                "frequency_days": {"type": "integer", "description": "随访频率（天）"}
            },
            "required": ["patient_name"]
        }
    },
    {
        "name": "analyze_patient_risk",
        "description": "分析患者健康风险，返回风险评估报告",
        "input_schema": {
            "type": "object",
            "properties": {
                "archive_id": {"type": "string", "description": "患者档案ID（十六进制字符串）"}
            },
            "required": ["archive_id"]
        }
    },
    {
        "name": "generate_tcm_plan",
        "description": "为患者生成个性化中医调理方案（Markdown 格式）",
        "input_schema": {
            "type": "object",
            "properties": {
                "archive_id": {"type": "string", "description": "患者档案ID（十六进制字符串）"},
                "extra_context": {"type": "string", "description": "额外背景信息，如症状描述、特殊需求等（可选）"}
            },
            "required": ["archive_id"]
        }
    },
    {
        "name": "issue_plan",
        "description": "将调理方案保存为指导记录并推送通知给患者，需先调用 generate_tcm_plan 获取 plan_content",
        "input_schema": {
            "type": "object",
            "properties": {
                "archive_id": {"type": "string", "description": "患者档案ID（十六进制字符串）"},
                "title": {"type": "string", "description": "方案标题"},
                "plan_content": {"type": "string", "description": "方案正文（Markdown）"}
            },
            "required": ["archive_id", "plan_content"]
        }
    },
    {
        "name": "ack_alert",
        "description": "确认（处理）一条预警事件，将状态从 OPEN 改为 ACKED",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "预警事件ID（UUID 格式）"},
                "note": {"type": "string", "description": "处理备注（可选）"}
            },
            "required": ["event_id"]
        }
    },
    {
        "name": "navigate_to",
        "description": "跳转到平台指定页面，可用于引导医生查看相关模块",
        "input_schema": {
            "type": "object",
            "properties": {
                "page": {
                    "type": "string",
                    "enum": ["patients", "alerts", "followup", "stats", "audit", "content", "visit", "risk", "consultations"],
                    "description": "目标页面标识"
                },
                "query_params": {"type": "string", "description": "URL 查询参数（可选），如 status=OPEN"}
            },
            "required": ["page"]
        }
    },
    {
        "name": "create_archive",
        "description": "新建居民健康档案，支持所有档案类型（普通居民/老年人/儿童/女性/重点关注）",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "居民姓名（必填）"},
                "gender": {"type": "string", "enum": ["male", "female"], "description": "性别，male=男 female=女"},
                "birth_date": {"type": "string", "description": "出生日期，格式 YYYY-MM-DD（可选）"},
                "phone": {"type": "string", "description": "手机号（可选）"},
                "archive_type": {
                    "type": "string",
                    "enum": ["NORMAL", "CHILD", "FEMALE", "ELDERLY", "KEY_FOCUS"],
                    "description": "档案类型：NORMAL=普通居民 CHILD=0-6岁儿童 FEMALE=女性 ELDERLY=老年人 KEY_FOCUS=重点关注，默认 NORMAL"
                },
                "id_number": {"type": "string", "description": "证件号码（可选）"},
                "address": {"type": "string", "description": "居住地址（可选）"},
                "ethnicity": {"type": "string", "description": "民族，默认汉族（可选）"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "get_patient_brief",
        "description": "获取患者AI一键摘要：汇聚档案、近期指标、风险、当前方案，AI自动生成临床简报和3条行动建议。适合快速了解患者整体状况",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "患者档案ID（十六进制字符串）"}
            },
            "required": ["patient_id"]
        }
    },
    {
        "name": "get_plan_delta_suggestion",
        "description": "获取方案调整建议：基于患者当前方案和近30天健康指标变化，AI生成具体的调整建议",
        "input_schema": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "方案ID（UUID格式）"}
            },
            "required": ["plan_id"]
        }
    },
    {
        "name": "get_followup_focus",
        "description": "获取本次随访重点：基于患者依从性和近期异常预警，AI生成3-5个本次随访应重点关注的问题",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "患者档案ID（十六进制字符串）"}
            },
            "required": ["patient_id"]
        }
    },
    {
        "name": "get_recall_script",
        "description": "生成个性化电话召回话术：基于患者慢病情况和召回原因，AI生成开场白、关注要点和预约引导语",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "患者档案ID（十六进制字符串）"}
            },
            "required": ["patient_id"]
        }
    },
    # ── 档案 CRUD ────────────────────────────────────────────────────────────
    {
        "name": "get_patient_archive",
        "description": "查询患者档案详情（姓名/性别/出生日期/手机/地址/既往史/过敏史等完整信息）",
        "input_schema": {
            "type": "object",
            "properties": {"archive_id": {"type": "string", "description": "档案ID（十六进制字符串）"}},
            "required": ["archive_id"]
        }
    },
    {
        "name": "update_patient_archive",
        "description": "修改患者档案信息，仅传需要修改的字段",
        "input_schema": {
            "type": "object",
            "properties": {
                "archive_id":   {"type": "string", "description": "档案ID"},
                "name":         {"type": "string", "description": "姓名"},
                "gender":       {"type": "string", "enum": ["male", "female"], "description": "性别"},
                "phone":        {"type": "string", "description": "手机号"},
                "birth_date":   {"type": "string", "description": "出生日期 YYYY-MM-DD"},
                "address":      {"type": "string", "description": "居住地址"},
                "occupation":   {"type": "string", "description": "职业"},
                "id_number":    {"type": "string", "description": "证件号"},
                "ethnicity":    {"type": "string", "description": "民族"},
                "emergency_contact_name":  {"type": "string", "description": "紧急联系人姓名"},
                "emergency_contact_phone": {"type": "string", "description": "紧急联系人电话"},
            },
            "required": ["archive_id"]
        }
    },
    {
        "name": "delete_patient_archive",
        "description": "将患者档案移入回收站（软删除）",
        "input_schema": {
            "type": "object",
            "properties": {"archive_id": {"type": "string", "description": "档案ID"}},
            "required": ["archive_id"]
        }
    },
    # ── 标签管理 ─────────────────────────────────────────────────────────────
    {
        "name": "list_patient_labels",
        "description": "查看患者当前的所有标签",
        "input_schema": {
            "type": "object",
            "properties": {"archive_id": {"type": "string", "description": "档案ID"}},
            "required": ["archive_id"]
        }
    },
    {
        "name": "assign_patient_label",
        "description": "给患者打标签，按标签名称查找并绑定",
        "input_schema": {
            "type": "object",
            "properties": {
                "archive_id": {"type": "string", "description": "档案ID"},
                "label_name": {"type": "string", "description": "标签名称"},
                "note":       {"type": "string", "description": "打标备注（可选）"}
            },
            "required": ["archive_id", "label_name"]
        }
    },
    {
        "name": "remove_patient_label",
        "description": "移除患者的某个标签",
        "input_schema": {
            "type": "object",
            "properties": {
                "archive_id": {"type": "string", "description": "档案ID"},
                "label_name": {"type": "string", "description": "要移除的标签名称"}
            },
            "required": ["archive_id", "label_name"]
        }
    },
    # ── 预警 ─────────────────────────────────────────────────────────────────
    {
        "name": "close_alert",
        "description": "关闭（结束）一条预警事件，将状态从 OPEN/ACKED 改为 CLOSED",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "预警事件ID（UUID格式）"},
                "note":     {"type": "string", "description": "关闭原因备注（可选）"}
            },
            "required": ["event_id"]
        }
    },
    {
        "name": "get_risk_dashboard",
        "description": "查看高危患者看板：列出有未处置 HIGH 级预警的患者",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "description": "返回数量，默认10"}}}
    },
    # ── 随访 ─────────────────────────────────────────────────────────────────
    {
        "name": "list_followup_plans",
        "description": "查看患者的随访计划列表（可按姓名查患者的所有计划）",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string", "description": "患者姓名（可选，不传则查全部）"},
                "limit":        {"type": "integer", "description": "返回数量，默认10"}
            }
        }
    },
    {
        "name": "today_followup_tasks",
        "description": "查看今日待随访任务列表",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "description": "返回数量，默认20"}}}
    },
    # ── 干预管理 ─────────────────────────────────────────────────────────────
    {
        "name": "list_interventions",
        "description": "查看干预计划列表（可按患者姓名或状态筛选）",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string", "description": "患者姓名（可选）"},
                "status":       {"type": "string", "description": "状态：IN_PROGRESS/COMPLETED/PAUSED（可选）"},
                "limit":        {"type": "integer", "description": "返回数量，默认10"}
            }
        }
    },
    {
        "name": "create_intervention",
        "description": "为患者创建干预计划（中医干预：针灸/推拿/药膳/运动等）",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name":      {"type": "string", "description": "患者姓名"},
                "plan_name":         {"type": "string", "description": "计划名称，如：气血双补针灸疗程"},
                "intervention_type": {"type": "string", "description": "类型：ACUPUNCTURE/TUINA/DIET/EXERCISE/HERBAL/OTHER"},
                "goal":              {"type": "string", "description": "干预目标（可选）"},
                "content_detail":    {"type": "string", "description": "内容详情：穴位/动作/方药等（可选）"},
                "duration_weeks":    {"type": "integer", "description": "疗程周数，默认4"},
                "frequency":         {"type": "string", "description": "频率：DAILY/WEEKLY/BIWEEKLY，默认WEEKLY"}
            },
            "required": ["patient_name", "plan_name", "intervention_type"]
        }
    },
    # ── 宣教管理 ─────────────────────────────────────────────────────────────
    {
        "name": "list_education_records",
        "description": "查看宣教记录列表（已发送的健康教育内容）",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回数量，默认10"}
            }
        }
    },
    {
        "name": "send_education",
        "description": "向患者发送宣教内容（健康教育）",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string", "description": "患者姓名"},
                "title":        {"type": "string", "description": "宣教标题"},
                "content":      {"type": "string", "description": "宣教内容正文"},
                "edu_type":     {"type": "string", "description": "类型：DIET/EXERCISE/MEDICATION/LIFESTYLE/OTHER，默认LIFESTYLE"}
            },
            "required": ["patient_name", "title", "content"]
        }
    },
    # ── 指导管理 ─────────────────────────────────────────────────────────────
    {
        "name": "list_guidance_records",
        "description": "查看医学指导记录列表",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string", "description": "患者姓名（可选）"},
                "limit":        {"type": "integer", "description": "返回数量，默认10"}
            }
        }
    },
    {
        "name": "create_guidance_record",
        "description": "为患者创建并下达医学指导内容",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string", "description": "患者姓名"},
                "title":        {"type": "string", "description": "指导标题"},
                "content":      {"type": "string", "description": "指导内容"},
                "guidance_type":{"type": "string", "description": "类型：GUIDANCE/EDUCATION/INTERVENTION，默认GUIDANCE"}
            },
            "required": ["patient_name", "title", "content"]
        }
    },
    # ── 咨询管理 ─────────────────────────────────────────────────────────────
    {
        "name": "list_consultations",
        "description": "查看患者咨询列表（含待处理/已回复等状态）",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "状态筛选：PENDING/IN_PROGRESS/RESOLVED（可选）"},
                "limit":  {"type": "integer", "description": "返回数量，默认10"}
            }
        }
    },
    # ── 健康指标 ─────────────────────────────────────────────────────────────
    {
        "name": "record_health_indicator",
        "description": "录入患者健康指标（血压/血糖/体重等）",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name":     {"type": "string", "description": "患者姓名"},
                "indicator_type":   {"type": "string", "enum": ["BLOOD_PRESSURE", "BLOOD_GLUCOSE", "WEIGHT", "WAIST_CIRCUMFERENCE"], "description": "指标类型"},
                "systolic":         {"type": "number", "description": "收缩压（血压时必填）"},
                "diastolic":        {"type": "number", "description": "舒张压（血压时必填）"},
                "value":            {"type": "number", "description": "数值（血糖/体重/腰围时填）"},
                "measured_at":      {"type": "string", "description": "测量时间 YYYY-MM-DD HH:MM（可选，默认当前时间）"}
            },
            "required": ["patient_name", "indicator_type"]
        }
    },
    {
        "name": "list_health_indicators",
        "description": "查询患者近期健康指标记录（血压/血糖/体重趋势）",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name":   {"type": "string", "description": "患者姓名"},
                "indicator_type": {"type": "string", "description": "指标类型（可选，不传返回所有类型）"},
                "limit":          {"type": "integer", "description": "返回条数，默认10"}
            },
            "required": ["patient_name"]
        }
    },
    # ── 统计 ─────────────────────────────────────────────────────────────────
    {
        "name": "get_business_stats",
        "description": "查看业务统计数据（复诊率、咨询量、预警数、随访完成率等 KPI）",
        "input_schema": {"type": "object", "properties": {}}
    },
]

_PAGE_URL_MAP = {
    "patients": "/gui/admin/patients",
    "alerts": "/gui/admin/alerts",
    "followup": "/gui/admin/followup",
    "stats": "/gui/admin/stats",
    "audit": "/gui/admin/audit",
    "content": "/gui/admin/content",
    "visit": "/gui/admin/visit-station",
    "risk": "/gui/admin/risk/plan",
    "consultations": "/gui/admin/consultations",
}

# ── 工具执行器 ───────────────────────────────────────────────────────────────

async def _exec_call_api(db: AsyncSession, current_user: Any, args: dict) -> dict:
    """通用 API 调用器：直接调用平台现有的工具函数"""
    method = args["method"]
    path = args["path"]
    body = args.get("body", {})
    params = args.get("params", {})

    # 根据路径映射到对应的工具函数
    if path.startswith("/tools/followup/plans"):
        if method == "POST":
            from app.tools.followup_tools import start_followup_plan
            from pydantic import BaseModel
            class Req(BaseModel):
                user_id: str
                disease_type: str
                start_date: str
                end_date: str
                frequency_days: int = 7
            req = Req(**body)
            result = await start_followup_plan(req, db, current_user)
            return result if isinstance(result, dict) else {"success": True}
        elif method == "GET":
            from app.tools.followup_tools import list_plans
            result = await list_plans(db, current_user, **params)
            return result if isinstance(result, dict) else {"success": True}

    elif path.startswith("/tools/archive/archives"):
        if method == "GET" and "?" not in path:
            from app.tools.archive_tools import get_archives
            result = await get_archives(db, current_user, **params)
            return result if isinstance(result, dict) else {"items": []}

    return {"error": f"暂不支持调用: {method} {path}，请使用内置工具"}



async def _exec_search_patient(db: AsyncSession, args: dict) -> dict:
    """搜索患者并返回档案 ID"""
    from app.models.archive import PatientArchive

    name = args.get("name", "").strip()
    phone = args.get("phone", "").strip()

    filters = [PatientArchive.name.contains(name)] if name else []
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
                "age": a.age if hasattr(a, 'age') else None,
            }
            for a in archives
        ],
    }


async def _exec_search_patients(db: AsyncSession, args: dict) -> dict:
    q = args.get("q", "").strip()
    is_active = args.get("is_active")
    filters = [User.role == UserRole.PATIENT]
    if is_active is not None:
        filters.append(User.is_active == is_active)
    if q:
        filters.append((User.name.contains(q)) | (User.phone.contains(q)))
    result = await db.execute(
        select(User).where(and_(*filters)).order_by(User.created_at.desc()).limit(20)
    )
    users = result.scalars().all()
    return {
        "count": len(users),
        "items": [
            {"id": str(u.id), "name": u.name, "phone": u.phone, "is_active": u.is_active}
            for u in users
        ],
    }


async def _exec_get_alert_list(db: AsyncSession, args: dict) -> dict:
    from app.models.enums import AlertSeverity

    limit = min(int(args.get("limit", 10)), 50)
    filters: list = []
    status_str = args.get("status")
    severity_str = args.get("severity")
    if status_str:
        try:
            filters.append(AlertEvent.status == AlertStatus[status_str])
        except KeyError:
            pass
    if severity_str:
        try:
            filters.append(AlertEvent.severity == AlertSeverity[severity_str])
        except KeyError:
            pass
    stmt = select(AlertEvent).order_by(AlertEvent.created_at.desc()).limit(limit)
    if filters:
        stmt = stmt.where(and_(*filters))
    result = await db.execute(stmt)
    events = result.scalars().all()

    items = []
    for e in events:
        user_r = await db.execute(select(User).where(User.id == e.user_id))
        user = user_r.scalar_one_or_none()
        items.append(
            {
                "id": str(e.id),
                "patient": user.name if user else "未知",
                "severity": e.severity.value,
                "status": e.status.value,
                "message": e.message,
                "created_at": e.created_at.isoformat(),
            }
        )
    return {"count": len(items), "items": items}


async def _exec_get_followup_overview(db: AsyncSession, args: dict) -> dict:
    limit = min(int(args.get("limit", 5)), 20)
    plans_result = await db.execute(
        select(FollowupPlan).where(FollowupPlan.status == FollowupStatus.ACTIVE).limit(50)
    )
    plans = plans_result.scalars().all()

    items = []
    for plan in plans:
        task_ids_stmt = select(FollowupTask.id).where(FollowupTask.plan_id == plan.id)
        total_r = await db.execute(
            select(func.count()).select_from(CheckIn).where(
                CheckIn.task_id.in_(task_ids_stmt)
            )
        )
        done_r = await db.execute(
            select(func.count()).select_from(CheckIn).where(
                and_(
                    CheckIn.task_id.in_(task_ids_stmt),
                    CheckIn.status == CheckInStatus.DONE,
                )
            )
        )
        total_t = total_r.scalar_one()
        done_t = done_r.scalar_one()
        adherence = round(done_t / total_t, 3) if total_t > 0 else 0.0

        user_r = await db.execute(select(User).where(User.id == plan.user_id))
        user = user_r.scalar_one_or_none()
        items.append(
            {
                "plan_id": str(plan.id),
                "patient": user.name if user else "未知",
                "phone": user.phone if user else "",
                "disease": plan.disease_type.value,
                "adherence_rate": adherence,
                "start_date": str(plan.start_date),
                "end_date": str(plan.end_date),
            }
        )

    items.sort(key=lambda x: x["adherence_rate"])
    return {"count": len(items[:limit]), "items": items[:limit]}


async def _exec_get_stats_overview(db: AsyncSession) -> dict:
    from app.models.enums import AlertSeverity

    total_patients_r = await db.execute(
        select(func.count()).select_from(User).where(User.role == UserRole.PATIENT)
    )
    active_patients_r = await db.execute(
        select(func.count(FollowupPlan.user_id.distinct())).where(
            FollowupPlan.status == FollowupStatus.ACTIVE
        )
    )
    open_alerts_r = await db.execute(
        select(func.count()).select_from(AlertEvent).where(
            AlertEvent.status == AlertStatus.OPEN
        )
    )
    high_alerts_r = await db.execute(
        select(func.count()).select_from(AlertEvent).where(
            and_(
                AlertEvent.status == AlertStatus.OPEN,
                AlertEvent.severity == AlertSeverity.HIGH,
            )
        )
    )
    return {
        "total_patients": total_patients_r.scalar_one(),
        "active_patients": active_patients_r.scalar_one(),
        "open_alerts": open_alerts_r.scalar_one(),
        "high_severity_alerts": high_alerts_r.scalar_one(),
    }


async def _exec_ack_alert(db: AsyncSession, current_user: Any, args: dict) -> dict:
    import uuid as uuid_mod
    from datetime import datetime, timezone

    event_id_str = args["event_id"]
    note = args.get("note", "")
    try:
        eid = uuid_mod.UUID(event_id_str)
    except ValueError:
        return {"error": "event_id 格式无效"}

    result = await db.execute(select(AlertEvent).where(AlertEvent.id == eid))
    event = result.scalar_one_or_none()
    if not event:
        return {"error": "预警事件不存在"}
    if event.status != AlertStatus.OPEN:
        return {"error": f"预警当前状态为 {event.status.value}，只有 OPEN 状态可确认"}

    event.status = AlertStatus.ACKED
    event.handled_by_id = current_user.id
    event.handler_note = note
    event.acked_at = datetime.now(timezone.utc)
    db.add(event)
    return {"success": True, "event_id": event_id_str, "new_status": "ACKED"}


async def _exec_analyze_patient_risk(db: AsyncSession, args: dict) -> dict:
    from app.services.risk_engine import analyze_patient_risk
    import uuid as uuid_mod
    try:
        aid = uuid_mod.UUID(args["archive_id"])
    except (KeyError, ValueError):
        return {"error": "archive_id 格式无效"}
    result = await analyze_patient_risk(db, aid)
    return result


async def _exec_generate_tcm_plan(db: AsyncSession, args: dict) -> dict:
    from app.services.risk_engine import generate_tcm_plan
    import uuid as uuid_mod
    try:
        aid = uuid_mod.UUID(args["archive_id"])
    except (KeyError, ValueError):
        return {"error": "archive_id 格式无效"}
    plan = await generate_tcm_plan(db, aid, extra_context=args.get("extra_context", ""))
    return {"plan_markdown": plan}


async def _exec_issue_plan(db: AsyncSession, current_user: Any, args: dict) -> dict:
    from app.models.guidance import GuidanceRecord, GuidanceStatus, GuidanceType
    from app.services.notification_service import push_to_patient
    from app.models.archive import PatientArchive
    import uuid as uuid_mod

    try:
        aid = uuid_mod.UUID(args["archive_id"])
    except (KeyError, ValueError):
        return {"error": "archive_id 格式无效"}

    from sqlalchemy import select
    archive_r = await db.execute(select(PatientArchive).where(PatientArchive.id == aid))
    archive = archive_r.scalar_one_or_none()
    if not archive:
        return {"error": "患者档案不存在"}

    title = args.get("title", "个性化中医调理方案")
    plan_content = args["plan_content"]

    record = GuidanceRecord(
        patient_id=archive.user_id if archive.user_id else aid,
        doctor_id=current_user.id,
        guidance_type=GuidanceType.GUIDANCE,
        title=title,
        content=plan_content,
        status=GuidanceStatus.PUBLISHED,
        is_read=False,
    )
    db.add(record)
    await db.flush()

    await push_to_patient(
        db=db, archive_id=aid,
        title=f"医生为您制定了调理方案：{title}",
        content=plan_content[:200],
        notif_type="PLAN_ISSUED",
        action_url=f"/h5/plan/{str(record.id)}",
        sender_id=current_user.id,
    )
    return {"success": True, "record_id": str(record.id), "patient": archive.name}


async def _exec_get_consultation_list(db: AsyncSession, args: dict) -> dict:
    from app.models.consultation import Consultation
    from sqlalchemy import select, desc
    filters = []
    status_str = args.get("status")
    if status_str:
        filters.append(Consultation.status == status_str)
    stmt = select(Consultation).order_by(desc(Consultation.updated_at)).limit(20)
    if filters:
        from sqlalchemy import and_
        stmt = stmt.where(and_(*filters))
    result = await db.execute(stmt)
    consults = result.scalars().all()
    return {
        "count": len(consults),
        "items": [
            {"id": str(c.id), "title": c.title, "status": c.status,
             "priority": c.priority, "updated_at": c.updated_at.isoformat()}
            for c in consults
        ],
    }


async def _exec_create_followup_task(db: AsyncSession, current_user: Any, args: dict) -> dict:
    from app.models.archive import PatientArchive
    from app.models.enums import DiseaseType, FollowupStatus
    from datetime import datetime, timedelta
    import uuid as uuid_mod

    patient_name = args.get("patient_name", "").strip()
    patient_phone = args.get("patient_phone", "").strip()

    if not patient_name:
        return {"error": "患者姓名不能为空"}

    # 查找患者
    filters = [PatientArchive.name == patient_name]
    if patient_phone:
        filters.append(PatientArchive.phone == patient_phone)

    result = await db.execute(select(PatientArchive).where(and_(*filters)).limit(1))
    archive = result.scalar_one_or_none()

    if not archive:
        return {"error": f"未找到患者：{patient_name}"}

    # 解析疾病类型
    disease_str = args.get("disease_type", "高血压")
    disease_map = {
        "高血压": DiseaseType.HYPERTENSION,
        "糖尿病": DiseaseType.DIABETES_T2,
        "冠心病": DiseaseType.HYPERTENSION,
        "脑卒中": DiseaseType.HYPERTENSION,
        "慢阻肺": DiseaseType.HYPERTENSION,
        "肿瘤":   DiseaseType.HYPERTENSION,
    }
    disease_type = disease_map.get(disease_str, DiseaseType.HYPERTENSION)

    # 解析日期
    try:
        start_date = datetime.strptime(args.get("start_date", ""), "%Y-%m-%d").date() if args.get("start_date") else datetime.now().date()
        end_date = datetime.strptime(args.get("end_date", ""), "%Y-%m-%d").date() if args.get("end_date") else (start_date + timedelta(days=90))
    except ValueError:
        return {"error": "日期格式错误，请使用 YYYY-MM-DD"}

    frequency_days = args.get("frequency_days", 7)

    # 创建随访计划
    plan = FollowupPlan(
        id=uuid_mod.uuid4(),
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
            id=uuid_mod.uuid4(),
            plan_id=plan.id,
            scheduled_date=current,
        )
        db.add(task)

        # 创建打卡记录
        checkin = CheckIn(
            id=uuid_mod.uuid4(),
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
        "start_date": str(start_date),
        "end_date": str(end_date),
    }


async def _exec_get_patient_archive(db: AsyncSession, args: dict) -> dict:
    from app.models.archive import PatientArchive
    import uuid as uuid_mod
    try:
        aid = uuid_mod.UUID(args["archive_id"])
    except (KeyError, ValueError):
        return {"error": "archive_id 格式无效"}
    r = await db.execute(select(PatientArchive).where(PatientArchive.id == aid))
    a = r.scalar_one_or_none()
    if not a:
        return {"error": "档案不存在"}
    return {
        "archive_id": str(a.id).replace("-", ""),
        "name": a.name, "gender": a.gender,
        "birth_date": str(a.birth_date) if a.birth_date else None,
        "phone": a.phone, "ethnicity": a.ethnicity, "occupation": a.occupation,
        "address": a.address, "id_number": a.id_number,
        "archive_type": a.archive_type.value if a.archive_type else None,
        "past_history": a.past_history, "family_history": a.family_history,
        "allergy_history": a.allergy_history,
        "emergency_contact_name": a.emergency_contact_name,
        "emergency_contact_phone": a.emergency_contact_phone,
    }


async def _exec_update_patient_archive(db: AsyncSession, args: dict) -> dict:
    from app.models.archive import PatientArchive
    from datetime import datetime
    import uuid as uuid_mod
    try:
        aid = uuid_mod.UUID(args["archive_id"])
    except (KeyError, ValueError):
        return {"error": "archive_id 格式无效"}
    r = await db.execute(select(PatientArchive).where(PatientArchive.id == aid))
    a = r.scalar_one_or_none()
    if not a:
        return {"error": "档案不存在"}
    updatable = ["name", "gender", "phone", "address", "occupation", "id_number",
                 "ethnicity", "emergency_contact_name", "emergency_contact_phone"]
    for field in updatable:
        if field in args and args[field] is not None:
            setattr(a, field, args[field])
    if args.get("birth_date"):
        try:
            a.birth_date = datetime.strptime(args["birth_date"], "%Y-%m-%d").date()
        except ValueError:
            return {"error": "birth_date 格式错误，请用 YYYY-MM-DD"}
    db.add(a)
    await db.flush()
    return {"success": True, "archive_id": str(a.id).replace("-", ""), "name": a.name}


async def _exec_delete_patient_archive(db: AsyncSession, args: dict) -> dict:
    from app.models.archive import PatientArchive
    import uuid as uuid_mod
    try:
        aid = uuid_mod.UUID(args["archive_id"])
    except (KeyError, ValueError):
        return {"error": "archive_id 格式无效"}
    r = await db.execute(select(PatientArchive).where(PatientArchive.id == aid))
    a = r.scalar_one_or_none()
    if not a:
        return {"error": "档案不存在"}
    await db.delete(a)
    await db.flush()
    return {"success": True, "message": f"档案「{a.name}」已移入回收站"}


async def _exec_list_patient_labels(db: AsyncSession, args: dict) -> dict:
    from app.models.label import Label, PatientLabel
    import uuid as uuid_mod
    try:
        aid = uuid_mod.UUID(args["archive_id"])
    except (KeyError, ValueError):
        return {"error": "archive_id 格式无效"}
    stmt = (
        select(PatientLabel, Label)
        .join(Label, PatientLabel.label_id == Label.id)
        .where(PatientLabel.patient_id == aid)
    )
    result = await db.execute(stmt)
    rows = result.all()
    return {
        "count": len(rows),
        "items": [{"label_id": pl.label_id, "name": lb.name, "color": lb.color, "note": pl.note} for pl, lb in rows],
    }


async def _exec_assign_patient_label(db: AsyncSession, current_user: Any, args: dict) -> dict:
    from app.models.label import Label, PatientLabel
    import uuid as uuid_mod
    try:
        aid = uuid_mod.UUID(args["archive_id"])
    except (KeyError, ValueError):
        return {"error": "archive_id 格式无效"}
    label_name = args.get("label_name", "").strip()
    lr = await db.execute(select(Label).where(Label.name == label_name, Label.is_active == True))
    label = lr.scalar_one_or_none()
    if not label:
        return {"error": f"标签「{label_name}」不存在，请先在标签管理中创建"}
    # 检查是否已有
    exist_r = await db.execute(
        select(PatientLabel).where(PatientLabel.patient_id == aid, PatientLabel.label_id == label.id)
    )
    if exist_r.scalar_one_or_none():
        return {"success": True, "message": f"患者已有标签「{label_name}」，无需重复添加"}
    pl = PatientLabel(patient_id=aid, label_id=label.id, note=args.get("note"), created_by=current_user.id)
    db.add(pl)
    await db.flush()
    return {"success": True, "label": label_name}


async def _exec_remove_patient_label(db: AsyncSession, args: dict) -> dict:
    from app.models.label import Label, PatientLabel
    import uuid as uuid_mod
    try:
        aid = uuid_mod.UUID(args["archive_id"])
    except (KeyError, ValueError):
        return {"error": "archive_id 格式无效"}
    label_name = args.get("label_name", "").strip()
    lr = await db.execute(select(Label).where(Label.name == label_name))
    label = lr.scalar_one_or_none()
    if not label:
        return {"error": f"标签「{label_name}」不存在"}
    pr = await db.execute(
        select(PatientLabel).where(PatientLabel.patient_id == aid, PatientLabel.label_id == label.id)
    )
    pl = pr.scalar_one_or_none()
    if not pl:
        return {"error": f"患者未绑定标签「{label_name}」"}
    await db.delete(pl)
    await db.flush()
    return {"success": True, "message": f"已移除标签「{label_name}」"}


async def _exec_close_alert(db: AsyncSession, current_user: Any, args: dict) -> dict:
    import uuid as uuid_mod
    from datetime import datetime, timezone
    try:
        eid = uuid_mod.UUID(args["event_id"])
    except (KeyError, ValueError):
        return {"error": "event_id 格式无效"}
    r = await db.execute(select(AlertEvent).where(AlertEvent.id == eid))
    event = r.scalar_one_or_none()
    if not event:
        return {"error": "预警事件不存在"}
    if event.status == AlertStatus.CLOSED:
        return {"error": "预警已经是 CLOSED 状态"}
    event.status = AlertStatus.CLOSED
    event.handled_by_id = current_user.id
    event.handler_note = args.get("note", "")
    event.acked_at = datetime.now(timezone.utc)
    db.add(event)
    return {"success": True, "event_id": args["event_id"], "new_status": "CLOSED"}


async def _exec_get_risk_dashboard(db: AsyncSession, args: dict) -> dict:
    from app.models.enums import AlertSeverity
    limit = min(int(args.get("limit", 10)), 50)
    stmt = (
        select(AlertEvent)
        .where(AlertEvent.status == AlertStatus.OPEN, AlertEvent.severity == AlertSeverity.HIGH)
        .order_by(AlertEvent.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    events = result.scalars().all()
    items = []
    for e in events:
        ur = await db.execute(select(User).where(User.id == e.user_id))
        user = ur.scalar_one_or_none()
        items.append({"event_id": str(e.id), "patient": user.name if user else "未知",
                      "message": e.message, "created_at": e.created_at.isoformat()})
    return {"count": len(items), "items": items}


async def _exec_list_followup_plans(db: AsyncSession, args: dict) -> dict:
    from app.models.enums import FollowupStatus
    limit = min(int(args.get("limit", 10)), 50)
    stmt = select(FollowupPlan).order_by(FollowupPlan.start_date.desc()).limit(limit)
    patient_name = args.get("patient_name", "").strip()
    if patient_name:
        user_r = await db.execute(select(User).where(User.name.contains(patient_name)))
        users = user_r.scalars().all()
        if not users:
            return {"count": 0, "items": [], "note": f"未找到患者「{patient_name}」"}
        user_ids = [u.id for u in users]
        stmt = stmt.where(FollowupPlan.user_id.in_(user_ids))
    result = await db.execute(stmt)
    plans = result.scalars().all()
    items = []
    for p in plans:
        ur = await db.execute(select(User).where(User.id == p.user_id))
        user = ur.scalar_one_or_none()
        items.append({
            "plan_id": str(p.id), "patient": user.name if user else "未知",
            "disease": p.disease_type.value, "status": p.status.value,
            "start_date": str(p.start_date), "end_date": str(p.end_date),
            "frequency_days": p.frequency_days,
        })
    return {"count": len(items), "items": items}


async def _exec_today_followup_tasks(db: AsyncSession, args: dict) -> dict:
    from datetime import date
    limit = min(int(args.get("limit", 20)), 50)
    today = date.today()
    stmt = select(FollowupTask).where(FollowupTask.scheduled_date == today).limit(limit)
    result = await db.execute(stmt)
    tasks = result.scalars().all()
    items = []
    for t in tasks:
        pr = await db.execute(select(FollowupPlan).where(FollowupPlan.id == t.plan_id))
        plan = pr.scalar_one_or_none()
        if plan:
            ur = await db.execute(select(User).where(User.id == plan.user_id))
            user = ur.scalar_one_or_none()
            items.append({
                "task_id": str(t.id), "patient": user.name if user else "未知",
                "disease": plan.disease_type.value,
                "scheduled_date": str(t.scheduled_date),
            })
    return {"count": len(items), "items": items, "date": str(today)}


async def _exec_list_interventions(db: AsyncSession, args: dict) -> dict:
    from app.models.intervention import Intervention
    limit = min(int(args.get("limit", 10)), 50)
    filters = []
    status_str = args.get("status")
    if status_str:
        filters.append(Intervention.status == status_str)
    patient_name = args.get("patient_name", "").strip()
    if patient_name:
        from app.models.archive import PatientArchive
        ar = await db.execute(select(PatientArchive).where(PatientArchive.name.contains(patient_name)).limit(5))
        archives = ar.scalars().all()
        if not archives:
            return {"count": 0, "items": []}
        patient_ids = [a.user_id for a in archives if a.user_id]
        if patient_ids:
            filters.append(Intervention.patient_id.in_(patient_ids))
    stmt = select(Intervention).order_by(Intervention.created_at.desc()).limit(limit)
    if filters:
        stmt = stmt.where(and_(*filters))
    result = await db.execute(stmt)
    items_raw = result.scalars().all()
    return {
        "count": len(items_raw),
        "items": [{"id": i.id, "plan_name": i.plan_name, "type": i.intervention_type,
                   "status": i.status, "duration_weeks": i.duration_weeks,
                   "start_date": str(i.start_date) if i.start_date else None} for i in items_raw],
    }


async def _exec_create_intervention(db: AsyncSession, current_user: Any, args: dict) -> dict:
    from app.models.intervention import Intervention
    from app.models.archive import PatientArchive
    from datetime import datetime, date
    patient_name = args.get("patient_name", "").strip()
    if not patient_name:
        return {"error": "患者姓名不能为空"}
    ar = await db.execute(select(PatientArchive).where(PatientArchive.name == patient_name).limit(1))
    archive = ar.scalar_one_or_none()
    if not archive:
        return {"error": f"未找到患者「{patient_name}」"}
    patient_id = archive.user_id if archive.user_id else archive.id
    iv = Intervention(
        patient_id=patient_id,
        plan_name=args.get("plan_name", "中医干预计划"),
        intervention_type=args.get("intervention_type", "OTHER"),
        goal=args.get("goal"),
        content_detail=args.get("content_detail"),
        duration_weeks=int(args.get("duration_weeks", 4)),
        frequency=args.get("frequency", "WEEKLY"),
        status="IN_PROGRESS",
        start_date=date.today(),
        created_by=current_user.id,
    )
    db.add(iv)
    await db.flush()
    return {"success": True, "intervention_id": iv.id, "plan_name": iv.plan_name, "patient": patient_name}


async def _exec_list_education_records(db: AsyncSession, args: dict) -> dict:
    from app.models.education import EducationRecord
    limit = min(int(args.get("limit", 10)), 50)
    result = await db.execute(
        select(EducationRecord).order_by(EducationRecord.created_at.desc()).limit(limit)
    )
    records = result.scalars().all()
    return {
        "count": len(records),
        "items": [{"id": str(r.id), "title": r.title, "edu_type": r.edu_type,
                   "created_at": r.created_at.isoformat()} for r in records],
    }


async def _exec_send_education(db: AsyncSession, current_user: Any, args: dict) -> dict:
    from app.models.education import EducationRecord, EducationDelivery
    from app.models.archive import PatientArchive
    patient_name = args.get("patient_name", "").strip()
    if not patient_name:
        return {"error": "患者姓名不能为空"}
    ar = await db.execute(select(PatientArchive).where(PatientArchive.name == patient_name).limit(1))
    archive = ar.scalar_one_or_none()
    if not archive:
        return {"error": f"未找到患者「{patient_name}」"}
    record = EducationRecord(
        title=args.get("title", "健康宣教"),
        content=args.get("content", ""),
        edu_type=args.get("edu_type", "LIFESTYLE"),
        send_scope="SINGLE",
        created_by=current_user.id,
    )
    db.add(record)
    await db.flush()
    delivery = EducationDelivery(
        record_id=record.id,
        patient_id=archive.user_id if archive.user_id else archive.id,
        send_method="IN_APP",
    )
    db.add(delivery)
    await db.flush()
    return {"success": True, "record_id": record.id, "patient": patient_name, "title": record.title}


async def _exec_list_guidance_records(db: AsyncSession, args: dict) -> dict:
    from app.models.guidance import GuidanceRecord
    limit = min(int(args.get("limit", 10)), 50)
    patient_name = args.get("patient_name", "").strip()
    stmt = select(GuidanceRecord).order_by(GuidanceRecord.created_at.desc()).limit(limit)
    if patient_name:
        from app.models.archive import PatientArchive
        ar = await db.execute(select(PatientArchive).where(PatientArchive.name.contains(patient_name)).limit(5))
        archives = ar.scalars().all()
        patient_ids = [a.user_id for a in archives if a.user_id]
        if patient_ids:
            stmt = stmt.where(GuidanceRecord.patient_id.in_(patient_ids))
    result = await db.execute(stmt)
    records = result.scalars().all()
    return {
        "count": len(records),
        "items": [{"id": str(r.id), "title": r.title, "guidance_type": r.guidance_type.value,
                   "status": r.status.value, "created_at": r.created_at.isoformat()} for r in records],
    }


async def _exec_create_guidance_record(db: AsyncSession, current_user: Any, args: dict) -> dict:
    from app.models.guidance import GuidanceRecord, GuidanceStatus, GuidanceType
    from app.models.archive import PatientArchive
    import uuid as uuid_mod
    patient_name = args.get("patient_name", "").strip()
    if not patient_name:
        return {"error": "患者姓名不能为空"}
    ar = await db.execute(select(PatientArchive).where(PatientArchive.name == patient_name).limit(1))
    archive = ar.scalar_one_or_none()
    if not archive:
        return {"error": f"未找到患者「{patient_name}」"}
    type_map = {"GUIDANCE": GuidanceType.GUIDANCE, "EDUCATION": GuidanceType.EDUCATION, "INTERVENTION": GuidanceType.INTERVENTION}
    g_type = type_map.get(args.get("guidance_type", "GUIDANCE"), GuidanceType.GUIDANCE)
    record = GuidanceRecord(
        patient_id=archive.user_id if archive.user_id else archive.id,
        doctor_id=current_user.id,
        guidance_type=g_type,
        title=args.get("title", "医学指导"),
        content=args.get("content", ""),
        status=GuidanceStatus.PUBLISHED,
        is_read=False,
    )
    db.add(record)
    await db.flush()
    return {"success": True, "record_id": str(record.id), "patient": patient_name}


async def _exec_list_consultations(db: AsyncSession, args: dict) -> dict:
    from app.models.consultation import Consultation
    from sqlalchemy import desc
    limit = min(int(args.get("limit", 10)), 50)
    filters = []
    status_str = args.get("status")
    if status_str:
        filters.append(Consultation.status == status_str)
    stmt = select(Consultation).order_by(desc(Consultation.updated_at)).limit(limit)
    if filters:
        stmt = stmt.where(and_(*filters))
    result = await db.execute(stmt)
    items = result.scalars().all()
    return {
        "count": len(items),
        "items": [{"id": str(c.id), "title": c.title, "status": c.status,
                   "priority": c.priority, "updated_at": c.updated_at.isoformat()} for c in items],
    }


async def _exec_record_health_indicator(db: AsyncSession, current_user: Any, args: dict) -> dict:
    from app.models.health import HealthIndicator
    from app.models.archive import PatientArchive
    from app.models.enums import IndicatorType
    from datetime import datetime, timezone
    import uuid as uuid_mod
    patient_name = args.get("patient_name", "").strip()
    if not patient_name:
        return {"error": "患者姓名不能为空"}
    ar = await db.execute(select(PatientArchive).where(PatientArchive.name == patient_name).limit(1))
    archive = ar.scalar_one_or_none()
    if not archive:
        return {"error": f"未找到患者「{patient_name}」"}
    ind_type_str = args.get("indicator_type", "")
    try:
        ind_type = IndicatorType[ind_type_str]
    except KeyError:
        return {"error": f"无效指标类型：{ind_type_str}，支持：BLOOD_PRESSURE/BLOOD_GLUCOSE/WEIGHT/WAIST_CIRCUMFERENCE"}
    values: dict = {}
    if ind_type == IndicatorType.BLOOD_PRESSURE:
        if not args.get("systolic") or not args.get("diastolic"):
            return {"error": "血压需填写 systolic（收缩压）和 diastolic（舒张压）"}
        values = {"systolic": float(args["systolic"]), "diastolic": float(args["diastolic"])}
    else:
        if not args.get("value"):
            return {"error": f"{ind_type_str} 需填写 value"}
        values = {"value": float(args["value"])}
    measured_at = datetime.now(timezone.utc)
    if args.get("measured_at"):
        try:
            measured_at = datetime.strptime(args["measured_at"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    patient_id = archive.user_id if archive.user_id else archive.id
    indicator = HealthIndicator(
        id=uuid_mod.uuid4(),
        user_id=patient_id,
        indicator_type=ind_type,
        values=values,
        recorded_at=measured_at,
    )
    db.add(indicator)
    await db.flush()
    return {"success": True, "patient": patient_name, "type": ind_type_str, "values": values}


async def _exec_list_health_indicators(db: AsyncSession, args: dict) -> dict:
    from app.models.health import HealthIndicator
    from app.models.archive import PatientArchive
    from app.models.enums import IndicatorType
    patient_name = args.get("patient_name", "").strip()
    if not patient_name:
        return {"error": "患者姓名不能为空"}
    ar = await db.execute(select(PatientArchive).where(PatientArchive.name == patient_name).limit(1))
    archive = ar.scalar_one_or_none()
    if not archive:
        return {"error": f"未找到患者「{patient_name}」"}
    patient_id = archive.user_id if archive.user_id else archive.id
    limit = min(int(args.get("limit", 10)), 50)
    stmt = (
        select(HealthIndicator)
        .where(HealthIndicator.user_id == patient_id)
        .order_by(HealthIndicator.recorded_at.desc())
        .limit(limit)
    )
    ind_type_str = args.get("indicator_type")
    if ind_type_str:
        try:
            stmt = stmt.where(HealthIndicator.indicator_type == IndicatorType[ind_type_str])
        except KeyError:
            pass
    result = await db.execute(stmt)
    indicators = result.scalars().all()
    from app.tools.plugin_tools import _INDICATOR_CN
    return {
        "count": len(indicators),
        "patient": patient_name,
        "items": [{"type": i.indicator_type.value, "type_cn": _INDICATOR_CN.get(i.indicator_type.value, i.indicator_type.value),
                   "values": i.values, "measured_at": i.recorded_at.isoformat()} for i in indicators],
    }


async def _exec_get_business_stats(db: AsyncSession) -> dict:
    from app.models.consultation import Consultation
    from app.models.enums import AlertSeverity
    from sqlalchemy import func
    open_r = await db.execute(select(func.count()).select_from(AlertEvent).where(AlertEvent.status == AlertStatus.OPEN))
    consult_r = await db.execute(select(func.count()).select_from(Consultation))
    active_r = await db.execute(select(func.count(FollowupPlan.id)).where(FollowupPlan.status == FollowupStatus.ACTIVE))
    total_r = await db.execute(select(func.count()).select_from(User).where(User.role == UserRole.PATIENT))
    done_r = await db.execute(
        select(func.count()).select_from(CheckIn).where(CheckIn.status == CheckInStatus.DONE)
    )
    total_ci_r = await db.execute(select(func.count()).select_from(CheckIn))
    total_ci = total_ci_r.scalar_one()
    done_ci = done_r.scalar_one()
    return {
        "total_patients": total_r.scalar_one(),
        "active_followup_plans": active_r.scalar_one(),
        "open_alerts": open_r.scalar_one(),
        "total_consultations": consult_r.scalar_one(),
        "followup_adherence_rate": round(done_ci / total_ci, 3) if total_ci > 0 else 0.0,
    }


async def _exec_navigate_to(args: dict) -> dict:
    qp = args.get("query_params", "").strip()
    url = _PAGE_URL_MAP.get(page, "/gui/admin/alerts")
    if qp:
        url = f"{url}?{qp}"
    return {"url": url, "page": page}


async def _exec_create_archive(db: AsyncSession, current_user: Any, args: dict) -> dict:
    """新建居民健康档案"""
    from app.models.archive import PatientArchive
    from app.models.enums import ArchiveType
    import uuid as uuid_mod
    from datetime import datetime

    name = args.get("name", "").strip()
    if not name:
        return {"error": "姓名不能为空"}

    # 解析出生日期
    birth_date = None
    birth_date_str = args.get("birth_date")
    if birth_date_str:
        try:
            birth_date = datetime.strptime(birth_date_str, "%Y-%m-%d").date()
        except ValueError:
            return {"error": "出生日期格式错误，请使用 YYYY-MM-DD"}

    # 解析档案类型
    type_map = {
        "NORMAL": ArchiveType.NORMAL,
        "CHILD": ArchiveType.CHILD,
        "FEMALE": ArchiveType.FEMALE,
        "ELDERLY": ArchiveType.ELDERLY,
        "KEY_FOCUS": ArchiveType.KEY_FOCUS,
    }
    archive_type = type_map.get(args.get("archive_type", "NORMAL"), ArchiveType.NORMAL)

    archive = PatientArchive(
        id=uuid_mod.uuid4(),
        name=name,
        gender=args.get("gender") or None,
        birth_date=birth_date,
        phone=args.get("phone") or None,
        id_number=args.get("id_number") or None,
        address=args.get("address") or None,
        ethnicity=args.get("ethnicity") or "汉族",
        archive_type=archive_type,
        user_id=None,
    )
    db.add(archive)
    await db.flush()

    type_labels = {
        "NORMAL": "普通居民", "CHILD": "0-6岁儿童",
        "FEMALE": "女性档案", "ELDERLY": "老年人", "KEY_FOCUS": "重点关注"
    }
    return {
        "success": True,
        "archive_id": str(archive.id),
        "name": name,
        "archive_type": archive_type.value,
        "archive_type_label": type_labels.get(archive_type.value, archive_type.value),
    }


# ── Agent 辅助函数 ────────────────────────────────────────────────────────────

_TOOL_LABELS: dict[str, str] = {
    "search_patient":          "搜索患者",
    "get_alert_list":          "查询预警",
    "get_followup_overview":   "查询随访",
    "get_stats_overview":      "查询统计",
    "create_followup_task":    "创建随访计划",
    "analyze_patient_risk":    "分析患者风险",
    "generate_tcm_plan":       "生成调理方案",
    "issue_plan":              "发布调理方案",
    "ack_alert":               "确认预警",
    "navigate_to":             "页面跳转",
    "call_api":                "调用接口",
    "create_archive":          "新建居民档案",
    "get_patient_brief":       "患者AI摘要",
    "get_plan_delta_suggestion": "方案调整建议",
    "get_followup_focus":      "随访重点",
    "get_recall_script":       "召回话术",
    # 新增
    "get_patient_archive":     "查询档案",
    "update_patient_archive":  "修改档案",
    "delete_patient_archive":  "删除档案",
    "list_patient_labels":     "查看标签",
    "assign_patient_label":    "打标签",
    "remove_patient_label":    "移除标签",
    "close_alert":             "关闭预警",
    "get_risk_dashboard":      "高危看板",
    "list_followup_plans":     "随访计划列表",
    "today_followup_tasks":    "今日随访任务",
    "list_interventions":      "查看干预计划",
    "create_intervention":     "创建干预计划",
    "list_education_records":  "查看宣教记录",
    "send_education":          "发送宣教",
    "list_guidance_records":   "查看指导记录",
    "create_guidance_record":  "创建指导",
    "list_consultations":      "查看咨询",
    "record_health_indicator": "录入健康指标",
    "list_health_indicators":  "查看指标历史",
    "get_business_stats":      "业务统计",
}


def _tool_summary(name: str, args: dict, result: dict) -> str:
    """生成工具执行的简短摘要，用于前端展示执行过程。"""
    if "error" in result:
        return f"失败：{result['error']}"
    if name == "search_patient":
        cnt = result.get("count", 0)
        if cnt and result.get("items"):
            names = "、".join(i["name"] for i in result["items"][:3])
            return f"找到 {cnt} 名：{names}"
        return "未找到患者"
    if name == "create_followup_task":
        return f"已为 {result.get('patient', '?')} 创建 {result.get('task_count', '?')} 次随访"
    if name == "get_alert_list":
        return f"共 {result.get('count', 0)} 条预警"
    if name == "ack_alert":
        return "预警已确认处理"
    if name == "issue_plan":
        return f"已为 {result.get('patient', '?')} 发布方案"
    if name == "get_stats_overview":
        return (
            f"在管患者 {result.get('active_patients', '?')} 人，"
            f"开放预警 {result.get('open_alerts', '?')} 条"
        )
    if name == "get_followup_overview":
        return f"共 {result.get('count', 0)} 个随访计划"
    if name == "generate_tcm_plan":
        return "方案已生成"
    if name == "navigate_to":
        return f"跳转至 {result.get('page', '?')} 页面"
    if name == "create_archive":
        if "error" in result:
            return f"失败：{result['error']}"
        return f"已新建档案：{result.get('name', '?')}（{result.get('archive_type_label', '')}）"
    return "执行成功"


def _infer_navigate_url(result_data: dict | None, executed_steps: list) -> str | None:
    """根据执行结果自动推断跳转页面 URL。"""
    if not result_data:
        return None
    if result_data.get("archive_id") and not result_data.get("plan_id"):
        return f"/gui/admin/archives/{result_data['archive_id']}"
    if result_data.get("plan_id"):
        return "/gui/admin/followup"
    if result_data.get("record_id"):
        return "/gui/admin/guidance"
    for step in executed_steps:
        if step["tool"] == "ack_alert":
            return "/gui/admin/alerts"
    return None


def _build_fallback_message(result_data: dict | None, executed_steps: list) -> str:
    """当 AI 未生成文字摘要时，根据结果数据自动生成。"""
    if result_data and result_data.get("success"):
        patient = result_data.get("patient", "") or result_data.get("name", "")
        if result_data.get("archive_id") and not result_data.get("plan_id"):
            label = result_data.get("archive_type_label", "档案")
            return f"已成功为{patient}新建{label}。"
        if result_data.get("plan_id"):
            tc = result_data.get("task_count", "?")
            return f"已成功为{patient}创建随访计划，共 {tc} 次随访任务。"
        if result_data.get("record_id"):
            return f"已成功为{patient}发布中医调理方案。"
        if result_data.get("new_status") == "ACKED":
            return "预警已确认处理。"
        return "操作已成功完成。"
    if result_data and result_data.get("count") is not None:
        return f"已查询到 {result_data['count']} 条结果。"
    if executed_steps:
        return "操作已完成。"
    return ""


async def _exec_plugin_endpoint(tool_name: str, db: AsyncSession, current_user: Any, args: dict) -> dict:
    """
    通用插件 AI 工具执行器：
    直接调用 plugin_tools.py 中的端点函数，提取 data 字段返回给 Agent。
    """
    import json as json_lib
    from app.tools import plugin_tools

    fn_map = {
        "get_patient_brief":        plugin_tools.get_patient_brief,
        "get_plan_delta_suggestion": plugin_tools.get_plan_delta_suggestion,
        "get_followup_focus":       plugin_tools.get_followup_focus,
        "get_recall_script":        plugin_tools.get_recall_script,
    }
    fn = fn_map.get(tool_name)
    if fn is None:
        return {"error": f"未找到插件工具: {tool_name}"}

    try:
        if tool_name == "get_patient_brief":
            response = await fn(patient_id=args.get("patient_id", ""), db=db, current_user=current_user)
        elif tool_name == "get_plan_delta_suggestion":
            response = await fn(plan_id=args.get("plan_id", ""), db=db, current_user=current_user)
        elif tool_name == "get_followup_focus":
            response = await fn(patient_id=args.get("patient_id", ""), db=db, current_user=current_user)
        elif tool_name == "get_recall_script":
            response = await fn(patient_id=args.get("patient_id", ""), db=db, current_user=current_user)
        else:
            return {"error": f"未知工具: {tool_name}"}

        body = json_lib.loads(response.body)
        return body.get("data", body)
    except Exception as e:
        return {"error": f"插件工具执行失败: {e}"}


# ── 工具分发 ─────────────────────────────────────────────────────────────────


async def _execute_tool(
    name: str, args: dict, db: AsyncSession, current_user: Any
) -> Any:
    if name == "call_api":
        return await _exec_call_api(db, current_user, args)
    if name == "search_patient":
        return await _exec_search_patient(db, args)
    if name == "search_patients":
        return await _exec_search_patients(db, args)
    if name == "get_alert_list":
        return await _exec_get_alert_list(db, args)
    if name == "get_followup_overview":
        return await _exec_get_followup_overview(db, args)
    if name == "get_stats_overview":
        return await _exec_get_stats_overview(db)
    if name == "ack_alert":
        return await _exec_ack_alert(db, current_user, args)
    if name == "analyze_patient_risk":
        return await _exec_analyze_patient_risk(db, args)
    if name == "generate_tcm_plan":
        return await _exec_generate_tcm_plan(db, args)
    if name == "issue_plan":
        return await _exec_issue_plan(db, current_user, args)
    if name == "get_consultation_list":
        return await _exec_get_consultation_list(db, args)
    if name == "create_followup_task":
        return await _exec_create_followup_task(db, current_user, args)
    if name == "navigate_to":
        return await _exec_navigate_to(args)
    if name == "create_archive":
        return await _exec_create_archive(db, current_user, args)
    if name == "get_patient_archive":
        return await _exec_get_patient_archive(db, args)
    if name == "update_patient_archive":
        return await _exec_update_patient_archive(db, args)
    if name == "delete_patient_archive":
        return await _exec_delete_patient_archive(db, args)
    if name == "list_patient_labels":
        return await _exec_list_patient_labels(db, args)
    if name == "assign_patient_label":
        return await _exec_assign_patient_label(db, current_user, args)
    if name == "remove_patient_label":
        return await _exec_remove_patient_label(db, args)
    if name == "close_alert":
        return await _exec_close_alert(db, current_user, args)
    if name == "get_risk_dashboard":
        return await _exec_get_risk_dashboard(db, args)
    if name == "list_followup_plans":
        return await _exec_list_followup_plans(db, args)
    if name == "today_followup_tasks":
        return await _exec_today_followup_tasks(db, args)
    if name == "list_interventions":
        return await _exec_list_interventions(db, args)
    if name == "create_intervention":
        return await _exec_create_intervention(db, current_user, args)
    if name == "list_education_records":
        return await _exec_list_education_records(db, args)
    if name == "send_education":
        return await _exec_send_education(db, current_user, args)
    if name == "list_guidance_records":
        return await _exec_list_guidance_records(db, args)
    if name == "create_guidance_record":
        return await _exec_create_guidance_record(db, current_user, args)
    if name == "list_consultations":
        return await _exec_list_consultations(db, args)
    if name == "record_health_indicator":
        return await _exec_record_health_indicator(db, current_user, args)
    if name == "list_health_indicators":
        return await _exec_list_health_indicators(db, args)
    if name == "get_business_stats":
        return await _exec_get_business_stats(db)
    # ── Plugin AI 工具（调用插件端 AI 驱动接口）────────────────────────────────
    if name == "get_patient_brief":
        return await _exec_plugin_endpoint("get_patient_brief", db, current_user, args)
    if name == "get_plan_delta_suggestion":
        return await _exec_plugin_endpoint("get_plan_delta_suggestion", db, current_user, args)
    if name == "get_followup_focus":
        return await _exec_plugin_endpoint("get_followup_focus", db, current_user, args)
    if name == "get_recall_script":
        return await _exec_plugin_endpoint("get_recall_script", db, current_user, args)
    return {"error": f"未知工具: {name}"}


# ── 流式主入口（SSE） ─────────────────────────────────────────────────────────

from typing import AsyncIterator


def _safe_parse_args(raw) -> dict:
    """安全解析 tool_call arguments，兼容 GLM/OpenAI 各种返回格式。"""
    if isinstance(raw, dict):
        return raw
    if not raw or raw == "null":
        return {}
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except Exception:
        # 容忍尾部多余字符：取第一个完整 JSON 对象
        try:
            dec = json.JSONDecoder()
            result, _ = dec.raw_decode(str(raw).strip())
            return result if isinstance(result, dict) else {}
        except Exception:
            return {}


async def run_agent_stream(
    query: str, db: AsyncSession, current_user: Any
) -> AsyncIterator[dict]:
    """流式 Agent 执行：逐步 yield 事件 dict，供 SSE 端点使用。
    事件类型：
      thinking  — 正在调用模型
      tool_call — 正在执行工具
      tool_result — 工具返回结果
      done      — 全部完成
      error     — 发生错误
    """
    exec_id = str(uuid.uuid4())
    if not settings.anthropic_api_key:
        yield {"type": "error", "message": "AI 助手暂时不可用（API key 未配置）"}
        return

    import httpx, json as json_lib
    base_url = settings.anthropic_base_url or None
    claude_model = settings.anthropic_model
    # OpenAI 格式：system 作为首条消息
    messages: list = [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": query}]
    result_data: Any = None
    navigate_url: str | None = None
    executed_steps: list = []
    final_message = ""

    # 将 Anthropic tool schema 转换为 OpenAI function calling 格式
    openai_tools = [
        {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
        for t in AGENT_TOOLS
    ]

    yield {"type": "thinking"}

    try:
        if base_url:
            async with httpx.AsyncClient(timeout=60.0) as client:
                for _ in range(4):
                    resp = await client.post(
                        f"{base_url}/chat/completions",
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {settings.anthropic_api_key}",
                        },
                        json={
                            "model": claude_model,
                            "max_tokens": 4096,
                            "messages": messages,
                            "tools": openai_tools,
                            "tool_choice": "auto",
                        },
                    )
                    try:
                        data = resp.json()
                    except Exception as je:
                        raw_preview = resp.text[:300] if resp.text else "(empty)"
                        yield {"type": "error", "message": f"AI响应解析失败: {raw_preview}"}
                        return
                    if resp.status_code != 200:
                        err_msg = data.get("error", {}).get("message") or str(data)
                        yield {"type": "error", "message": f"AI调用失败（{resp.status_code}）：{err_msg}"}
                        return
                    choice = data["choices"][0]
                    msg = choice["message"]
                    text = msg.get("content") or ""
                    tool_calls = msg.get("tool_calls") or []
                    if not tool_calls:
                        final_message = text.strip()
                        break
                    messages.append({"role": "assistant", "content": text, "tool_calls": tool_calls})
                    for tc in tool_calls:
                        tool_name = tc["function"]["name"]
                        tool_input = _safe_parse_args(tc["function"].get("arguments", "{}"))
                        yield {"type": "tool_call", "tool": tool_name, "label": _TOOL_LABELS.get(tool_name, tool_name)}
                        out = await _execute_tool(tool_name, tool_input, db, current_user)
                        step = {
                            "tool": tool_name,
                            "label": _TOOL_LABELS.get(tool_name, tool_name),
                            "summary": _tool_summary(tool_name, tool_input, out),
                            "status": "error" if "error" in out else "success",
                        }
                        executed_steps.append(step)
                        yield {"type": "tool_result", **step}
                        if tool_name == "navigate_to":
                            navigate_url = out.get("url")
                        elif "error" not in out:
                            result_data = out
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json_lib.dumps(out, ensure_ascii=False, default=str),
                        })
                    if choice.get("finish_reason") == "stop":
                        break
                else:
                    final_message = "操作已执行完毕。"
        else:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            for _ in range(4):
                response = await client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1024,
                    system=_SYSTEM_PROMPT,
                    tools=AGENT_TOOLS,
                    messages=messages,
                )
                texts = [b.text for b in response.content if b.type == "text"]
                tools = [b for b in response.content if b.type == "tool_use"]
                if not tools:
                    final_message = " ".join(texts).strip()
                    break
                messages.append({"role": "assistant", "content": response.content})
                results = []
                for t in tools:
                    yield {"type": "tool_call", "tool": t.name, "label": _TOOL_LABELS.get(t.name, t.name)}
                    out = await _execute_tool(t.name, t.input, db, current_user)
                    step = {
                        "tool": t.name,
                        "label": _TOOL_LABELS.get(t.name, t.name),
                        "summary": _tool_summary(t.name, t.input, out),
                        "status": "error" if "error" in out else "success",
                    }
                    executed_steps.append(step)
                    yield {"type": "tool_result", **step}
                    if t.name == "navigate_to":
                        navigate_url = out.get("url")
                    elif "error" not in out:
                        result_data = out
                    results.append({"type": "tool_result", "tool_use_id": t.id, "content": json.dumps(out, ensure_ascii=False, default=str)})
                messages.append({"role": "user", "content": results})
                if response.stop_reason == "end_turn":
                    final_message = " ".join(texts).strip()
                    break
            else:
                final_message = "操作已执行完毕。"
    except Exception as e:
        yield {"type": "error", "message": f"AI 执行失败：{e}"}
        return

    if navigate_url is None:
        navigate_url = _infer_navigate_url(result_data, executed_steps)
    if not final_message:
        final_message = _build_fallback_message(result_data, executed_steps)

    try:
        await log_action(
            db, action="AGENT_EXECUTE", resource_type="AgentQuery",
            user_id=current_user.id, resource_id=exec_id,
            old_values=None, new_values={"query": query, "navigate_url": navigate_url},
        )
        await db.commit()
    except Exception:
        pass

    yield {
        "type": "done",
        "message": final_message,
        "data": result_data,
        "navigate_url": navigate_url,
        "execution_id": exec_id,
        "executed_steps": executed_steps,
    }


# ── 主入口 ────────────────────────────────────────────────────────────────────


async def run_agent(query: str, db: AsyncSession, current_user: Any) -> dict:
    exec_id = str(uuid.uuid4())
    if not settings.anthropic_api_key:
        return {"message": "AI 助手暂时不可用（API key 未正确配置）。", "data": None, "navigate_url": None, "execution_id": exec_id}
    
    import httpx, json as json_lib
    base_url = settings.anthropic_base_url or None
    claude_model = settings.anthropic_model
    messages = [{"role": "user", "content": query}]
    result_data, navigate_url, final_message = None, None, ""
    executed_steps: list = []

    if base_url:
        try:
            openai_tools = [
                {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
                for t in AGENT_TOOLS
            ]
            messages = [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": query}]
            async with httpx.AsyncClient(timeout=60.0) as client:
                for _ in range(4):
                    resp = await client.post(
                        f"{base_url}/chat/completions",
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.anthropic_api_key}"},
                        json={"model": claude_model, "max_tokens": 4096, "messages": messages, "tools": openai_tools, "tool_choice": "auto"},
                    )
                    data = resp.json()
                    if resp.status_code != 200:
                        err_msg = data.get("error", {}).get("message") or str(data)
                        return {"message": f"AI调用失败（{resp.status_code}）：{err_msg}", "data": None, "navigate_url": None, "execution_id": exec_id}
                    choice = data["choices"][0]
                    msg = choice["message"]
                    text = msg.get("content") or ""
                    tool_calls = msg.get("tool_calls") or []
                    if not tool_calls:
                        final_message = text.strip()
                        break
                    messages.append({"role": "assistant", "content": text, "tool_calls": tool_calls})
                    for tc in tool_calls:
                        tool_name = tc["function"]["name"]
                        tool_input = _safe_parse_args(tc["function"].get("arguments", "{}"))
                        out = await _execute_tool(tool_name, tool_input, db, current_user)
                        executed_steps.append({
                            "tool": tool_name,
                            "label": _TOOL_LABELS.get(tool_name, tool_name),
                            "summary": _tool_summary(tool_name, tool_input, out),
                            "status": "error" if "error" in out else "success",
                        })
                        if tool_name == "navigate_to":
                            navigate_url = out.get("url")
                        elif "error" not in out:
                            result_data = out
                        messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json_lib.dumps(out, ensure_ascii=False, default=str)})
                    if choice.get("finish_reason") == "stop":
                        break
                else:
                    final_message = "操作已执行完毕。"
        except Exception as e:
            return {"message": f"AI 助手执行失败：{str(e)}", "data": None, "navigate_url": None, "execution_id": exec_id}
    else:
        import anthropic
        try:
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            for _ in range(4):
                response = await client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=1024, system=_SYSTEM_PROMPT, tools=AGENT_TOOLS, messages=messages)
                texts = [b.text for b in response.content if b.type == "text"]
                tools = [b for b in response.content if b.type == "tool_use"]
                if not tools:
                    final_message = " ".join(texts).strip()
                    break
                messages.append({"role": "assistant", "content": response.content})
                results = []
                for t in tools:
                    out = await _execute_tool(t.name, t.input, db, current_user)
                    executed_steps.append({
                        "tool": t.name,
                        "label": _TOOL_LABELS.get(t.name, t.name),
                        "summary": _tool_summary(t.name, t.input, out),
                        "status": "error" if "error" in out else "success",
                    })
                    if t.name == "navigate_to":
                        navigate_url = out.get("url")
                    elif "error" not in out:
                        result_data = out
                    results.append({"type": "tool_result", "tool_use_id": t.id, "content": json.dumps(out, ensure_ascii=False, default=str)})
                messages.append({"role": "user", "content": results})
                if response.stop_reason == "end_turn":
                    final_message = " ".join(texts).strip()
                    break
            else:
                final_message = "操作已执行完毕。"
        except Exception as e:
            return {"message": f"AI 助手执行失败：{str(e)}", "data": None, "navigate_url": None, "execution_id": exec_id}
    
    # 自动推断跳转页面（AI 没有主动调用 navigate_to 时）
    if navigate_url is None:
        navigate_url = _infer_navigate_url(result_data, executed_steps)

    # 兜底摘要（AI 没有生成文字说明时）
    if not final_message:
        final_message = _build_fallback_message(result_data, executed_steps)

    await log_action(db, action="AGENT_EXECUTE", resource_type="AgentQuery", user_id=current_user.id, resource_id=exec_id, old_values=None, new_values={"query": query, "navigate_url": navigate_url})
    await db.commit()
    return {
        "message": final_message,
        "data": result_data,
        "navigate_url": navigate_url,
        "execution_id": exec_id,
        "executed_steps": executed_steps,
    }
