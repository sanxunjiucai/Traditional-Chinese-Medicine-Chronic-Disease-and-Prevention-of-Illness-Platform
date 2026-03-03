"""
预警管理流程集成测试：预警 → ack → close。
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import AlertRule
from app.models.enums import AlertSeverity, AlertStatus, IndicatorType
from tests.conftest import make_auth_cookie


async def seed_alert_rule(db: AsyncSession) -> AlertRule:
    rule = AlertRule(
        name="integration_mgmt_rule",
        indicator_type=IndicatorType.BLOOD_PRESSURE,
        severity=AlertSeverity.HIGH,
        conditions=[{"field": "systolic", "op": ">", "value": 180}],
        message_template="测试预警：收缩压 {systolic}",
        is_active=True,
    )
    db.add(rule)
    await db.flush()
    return rule


@pytest.mark.asyncio
async def test_alert_lifecycle(
    async_client: AsyncClient, patient_user, admin_user, db_session
):
    await seed_alert_rule(db_session)

    patient_cookies = make_auth_cookie(patient_user)["cookies"]
    admin_cookies = make_auth_cookie(admin_user)["cookies"]

    # 1. 患者录入高血压指标触发预警
    resp = await async_client.post(
        "/tools/indicators",
        json={"indicator_type": "BLOOD_PRESSURE", "values": {"systolic": 185, "diastolic": 95}},
        cookies=patient_cookies,
    )
    assert resp.json()["data"]["alerts_created"] >= 1

    # 2. 管理端查看所有预警
    resp = await async_client.get(
        "/tools/alerts/admin?status=OPEN",
        cookies=admin_cookies,
    )
    assert resp.status_code == 200
    alerts = resp.json()["data"]
    assert len(alerts) >= 1
    event_id = alerts[0]["id"]
    assert alerts[0]["status"] == "OPEN"

    # 3. 确认预警 OPEN → ACKED
    resp = await async_client.patch(
        f"/tools/alerts/{event_id}/ack",
        cookies=admin_cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ACKED"

    # 4. 重复 ack 应返回 STATE_ERROR
    resp = await async_client.patch(
        f"/tools/alerts/{event_id}/ack",
        cookies=admin_cookies,
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "STATE_ERROR"

    # 5. 关闭预警 ACKED → CLOSED
    resp = await async_client.patch(
        f"/tools/alerts/{event_id}/close",
        json={"handler_note": "已联系患者，建议就医"},
        cookies=admin_cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "CLOSED"

    # 6. 验证状态已更新
    resp = await async_client.get("/tools/alerts/admin?status=CLOSED", cookies=admin_cookies)
    closed = [a for a in resp.json()["data"] if a["id"] == event_id]
    assert len(closed) == 1
    assert closed[0]["handler_note"] == "已联系患者，建议就医"


@pytest.mark.asyncio
async def test_patient_cannot_access_admin_alerts(
    async_client: AsyncClient, patient_user
):
    cookies = make_auth_cookie(patient_user)["cookies"]
    resp = await async_client.get("/tools/alerts/admin", cookies=cookies)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_ERROR"
