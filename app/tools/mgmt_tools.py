"""
管理中心 API：机构管理、角色管理、系统配置、定时任务。
所有接口均需 ADMIN 角色。
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import require_role
from app.models.enums import OrgLevel, ScheduledTaskStatus, UserRole
from app.models.config import ScheduledTask, SystemConfig
from app.models.org import Department, Organization, SystemRole
from app.tools.response import fail, ok

router = APIRouter(prefix="/mgmt", tags=["mgmt"])

_ADMIN_ONLY = require_role(UserRole.ADMIN)
_ADMIN_OR_PRO = require_role(UserRole.ADMIN, UserRole.PROFESSIONAL)


# ════════════════════════════════════
# 机构管理
# ════════════════════════════════════

@router.get("/orgs")
async def list_orgs(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    level: OrgLevel | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    filters = []
    if level:
        filters.append(Organization.level == level)
    if q:
        filters.append(Organization.name.contains(q))

    total_r = await db.execute(
        select(func.count()).select_from(Organization)
        .where(and_(*filters) if filters else True)
    )
    total = total_r.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        select(Organization)
        .where(and_(*filters) if filters else True)
        .order_by(Organization.created_at.asc())
        .offset(offset)
        .limit(page_size)
    )
    orgs = result.scalars().all()

    return ok({
        "total": total, "page": page, "page_size": page_size,
        "items": [
            {
                "id": str(o.id),
                "name": o.name,
                "code": o.code,
                "level": o.level.value,
                "parent_id": str(o.parent_id) if o.parent_id else None,
                "address": o.address,
                "phone": o.phone,
                "is_active": o.is_active,
                "created_at": o.created_at.isoformat(),
            }
            for o in orgs
        ],
    })


@router.post("/orgs")
async def create_org(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
    body: dict = Body(...),
):
    name = body.get("name", "").strip()
    if not name:
        return fail("VALIDATION_ERROR", "name 不能为空")
    try:
        level = OrgLevel(body.get("level", "HOSPITAL"))
    except ValueError:
        return fail("VALIDATION_ERROR", "level 枚举值无效")

    parent_id = None
    if body.get("parent_id"):
        try:
            parent_id = uuid.UUID(body["parent_id"])
        except ValueError:
            return fail("VALIDATION_ERROR", "parent_id 格式无效")

    org = Organization(
        name=name,
        code=body.get("code"),
        level=level,
        parent_id=parent_id,
        address=body.get("address"),
        phone=body.get("phone"),
        description=body.get("description"),
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return ok({"org_id": str(org.id)})


@router.patch("/orgs/{org_id}")
async def update_org(
    org_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
    body: dict = Body(...),
):
    result = await db.execute(
        select(Organization).where(Organization.id == uuid.UUID(org_id))
    )
    org = result.scalar_one_or_none()
    if org is None:
        return fail("NOT_FOUND", "机构不存在", status_code=404)

    for field in ("name", "code", "address", "phone", "description"):
        if field in body:
            setattr(org, field, body[field])
    if "is_active" in body:
        org.is_active = bool(body["is_active"])

    db.add(org)
    await db.commit()
    return ok({"org_id": org_id})


@router.delete("/orgs/{org_id}")
async def delete_org(
    org_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
):
    result = await db.execute(
        select(Organization).where(Organization.id == uuid.UUID(org_id))
    )
    org = result.scalar_one_or_none()
    if org is None:
        return fail("NOT_FOUND", "机构不存在", status_code=404)
    org.is_active = False
    db.add(org)
    await db.commit()
    return ok({"deleted": True})


# ── 科室 ──

@router.get("/orgs/{org_id}/departments")
async def list_departments(
    org_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
):
    result = await db.execute(
        select(Department)
        .where(Department.org_id == uuid.UUID(org_id))
        .order_by(Department.created_at.asc())
    )
    depts = result.scalars().all()
    return ok([
        {
            "id": str(d.id),
            "name": d.name,
            "code": d.code,
            "parent_id": str(d.parent_id) if d.parent_id else None,
            "manager_name": d.manager_name,
            "phone": d.phone,
            "is_active": d.is_active,
        }
        for d in depts
    ])


@router.post("/orgs/{org_id}/departments")
async def create_department(
    org_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
    body: dict = Body(...),
):
    name = body.get("name", "").strip()
    if not name:
        return fail("VALIDATION_ERROR", "name 不能为空")

    dept = Department(
        org_id=uuid.UUID(org_id),
        name=name,
        code=body.get("code"),
        address=body.get("address"),
        phone=body.get("phone"),
        manager_name=body.get("manager_name"),
        description=body.get("description"),
    )
    db.add(dept)
    await db.commit()
    await db.refresh(dept)
    return ok({"dept_id": str(dept.id)})


# ════════════════════════════════════
# 角色管理
# ════════════════════════════════════

@router.get("/roles")
async def list_roles(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    total_r = await db.execute(select(func.count()).select_from(SystemRole))
    total = total_r.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        select(SystemRole)
        .order_by(SystemRole.created_at.asc())
        .offset(offset)
        .limit(page_size)
    )
    roles = result.scalars().all()

    return ok({
        "total": total, "page": page, "page_size": page_size,
        "items": [
            {
                "id": str(r.id),
                "name": r.name,
                "code": r.code,
                "description": r.description,
                "permissions": r.permissions,
                "is_active": r.is_active,
                "created_at": r.created_at.isoformat(),
            }
            for r in roles
        ],
    })


@router.post("/roles")
async def create_role(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
    body: dict = Body(...),
):
    name = body.get("name", "").strip()
    code = body.get("code", "").strip()
    if not name or not code:
        return fail("VALIDATION_ERROR", "name 和 code 不能为空")

    role = SystemRole(
        name=name,
        code=code,
        description=body.get("description"),
        permissions=body.get("permissions", []),
    )
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return ok({"role_id": str(role.id)})


@router.patch("/roles/{role_id}")
async def update_role(
    role_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
    body: dict = Body(...),
):
    result = await db.execute(
        select(SystemRole).where(SystemRole.id == uuid.UUID(role_id))
    )
    role = result.scalar_one_or_none()
    if role is None:
        return fail("NOT_FOUND", "角色不存在", status_code=404)

    for field in ("name", "description", "permissions"):
        if field in body:
            setattr(role, field, body[field])
    if "is_active" in body:
        role.is_active = bool(body["is_active"])

    db.add(role)
    await db.commit()
    return ok({"role_id": role_id})


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
):
    result = await db.execute(
        select(SystemRole).where(SystemRole.id == uuid.UUID(role_id))
    )
    role = result.scalar_one_or_none()
    if role is None:
        return fail("NOT_FOUND", "角色不存在", status_code=404)
    await db.delete(role)
    await db.commit()
    return ok({"deleted": True})


# ════════════════════════════════════
# 系统配置
# ════════════════════════════════════

@router.get("/settings")
async def list_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
    group: str | None = Query(default=None),
):
    filters = []
    if group:
        filters.append(SystemConfig.group == group)

    result = await db.execute(
        select(SystemConfig)
        .where(and_(*filters) if filters else True)
        .order_by(SystemConfig.group.asc(), SystemConfig.key.asc())
    )
    configs = result.scalars().all()
    return ok([
        {
            "id": str(c.id),
            "key": c.key,
            "value": c.value,
            "description": c.description,
            "group": c.group,
            "is_public": c.is_public,
        }
        for c in configs
    ])


@router.put("/settings/{key}")
async def upsert_setting(
    key: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
    body: dict = Body(...),
):
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == key)
    )
    config = result.scalar_one_or_none()
    if config is None:
        config = SystemConfig(
            key=key,
            value=str(body.get("value", "")),
            description=body.get("description"),
            group=body.get("group", "general"),
            is_public=body.get("is_public", False),
        )
    else:
        config.value = str(body.get("value", ""))
        if "description" in body:
            config.description = body["description"]
        if "group" in body:
            config.group = body["group"]

    db.add(config)
    await db.commit()
    return ok({"key": key})


# ════════════════════════════════════
# 定时任务
# ════════════════════════════════════

@router.get("/tasks")
async def list_tasks(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_OR_PRO),
):
    result = await db.execute(
        select(ScheduledTask).order_by(ScheduledTask.created_at.asc())
    )
    tasks = result.scalars().all()
    return ok([
        {
            "id": str(t.id),
            "name": t.name,
            "task_key": t.task_key,
            "description": t.description,
            "cron_expr": t.cron_expr,
            "status": t.status.value,
            "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
            "next_run_at": t.next_run_at.isoformat() if t.next_run_at else None,
            "last_result": t.last_result,
            "run_count": t.run_count,
        }
        for t in tasks
    ])


@router.post("/tasks")
async def create_task(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
    body: dict = Body(...),
):
    name = body.get("name", "").strip()
    task_key = body.get("task_key", "").strip()
    if not name or not task_key:
        return fail("VALIDATION_ERROR", "name 和 task_key 不能为空")

    # 检查 task_key 唯一性
    existing = await db.execute(
        select(ScheduledTask).where(ScheduledTask.task_key == task_key)
    )
    if existing.scalar_one_or_none():
        return fail("VALIDATION_ERROR", f"task_key '{task_key}' 已存在")

    task = ScheduledTask(
        name=name,
        task_key=task_key,
        description=body.get("description"),
        cron_expr=body.get("cron_expr"),
        params=body.get("params"),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return ok({"task_id": str(task.id)})


@router.patch("/tasks/{task_id}/toggle")
async def toggle_task(
    task_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
):
    result = await db.execute(
        select(ScheduledTask).where(ScheduledTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if task is None:
        return fail("NOT_FOUND", "任务不存在", status_code=404)

    task.status = (
        ScheduledTaskStatus.DISABLED
        if task.status == ScheduledTaskStatus.ACTIVE
        else ScheduledTaskStatus.ACTIVE
    )
    db.add(task)
    await db.commit()
    return ok({"task_id": task_id, "status": task.status.value})


@router.post("/tasks/{task_id}/run")
async def run_task_now(
    task_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(_ADMIN_ONLY),
):
    """手动立即执行一次（模拟执行，记录运行计数）。"""
    from datetime import datetime, timezone

    result = await db.execute(
        select(ScheduledTask).where(ScheduledTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if task is None:
        return fail("NOT_FOUND", "任务不存在", status_code=404)

    task.run_count += 1
    task.last_run_at = datetime.now(timezone.utc)
    task.last_result = "手动触发执行成功"
    db.add(task)
    await db.commit()
    return ok({"task_id": task_id, "run_count": task.run_count})
