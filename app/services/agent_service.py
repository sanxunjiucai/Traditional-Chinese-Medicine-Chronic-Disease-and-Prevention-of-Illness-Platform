"""
Agent Service: 解析自然语言意图，通过 Claude tool-use 调用平台内置工具，返回结构化结果。
每次执行均写入 AuditLog（action=AGENT_EXECUTE）以支持审计与回归。
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

_SYSTEM_PROMPT = """你是「治未病平台」的智能医疗助手，帮助医生高效完成日常诊疗操作。

你可以：
- 按姓名/手机号搜索患者
- 查看平台预警事件（可按严重程度、状态筛选）
- 查看随访质控概览（依从率最低的患者）
- 获取平台统计概览
- 确认（处置）指定预警
- 跳转到相关管理页面

规则：
- 使用中文回答，语言简洁友好
- 不要捏造数据，所有数据来自工具返回
- 遇到需要执行的操作，先调用工具，再用工具结果生成回复
- 如果用户意图不明确，先给出最可能的理解并执行，并告知用户可以进一步细化
"""

# ── 工具定义（Claude tool schema）───────────────────────────────────────────

AGENT_TOOLS = [
    {
        "name": "search_patients",
        "description": "按姓名或手机号关键词搜索患者，返回匹配的患者列表",
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "姓名或手机号关键词"},
                "is_active": {
                    "type": "boolean",
                    "description": "仅返回启用(true)或禁用(false)的患者；不填则全部返回",
                },
            },
            "required": ["q"],
        },
    },
    {
        "name": "get_alert_list",
        "description": "查看预警事件列表，可按状态（OPEN/ACKED/CLOSED）和严重程度（LOW/MEDIUM/HIGH）筛选",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["OPEN", "ACKED", "CLOSED"],
                    "description": "预警状态；不填则返回所有状态",
                },
                "severity": {
                    "type": "string",
                    "enum": ["LOW", "MEDIUM", "HIGH"],
                    "description": "严重程度；不填则返回所有级别",
                },
                "limit": {"type": "integer", "description": "最多返回条数，默认 10，最大 50"},
            },
        },
    },
    {
        "name": "get_followup_overview",
        "description": "查看随访质控概览，返回依从率最低的患者随访计划，帮助识别需要重点关注的患者",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回条数，默认 5，最大 20"},
            },
        },
    },
    {
        "name": "get_stats_overview",
        "description": "获取平台整体统计：患者总数、在管患者数、开放预警数、高危预警数",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "ack_alert",
        "description": "确认（处置）一条 OPEN 状态的预警事件，状态将变为 ACKED",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "预警事件的 UUID"},
                "note": {"type": "string", "description": "处置备注说明"},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "navigate_to",
        "description": "跳转到平台指定页面",
        "input_schema": {
            "type": "object",
            "properties": {
                "page": {
                    "type": "string",
                    "enum": ["patients", "alerts", "followup", "stats", "audit", "content"],
                    "description": "目标页面：patients=患者管理, alerts=预警处置, followup=随访质控, stats=统计报表, audit=审计日志, content=内容管理",
                },
                "query_params": {
                    "type": "string",
                    "description": "附加到 URL 的查询参数字符串，如 q=张三&is_active=true",
                },
            },
            "required": ["page"],
        },
    },
]

_PAGE_URL_MAP = {
    "patients": "/gui/admin/patients",
    "alerts": "/gui/admin/alerts",
    "followup": "/gui/admin/followup",
    "stats": "/gui/admin/stats",
    "audit": "/gui/admin/audit",
    "content": "/gui/admin/content",
}

# ── 工具执行器 ───────────────────────────────────────────────────────────────


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


async def _exec_navigate_to(args: dict) -> dict:
    page = args["page"]
    qp = args.get("query_params", "").strip()
    url = _PAGE_URL_MAP.get(page, "/gui/admin/alerts")
    if qp:
        url = f"{url}?{qp}"
    return {"url": url, "page": page}


# ── 工具分发 ─────────────────────────────────────────────────────────────────


async def _execute_tool(
    name: str, args: dict, db: AsyncSession, current_user: Any
) -> Any:
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
    if name == "navigate_to":
        return await _exec_navigate_to(args)
    return {"error": f"未知工具: {name}"}


# ── 主入口 ────────────────────────────────────────────────────────────────────


async def run_agent(
    query: str,
    db: AsyncSession,
    current_user: Any,
) -> dict:
    """
    执行自然语言查询，返回：
      {message, data, navigate_url, execution_id}

    - message: 给用户看的文字说明
    - data: 结构化数据（查询结果）
    - navigate_url: 如果需要跳转，前端应导航到此 URL
    - execution_id: 本次执行唯一 ID（用于审计追溯）
    """
    exec_id = str(uuid.uuid4())

    # API key 未配置时退化为提示
    if not settings.anthropic_api_key:
        return {
            "message": "AI 助手尚未配置（请在 .env 中填写 ANTHROPIC_API_KEY）",
            "data": None,
            "navigate_url": None,
            "execution_id": exec_id,
        }

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    messages: list[dict] = [{"role": "user", "content": query}]

    result_data: dict | None = None
    navigate_url: str | None = None
    final_message = ""

    # Claude tool-use 循环（最多 4 轮，防止无限循环）
    for _ in range(4):
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            tools=AGENT_TOOLS,
            messages=messages,
        )

        text_parts = [b.text for b in response.content if b.type == "text"]
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            final_message = " ".join(text_parts).strip()
            break

        # 将 assistant 回复加入对话历史
        messages.append({"role": "assistant", "content": response.content})

        # 并行执行所有工具调用
        tool_results = []
        for tb in tool_use_blocks:
            output = await _execute_tool(tb.name, tb.input, db, current_user)

            if tb.name == "navigate_to":
                navigate_url = output.get("url")
            elif "error" not in output:
                result_data = output  # 保留最后一个有效数据结果

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tb.id,
                    "content": json.dumps(output, ensure_ascii=False, default=str),
                }
            )

        messages.append({"role": "user", "content": tool_results})

        if response.stop_reason == "end_turn":
            final_message = " ".join(text_parts).strip()
            break
    else:
        final_message = "操作已执行完毕。"

    # 写审计日志
    await log_action(
        db,
        action="AGENT_EXECUTE",
        resource_type="AgentQuery",
        user_id=current_user.id,
        resource_id=exec_id,
        old_values=None,
        new_values={"query": query, "navigate_url": navigate_url},
    )
    await db.commit()

    return {
        "message": final_message,
        "data": result_data,
        "navigate_url": navigate_url,
        "execution_id": exec_id,
    }
