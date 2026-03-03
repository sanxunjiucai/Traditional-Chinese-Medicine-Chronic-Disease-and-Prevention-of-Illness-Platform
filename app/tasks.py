"""
后台定时任务。
在 app/main.py lifespan 中通过 asyncio 调度，无需 Celery/APScheduler。

任务列表：
- mark_missed_checkins: 每天凌晨 1 点将昨日 PENDING CheckIn 标记为 MISSED
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, select, update

from app.database import AsyncSessionLocal
from app.models.enums import CheckInStatus
from app.models.followup import CheckIn, FollowupTask

logger = logging.getLogger(__name__)


async def mark_missed_checkins() -> int:
    """
    将 scheduled_date < today 且仍为 PENDING 的 CheckIn 标记为 MISSED。
    返回标记条数。
    """
    today = date.today()
    async with AsyncSessionLocal() as db:
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
        count = len(checkins)
        for ci in checkins:
            ci.status = CheckInStatus.MISSED
            db.add(ci)
        await db.commit()
    logger.info("mark_missed_checkins: %d checkins marked as MISSED", count)
    return count


def _seconds_until_next_1am() -> float:
    """计算距明天凌晨 1 点的秒数。"""
    now = datetime.now(timezone.utc)
    tomorrow_1am = (now + timedelta(days=1)).replace(
        hour=1, minute=0, second=0, microsecond=0
    )
    return (tomorrow_1am - now).total_seconds()


async def run_scheduler():
    """每天凌晨 1 点执行一次漏打卡标记，持续运行。"""
    logger.info("Scheduler started, first run in %.0fs", _seconds_until_next_1am())
    while True:
        await asyncio.sleep(_seconds_until_next_1am())
        try:
            await mark_missed_checkins()
        except Exception as exc:
            logger.error("mark_missed_checkins failed: %s", exc)
