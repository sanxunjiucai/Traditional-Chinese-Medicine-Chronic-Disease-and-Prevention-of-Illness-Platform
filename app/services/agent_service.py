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
    }
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
        "糖尿病": DiseaseType.DIABETES,
        "冠心病": DiseaseType.CHD,
        "脑卒中": DiseaseType.STROKE,
        "慢阻肺": DiseaseType.COPD,
        "肿瘤": DiseaseType.TUMOR,
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


async def _exec_navigate_to(args: dict) -> dict:
    page = args["page"]
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
    "search_patient":        "搜索患者",
    "get_alert_list":        "查询预警",
    "get_followup_overview": "查询随访",
    "get_stats_overview":    "查询统计",
    "create_followup_task":  "创建随访计划",
    "analyze_patient_risk":  "分析患者风险",
    "generate_tcm_plan":     "生成调理方案",
    "issue_plan":            "发布调理方案",
    "ack_alert":             "确认预警",
    "navigate_to":           "页面跳转",
    "call_api":              "调用接口",
    "create_archive":        "新建居民档案",
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
    return {"error": f"未知工具: {name}"}


# ── 主入口 ────────────────────────────────────────────────────────────────────


async def run_agent(query: str, db: AsyncSession, current_user: Any) -> dict:
    exec_id = str(uuid.uuid4())
    if not settings.anthropic_api_key:
        return {"message": "AI 助手暂时不可用（API key 未正确配置）。", "data": None, "navigate_url": None, "execution_id": exec_id}
    
    import os, httpx, json as json_lib
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    messages = [{"role": "user", "content": query}]
    result_data, navigate_url, final_message = None, None, ""
    executed_steps: list = []

    if base_url:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                for _ in range(4):
                    resp = await client.post(f"{base_url}/v1/messages", headers={"Content-Type": "application/json", "x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01"}, json={"model": "claude-haiku-4-5-20251001", "max_tokens": 1024, "system": _SYSTEM_PROMPT, "tools": AGENT_TOOLS, "messages": messages})
                    data = resp.json()
                    texts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
                    tools = [b for b in data.get("content", []) if b.get("type") == "tool_use"]
                    if not tools:
                        final_message = " ".join(texts).strip()
                        break
                    messages.append({"role": "assistant", "content": data["content"]})
                    results = []
                    for t in tools:
                        out = await _execute_tool(t["name"], t["input"], db, current_user)
                        executed_steps.append({
                            "tool": t["name"],
                            "label": _TOOL_LABELS.get(t["name"], t["name"]),
                            "summary": _tool_summary(t["name"], t["input"], out),
                            "status": "error" if "error" in out else "success",
                        })
                        if t["name"] == "navigate_to":
                            navigate_url = out.get("url")
                        elif "error" not in out:
                            result_data = out
                        results.append({"type": "tool_result", "tool_use_id": t["id"], "content": json_lib.dumps(out, ensure_ascii=False, default=str)})
                    messages.append({"role": "user", "content": results})
                    if data.get("stop_reason") == "end_turn":
                        final_message = " ".join(texts).strip()
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
