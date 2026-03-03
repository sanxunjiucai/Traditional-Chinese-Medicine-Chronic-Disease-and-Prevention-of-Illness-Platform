"""
预警引擎单测（使用 DB fixture）。
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.alert import AlertEvent, AlertRule
from app.models.enums import AlertSeverity, AlertStatus, IndicatorType
from app.models.health import HealthIndicator
from app.services.alert_engine import _evaluate_condition, _all_conditions_met, check_indicator


# ── 纯逻辑单测（不需要 DB）──

def test_evaluate_condition_greater():
    assert _evaluate_condition({"systolic": 185}, {"field": "systolic", "op": ">", "value": 180})


def test_evaluate_condition_not_triggered():
    assert not _evaluate_condition({"systolic": 120}, {"field": "systolic", "op": ">", "value": 180})


def test_evaluate_condition_missing_field():
    assert not _evaluate_condition({}, {"field": "systolic", "op": ">", "value": 180})


def test_all_conditions_met_single():
    conds = [{"field": "systolic", "op": ">", "value": 180}]
    assert _all_conditions_met({"systolic": 185}, conds)


def test_all_conditions_met_multiple_and():
    conds = [
        {"field": "systolic", "op": ">", "value": 180},
        {"field": "diastolic", "op": ">", "value": 120},
    ]
    assert _all_conditions_met({"systolic": 185, "diastolic": 125}, conds)
    assert not _all_conditions_met({"systolic": 185, "diastolic": 115}, conds)


def test_all_conditions_met_lte():
    conds = [{"field": "value", "op": "<=", "value": 3.9}]
    assert _all_conditions_met({"value": 3.5}, conds)
    assert not _all_conditions_met({"value": 4.0}, conds)


# ── 集成单测（使用 test DB）──

@pytest.mark.asyncio
async def test_check_indicator_creates_alert(db_session, patient_user):
    """收缩压185 → 触发预警规则 → 创建 AlertEvent。"""
    # 插入预警规则
    rule = AlertRule(
        name="test_systolic_high",
        indicator_type=IndicatorType.BLOOD_PRESSURE,
        severity=AlertSeverity.HIGH,
        conditions=[{"field": "systolic", "op": ">", "value": 180}],
        message_template="收缩压 {systolic} 超标，请及时就医！",
        is_active=True,
    )
    db_session.add(rule)
    await db_session.flush()

    indicator = HealthIndicator(
        user_id=patient_user.id,
        indicator_type=IndicatorType.BLOOD_PRESSURE,
        values={"systolic": 185, "diastolic": 95},
        recorded_at=datetime.now(timezone.utc),
    )
    db_session.add(indicator)
    await db_session.flush()

    events = await check_indicator(db_session, patient_user.id, indicator)
    assert len(events) == 1
    assert events[0].severity == AlertSeverity.HIGH
    assert events[0].status == AlertStatus.OPEN


@pytest.mark.asyncio
async def test_check_indicator_normal_no_alert(db_session, patient_user):
    """正常血压不触发预警。"""
    rule = AlertRule(
        name="test_systolic_high_2",
        indicator_type=IndicatorType.BLOOD_PRESSURE,
        severity=AlertSeverity.HIGH,
        conditions=[{"field": "systolic", "op": ">", "value": 180}],
        message_template="收缩压异常",
        is_active=True,
    )
    db_session.add(rule)
    await db_session.flush()

    indicator = HealthIndicator(
        user_id=patient_user.id,
        indicator_type=IndicatorType.BLOOD_PRESSURE,
        values={"systolic": 120, "diastolic": 80},
        recorded_at=datetime.now(timezone.utc),
    )
    db_session.add(indicator)
    await db_session.flush()

    events = await check_indicator(db_session, patient_user.id, indicator)
    assert len(events) == 0


@pytest.mark.asyncio
async def test_check_indicator_no_duplicate(db_session, patient_user):
    """同一规则已有 OPEN 事件时不重复创建。"""
    rule = AlertRule(
        name="test_no_dup",
        indicator_type=IndicatorType.BLOOD_PRESSURE,
        severity=AlertSeverity.HIGH,
        conditions=[{"field": "systolic", "op": ">", "value": 180}],
        message_template="重复测试",
        is_active=True,
    )
    db_session.add(rule)
    await db_session.flush()

    # 第一次录入触发
    ind1 = HealthIndicator(
        user_id=patient_user.id, indicator_type=IndicatorType.BLOOD_PRESSURE,
        values={"systolic": 185, "diastolic": 95}, recorded_at=datetime.now(timezone.utc),
    )
    db_session.add(ind1)
    await db_session.flush()
    events1 = await check_indicator(db_session, patient_user.id, ind1)
    assert len(events1) == 1

    # 第二次录入，已有 OPEN → 不新建
    ind2 = HealthIndicator(
        user_id=patient_user.id, indicator_type=IndicatorType.BLOOD_PRESSURE,
        values={"systolic": 190, "diastolic": 100}, recorded_at=datetime.now(timezone.utc),
    )
    db_session.add(ind2)
    await db_session.flush()
    events2 = await check_indicator(db_session, patient_user.id, ind2)
    assert len(events2) == 0
