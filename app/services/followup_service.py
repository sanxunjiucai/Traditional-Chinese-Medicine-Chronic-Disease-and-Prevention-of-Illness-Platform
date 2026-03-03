import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import CheckInStatus, DiseaseType, FollowupStatus, TaskType
from app.models.followup import CheckIn, FollowupPlan, FollowupTask, FollowupTemplate


async def start_plan(
    db: AsyncSession,
    user_id: uuid.UUID,
    disease_type: DiseaseType,
    start_date: date | None = None,
) -> FollowupPlan:
    """
    从模板创建30天随访计划，并生成每日任务（CheckIn PENDING）。
    """
    if start_date is None:
        start_date = date.today()

    # 查询模板
    template_result = await db.execute(
        select(FollowupTemplate).where(
            and_(
                FollowupTemplate.disease_type == disease_type,
                FollowupTemplate.is_active == True,  # noqa: E712
            )
        ).limit(1)
    )
    template = template_result.scalar_one_or_none()

    duration_days = template.duration_days if template else 30
    end_date = start_date + timedelta(days=duration_days - 1)

    plan = FollowupPlan(
        user_id=user_id,
        template_id=template.id if template else None,
        disease_type=disease_type,
        status=FollowupStatus.ACTIVE,
        start_date=start_date,
        end_date=end_date,
    )
    db.add(plan)
    await db.flush()

    # 生成任务
    task_definitions = template.tasks if template else _default_tasks(disease_type)
    for day_offset in range(duration_days):
        scheduled = start_date + timedelta(days=day_offset)
        day_num = day_offset + 1
        for task_def in task_definitions:
            # 检查该任务是否在当天执行
            if task_def.get("every_day", True):
                pass
            elif day_num not in task_def.get("days", []):
                continue

            task = FollowupTask(
                plan_id=plan.id,
                task_type=TaskType(task_def["task_type"]),
                name=task_def["name"],
                scheduled_date=scheduled,
                required=task_def.get("required", True),
                meta=task_def.get("meta"),
            )
            db.add(task)
            await db.flush()

            checkin = CheckIn(
                task_id=task.id,
                user_id=user_id,
                status=CheckInStatus.PENDING,
            )
            db.add(checkin)

    await db.flush()
    return plan


def _default_tasks(disease_type: DiseaseType) -> list[dict]:
    if disease_type == DiseaseType.HYPERTENSION:
        return [
            {"task_type": "INDICATOR_REPORT", "name": "记录血压", "required": True,
             "every_day": True, "meta": {"indicator_type": "BLOOD_PRESSURE"}},
            {"task_type": "EXERCISE", "name": "适量运动30分钟", "required": False, "every_day": True},
            {"task_type": "MEDICATION", "name": "按时用药", "required": True, "every_day": True},
        ]
    else:  # DIABETES_T2
        return [
            {"task_type": "INDICATOR_REPORT", "name": "记录空腹血糖", "required": True,
             "every_day": True, "meta": {"indicator_type": "BLOOD_GLUCOSE", "scene": "fasting"}},
            {"task_type": "INDICATOR_REPORT", "name": "记录餐后2小时血糖", "required": True,
             "every_day": True, "meta": {"indicator_type": "BLOOD_GLUCOSE", "scene": "postmeal_2h"}},
            {"task_type": "EXERCISE", "name": "餐后散步20分钟", "required": False, "every_day": True},
            {"task_type": "MEDICATION", "name": "按时用药", "required": True, "every_day": True},
        ]


async def record_checkin(
    db: AsyncSession,
    task_id: uuid.UUID,
    user_id: uuid.UUID,
    value: dict | None = None,
    note: str | None = None,
) -> CheckIn:
    """
    记录打卡，状态 PENDING → DONE。
    """
    result = await db.execute(
        select(CheckIn).where(
            and_(CheckIn.task_id == task_id, CheckIn.user_id == user_id)
        )
    )
    checkin = result.scalar_one_or_none()

    if checkin is None:
        # 直接创建（理论上不会，但容错）
        checkin = CheckIn(
            task_id=task_id,
            user_id=user_id,
            status=CheckInStatus.DONE,
            value=value,
            note=note,
            checked_at=datetime.now(timezone.utc),
        )
        db.add(checkin)
    else:
        checkin.status = CheckInStatus.DONE
        checkin.value = value
        checkin.note = note
        checkin.checked_at = datetime.now(timezone.utc)
        db.add(checkin)

    await db.flush()
    return checkin


async def mark_missed(db: AsyncSession) -> int:
    """
    将所有过期的 PENDING CheckIn 标记为 MISSED。
    返回处理数量。
    """
    today = date.today()
    result = await db.execute(
        select(CheckIn)
        .join(FollowupTask, CheckIn.task_id == FollowupTask.id)
        .where(
            and_(
                CheckIn.status == CheckInStatus.PENDING,
                FollowupTask.scheduled_date < today,
            )
        )
    )
    checkins = result.scalars().all()
    for checkin in checkins:
        checkin.status = CheckInStatus.MISSED
        db.add(checkin)
    await db.flush()
    return len(checkins)


async def get_adherence(db: AsyncSession, plan_id: uuid.UUID) -> float:
    """
    计算随访计划的依从率：done / (done + missed)
    """
    result = await db.execute(
        select(
            CheckIn.status,
            func.count(CheckIn.id).label("cnt"),
        )
        .join(FollowupTask, CheckIn.task_id == FollowupTask.id)
        .where(FollowupTask.plan_id == plan_id)
        .group_by(CheckIn.status)
    )
    rows = result.all()
    counts = {r.status: r.cnt for r in rows}
    done = counts.get(CheckInStatus.DONE, 0)
    missed = counts.get(CheckInStatus.MISSED, 0)
    total = done + missed
    if total == 0:
        return 0.0
    return round(done / total * 100, 1)
