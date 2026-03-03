"""
指标录入 + 预警触发集成测试。
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import AlertEvent, AlertRule
from app.models.enums import AlertSeverity, AlertStatus, IndicatorType
from app.services.auth_service import create_access_token
from tests.conftest import make_auth_cookie


@pytest.mark.asyncio
async def test_add_blood_pressure_indicator(async_client: AsyncClient, patient_user, db_session):
    cookies = make_auth_cookie(patient_user)
    resp = await async_client.post(
        "/tools/indicators",
        json={
            "indicator_type": "BLOOD_PRESSURE",
            "values": {"systolic": 120, "diastolic": 80},
        },
        cookies=cookies["cookies"],
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["success"] is True
    assert "indicator_id" in data["data"]


@pytest.mark.asyncio
async def test_high_bp_triggers_alert(async_client: AsyncClient, patient_user, db_session):
    """收缩压185 → 预警事件创建。"""
    # 插入预警规则
    rule = AlertRule(
        name="integration_bp_high",
        indicator_type=IndicatorType.BLOOD_PRESSURE,
        severity=AlertSeverity.HIGH,
        conditions=[{"field": "systolic", "op": ">", "value": 180}],
        message_template="血压异常：收缩压 {systolic}",
        is_active=True,
    )
    db_session.add(rule)
    await db_session.flush()

    cookies = make_auth_cookie(patient_user)
    resp = await async_client.post(
        "/tools/indicators",
        json={
            "indicator_type": "BLOOD_PRESSURE",
            "values": {"systolic": 185, "diastolic": 95},
        },
        cookies=cookies["cookies"],
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["alerts_created"] >= 1


@pytest.mark.asyncio
async def test_list_indicators_trend(async_client: AsyncClient, patient_user, db_session):
    """多次录入后，查询趋势应返回正确数量。"""
    cookies = make_auth_cookie(patient_user)

    for systolic in [120, 125, 130]:
        await async_client.post(
            "/tools/indicators",
            json={
                "indicator_type": "BLOOD_PRESSURE",
                "values": {"systolic": systolic, "diastolic": 80},
            },
            cookies=cookies["cookies"],
        )

    resp = await async_client.get(
        "/tools/indicators?indicator_type=BLOOD_PRESSURE&days=7",
        cookies=cookies["cookies"],
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) >= 3
    # 验证返回结构
    assert "values" in data[0]
    assert "recorded_at" in data[0]
