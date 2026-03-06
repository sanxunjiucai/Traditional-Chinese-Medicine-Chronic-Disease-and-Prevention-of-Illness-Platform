"""
后台定时任务。
在 app/main.py lifespan 中通过 asyncio 调度，无需 Celery/APScheduler。

任务列表：
- mark_missed_checkins:        每天凌晨 1 点将昨日 PENDING CheckIn 标记为 MISSED
- scan_new_lab_reports:        每 5 分钟扫描新检验报告，自动触发 AI 风险分析
- scan_overdue_followup:       每天凌晨 2 点推送随访逾期提醒
- scan_no_visit_patients:      每天凌晨 3 点推送长期未复诊提醒
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.enums import CheckInStatus, FollowupStatus
from app.models.followup import CheckIn, FollowupPlan, FollowupTask
from app.models.archive import PatientArchive
from app.models.clinical import ClinicalDocument
from app.models.notification import Notification

logger = logging.getLogger(__name__)


# ── 工具函数 ───────────────────────────────────────────────────────────

def _seconds_until_next(hour: int, minute: int = 0) -> float:
    """计算距今天/明天指定时间的剩余秒数（使用本地时间）。"""
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


# ── 任务实现 ───────────────────────────────────────────────────────────

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


async def scan_new_lab_reports() -> int:
    """
    扫描最近 6 分钟内新增的 LAB_REPORT 文档，
    对每个涉及的患者档案自动触发 AI 风险分析 + 预警扫描。
    返回处理的档案数。
    """
    from app.services.risk_engine import auto_scan_and_alert

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=6)
    processed = 0

    async with AsyncSessionLocal() as db:
        # 找到最近新增的 LAB_REPORT 涉及的唯一 archive_id
        result = await db.execute(
            select(distinct(ClinicalDocument.archive_id)).where(
                ClinicalDocument.doc_type == "LAB_REPORT",
                ClinicalDocument.archive_id.is_not(None),
                ClinicalDocument.created_at >= cutoff,
            )
        )
        archive_ids = result.scalars().all()

        for archive_id in archive_ids:
            try:
                await auto_scan_and_alert(db, archive_id)
                processed += 1
            except Exception as exc:
                logger.warning("auto_scan_and_alert failed for %s: %s", archive_id, exc)

        if archive_ids:
            await db.commit()

    if processed:
        logger.info("scan_new_lab_reports: processed %d archives", processed)
    return processed


async def scan_overdue_followup() -> int:
    """
    找出随访任务逾期（CheckIn.scheduled_date < today AND status=PENDING）
    且近 7 天内未收到 FOLLOWUP_REMINDER 通知的患者，推送提醒。
    返回推送通知数。
    """
    from app.services.notification_service import push_to_patient

    today = date.today()
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    pushed = 0

    async with AsyncSessionLocal() as db:
        # 找出逾期打卡的患者档案（通过 FollowupPlan.user_id → PatientArchive.user_id）
        result = await db.execute(
            select(distinct(PatientArchive.id))
            .join(FollowupPlan, FollowupPlan.user_id == PatientArchive.user_id)
            .join(FollowupTask, FollowupTask.plan_id == FollowupPlan.id)
            .join(CheckIn, CheckIn.task_id == FollowupTask.id)
            .where(
                PatientArchive.user_id.is_not(None),
                CheckIn.status == CheckInStatus.PENDING,
                FollowupTask.scheduled_date < today,
            )
        )
        overdue_archive_ids = result.scalars().all()

        for archive_id in overdue_archive_ids:
            # 检查近 7 天内是否已发过 FOLLOWUP_REMINDER
            recent = (await db.execute(
                select(func.count()).select_from(Notification).where(
                    Notification.archive_id == archive_id,
                    Notification.notif_type == "FOLLOWUP_REMINDER",
                    Notification.created_at >= seven_days_ago,
                )
            )).scalar_one()

            if recent == 0:
                await push_to_patient(
                    db,
                    archive_id=archive_id,
                    title="随访任务提醒",
                    content="您有未完成的健康随访任务，请及时完成打卡，以便医生跟踪您的健康状况。",
                    notif_type="FOLLOWUP_REMINDER",
                    action_url="/h5/followup",
                )
                pushed += 1

        if pushed:
            await db.commit()

    if pushed:
        logger.info("scan_overdue_followup: pushed %d reminders", pushed)
    return pushed


async def scan_no_visit_patients() -> int:
    """
    找出曾收到"方案下达"推送、但近 90 天内没有新 ClinicalDocument 的患者，
    且近 30 天内未收到"复诊"提醒，推送未复诊提醒。
    返回推送通知数。
    """
    from app.services.notification_service import push_to_patient

    ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    pushed = 0

    async with AsyncSessionLocal() as db:
        # 曾收到方案通知的所有患者 archive_id
        result = await db.execute(
            select(distinct(Notification.archive_id)).where(
                Notification.notif_type == "PLAN_ISSUED"
            )
        )
        plan_archive_ids = set(result.scalars().all())

        for archive_id in plan_archive_ids:
            # 是否有近 90 天内的 ClinicalDocument
            recent_doc = (await db.execute(
                select(func.count()).select_from(ClinicalDocument).where(
                    ClinicalDocument.archive_id == archive_id,
                    ClinicalDocument.created_at >= ninety_days_ago,
                )
            )).scalar_one()

            if recent_doc > 0:
                continue  # 最近有就诊记录，跳过

            # 是否近 30 天内已发过"复诊"提醒
            recent_reminder = (await db.execute(
                select(func.count()).select_from(Notification).where(
                    Notification.archive_id == archive_id,
                    Notification.notif_type == "SYSTEM",
                    Notification.title.like("%复诊%"),
                    Notification.created_at >= thirty_days_ago,
                )
            )).scalar_one()

            if recent_reminder == 0:
                await push_to_patient(
                    db,
                    archive_id=archive_id,
                    title="温馨提醒：建议近期复诊",
                    content="距您上次就诊已超过3个月，建议您近期安排复诊，医生将为您评估健康状况并更新调理方案。",
                    notif_type="SYSTEM",
                    action_url="/h5/consultation/new",
                )
                pushed += 1

        if pushed:
            await db.commit()

    if pushed:
        logger.info("scan_no_visit_patients: pushed %d reminders", pushed)
    return pushed


async def execute_periodic_followup_rules() -> int:
    """
    扫描所有有激活随访计划的患者档案，
    对匹配 MANUAL 触发规则且未在冷却期的档案推送随访提醒。
    返回推送通知数。
    """
    from app.services.followup_service import apply_followup_rules

    pushed = 0
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(distinct(PatientArchive.id))
            .join(FollowupPlan, FollowupPlan.user_id == PatientArchive.user_id)
            .where(
                PatientArchive.user_id.is_not(None),
                FollowupPlan.status == FollowupStatus.ACTIVE,
            )
        )
        archive_ids = result.scalars().all()

        for archive_id in archive_ids:
            try:
                count = await apply_followup_rules(db, "MANUAL", archive_id)
                pushed += count
            except Exception as exc:
                logger.warning("apply_followup_rules MANUAL failed for %s: %s", archive_id, exc)

        if pushed:
            await db.commit()

    if pushed:
        logger.info("execute_periodic_followup_rules: pushed %d reminders", pushed)
    return pushed


# ── 调度器入口 ─────────────────────────────────────────────────────────

async def run_5min_scanner():
    """每 5 分钟执行一次新检验报告扫描（准实时 HIS 数据监控）。"""
    logger.info("5-min scanner started (interval: 300s)")
    while True:
        await asyncio.sleep(300)  # 5 分钟
        try:
            await scan_new_lab_reports()
        except Exception as exc:
            logger.error("scan_new_lab_reports failed: %s", exc)


async def run_scheduler():
    """
    每日定时任务调度器：
    - 凌晨 1:00 标记漏打卡
    - 凌晨 2:00 推送随访逾期提醒
    - 凌晨 3:00 推送未复诊提醒
    """
    logger.info(
        "Daily scheduler started. Next run: 01:00 / 02:00 / 03:00"
    )

    async def _daily_loop(hour: int, task_fn, name: str, minute: int = 0):
        while True:
            wait_secs = _seconds_until_next(hour, minute)
            logger.info("%s: next run in %.0fs (at %02d:%02d)", name, wait_secs, hour, minute)
            await asyncio.sleep(wait_secs)
            try:
                await task_fn()
            except Exception as exc:
                logger.error("%s failed: %s", name, exc)

    # 同时运行四个每日定时任务
    await asyncio.gather(
        _daily_loop(1, mark_missed_checkins, "mark_missed_checkins"),
        _daily_loop(2, scan_overdue_followup, "scan_overdue_followup"),
        _daily_loop(2, execute_periodic_followup_rules, "execute_periodic_followup_rules", minute=30),
        _daily_loop(3, scan_no_visit_patients, "scan_no_visit_patients"),
    )
