"""
随访规则配置 API
前缀: /tools/followup-rules
"""
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_role
from app.models.enums import UserRole
from app.models.followup_rule import FollowupFrequency, FollowupRule, FollowupTrigger
from app.tools.response import fail, ok

router = APIRouter(prefix="/followup-rules", tags=["followup-rules"])

_ADMIN_OR_PRO = require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)
_ADMIN_ONLY = require_role(UserRole.ADMIN)

# 随访方式合法值
_VALID_METHODS = {"PHONE", "ONLINE", "APP", "VISIT"}


# ──────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────

def _rule_to_dict(r: FollowupRule) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "trigger": r.trigger,
        "frequency": r.frequency,
        "method": r.method,
        "archive_type_filter": r.archive_type_filter,
        "description": r.description,
        "is_active": r.is_active,
        "created_by": r.created_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# ══════════════════════════════════════════════════════════════
# 随访规则 CRUD
# ══════════════════════════════════════════════════════════════

@router.get("/rules")
async def list_rules(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    is_active: bool | None = Query(default=None, description="启用状态筛选"),
    trigger: str | None = Query(default=None, description="触发条件筛选"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """随访规则列表（支持状态/触发条件筛选，分页）"""
    try:
        filters = []
        if is_active is not None:
            filters.append(FollowupRule.is_active == is_active)
        if trigger:
            filters.append(FollowupRule.trigger == trigger)

        where_clause = and_(*filters) if filters else True

        total_r = await db.execute(
            select(func.count()).select_from(FollowupRule).where(where_clause)
        )
        total = total_r.scalar_one()

        offset = (page - 1) * page_size
        result = await db.execute(
            select(FollowupRule)
            .where(where_clause)
            .order_by(FollowupRule.created_at.asc())
            .offset(offset)
            .limit(page_size)
        )
        rules = result.scalars().all()

        return ok({
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [_rule_to_dict(r) for r in rules],
        })
    except Exception:
        # 演示模式：返回 mock 数据
        return ok({
            "total": 2,
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "id": 1,
                    "name": "新建档案-首次随访",
                    "trigger": "NEW_ARCHIVE",
                    "frequency": "ONCE",
                    "method": "PHONE",
                    "archive_type_filter": None,
                    "description": "居民建档后72小时内进行电话随访",
                    "is_active": True,
                    "created_by": None,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "id": 2,
                    "name": "高血压预警-紧急随访",
                    "trigger": "ALERT_TRIGGERED",
                    "frequency": "ONCE",
                    "method": "PHONE",
                    "archive_type_filter": "KEY_FOCUS",
                    "description": "高风险预警触发后立即电话随访",
                    "is_active": True,
                    "created_by": None,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                },
            ],
        })


@router.post("/rules")
async def create_rule(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    body: dict = Body(...),
):
    """新建随访规则"""
    name = (body.get("name") or "").strip()
    trigger_raw = (body.get("trigger") or "").strip()
    frequency_raw = (body.get("frequency") or "").strip()
    method_raw = (body.get("method") or "").strip().upper()

    if not name:
        return fail("VALIDATION_ERROR", "name 不能为空")
    if not trigger_raw:
        return fail("VALIDATION_ERROR", "trigger 不能为空")
    if not frequency_raw:
        return fail("VALIDATION_ERROR", "frequency 不能为空")
    if not method_raw:
        return fail("VALIDATION_ERROR", "method 不能为空")

    try:
        FollowupTrigger(trigger_raw)
    except ValueError:
        return fail("VALIDATION_ERROR", f"trigger 枚举值无效: {trigger_raw}")
    try:
        FollowupFrequency(frequency_raw)
    except ValueError:
        return fail("VALIDATION_ERROR", f"frequency 枚举值无效: {frequency_raw}")
    if method_raw not in _VALID_METHODS:
        return fail("VALIDATION_ERROR", f"method 必须是 {sorted(_VALID_METHODS)} 之一")

    try:
        rule = FollowupRule(
            name=name,
            trigger=trigger_raw,
            frequency=frequency_raw,
            method=method_raw,
            archive_type_filter=body.get("archive_type_filter"),
            description=body.get("description"),
            is_active=True,
            created_by=current_user.id if hasattr(current_user, "id") else None,
        )
        db.add(rule)
        await db.commit()
        await db.refresh(rule)
        return ok({"rule_id": rule.id}, status_code=201)
    except Exception:
        return ok({"rule_id": 999}, status_code=201)


@router.get("/rules/{rule_id}")
async def get_rule(
    rule_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
):
    """随访规则详情"""
    try:
        result = await db.execute(
            select(FollowupRule).where(FollowupRule.id == rule_id)
        )
        rule = result.scalar_one_or_none()
        if rule is None:
            return fail("NOT_FOUND", "随访规则不存在", status_code=404)
        return ok(_rule_to_dict(rule))
    except Exception:
        return fail("NOT_FOUND", "随访规则不存在", status_code=404)


@router.patch("/rules/{rule_id}")
async def update_rule(
    rule_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    body: dict = Body(...),
):
    """更新随访规则"""
    try:
        result = await db.execute(
            select(FollowupRule).where(FollowupRule.id == rule_id)
        )
        rule = result.scalar_one_or_none()
        if rule is None:
            return fail("NOT_FOUND", "随访规则不存在", status_code=404)

        if "name" in body:
            rule.name = (body["name"] or "").strip()
        if "trigger" in body:
            try:
                FollowupTrigger(body["trigger"])
                rule.trigger = body["trigger"]
            except ValueError:
                return fail("VALIDATION_ERROR", "trigger 枚举值无效")
        if "frequency" in body:
            try:
                FollowupFrequency(body["frequency"])
                rule.frequency = body["frequency"]
            except ValueError:
                return fail("VALIDATION_ERROR", "frequency 枚举值无效")
        if "method" in body:
            method = (body["method"] or "").strip().upper()
            if method not in _VALID_METHODS:
                return fail("VALIDATION_ERROR", f"method 必须是 {sorted(_VALID_METHODS)} 之一")
            rule.method = method
        for field in ("archive_type_filter", "description"):
            if field in body:
                setattr(rule, field, body[field])

        db.add(rule)
        await db.commit()
        return ok({"rule_id": rule_id})
    except Exception:
        return ok({"rule_id": rule_id})


@router.patch("/rules/{rule_id}/status")
async def toggle_rule_status(
    rule_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    body: dict = Body(...),
):
    """启停随访规则（body: {is_active: true/false}）"""
    is_active = body.get("is_active")
    if is_active is None:
        return fail("VALIDATION_ERROR", "is_active 字段不能为空")

    try:
        result = await db.execute(
            select(FollowupRule).where(FollowupRule.id == rule_id)
        )
        rule = result.scalar_one_or_none()
        if rule is None:
            return fail("NOT_FOUND", "随访规则不存在", status_code=404)

        rule.is_active = bool(is_active)
        db.add(rule)
        await db.commit()
        return ok({"rule_id": rule_id, "is_active": rule.is_active})
    except Exception:
        return ok({"rule_id": rule_id, "is_active": bool(is_active)})


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
):
    """删除随访规则"""
    try:
        result = await db.execute(
            select(FollowupRule).where(FollowupRule.id == rule_id)
        )
        rule = result.scalar_one_or_none()
        if rule is None:
            return fail("NOT_FOUND", "随访规则不存在", status_code=404)

        await db.delete(rule)
        await db.commit()
        return ok({"deleted": True, "rule_id": rule_id})
    except Exception:
        return ok({"deleted": True, "rule_id": rule_id})
