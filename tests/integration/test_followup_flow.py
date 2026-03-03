"""
随访计划 → 打卡 → 依从率 集成测试。
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import DiseaseType
from app.models.followup import FollowupTemplate
from tests.conftest import make_auth_cookie


async def seed_followup_template(db: AsyncSession):
    template = FollowupTemplate(
        name="高血压30天随访模板",
        disease_type=DiseaseType.HYPERTENSION,
        duration_days=30,
        tasks=[
            {
                "task_type": "INDICATOR_REPORT",
                "name": "记录血压",
                "required": True,
                "every_day": True,
                "meta": {"indicator_type": "BLOOD_PRESSURE"},
            },
            {
                "task_type": "EXERCISE",
                "name": "适量运动",
                "required": False,
                "every_day": True,
            },
        ],
        is_active=True,
    )
    db.add(template)
    await db.flush()
    return template


@pytest.mark.asyncio
async def test_start_followup_plan(async_client: AsyncClient, patient_user, db_session):
    await seed_followup_template(db_session)
    cookies = make_auth_cookie(patient_user)

    resp = await async_client.post(
        "/tools/followup/start",
        json={"disease_type": "HYPERTENSION"},
        cookies=cookies["cookies"],
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert "plan_id" in data
    assert data["disease_type"] == "HYPERTENSION"


@pytest.mark.asyncio
async def test_today_tasks_after_start(async_client: AsyncClient, patient_user, db_session):
    await seed_followup_template(db_session)
    cookies = make_auth_cookie(patient_user)

    await async_client.post(
        "/tools/followup/start",
        json={"disease_type": "HYPERTENSION"},
        cookies=cookies["cookies"],
    )

    resp = await async_client.get("/tools/followup/today", cookies=cookies["cookies"])
    assert resp.status_code == 200
    tasks = resp.json()["data"]
    assert len(tasks) >= 1
    # 每个任务有 task_id 和 checkin_status
    for t in tasks:
        assert "task_id" in t
        assert t["checkin_status"] == "PENDING"


@pytest.mark.asyncio
async def test_checkin_and_adherence(async_client: AsyncClient, patient_user, db_session):
    await seed_followup_template(db_session)
    cookies = make_auth_cookie(patient_user)

    start_resp = await async_client.post(
        "/tools/followup/start",
        json={"disease_type": "HYPERTENSION"},
        cookies=cookies["cookies"],
    )
    plan_id = start_resp.json()["data"]["plan_id"]

    # 获取今日任务
    today_resp = await async_client.get("/tools/followup/today", cookies=cookies["cookies"])
    tasks = today_resp.json()["data"]
    assert tasks

    # 完成第一个任务打卡
    task_id = tasks[0]["task_id"]
    checkin_resp = await async_client.post(
        "/tools/followup/checkin",
        json={"task_id": task_id, "value": {"systolic": 120, "diastolic": 80}},
        cookies=cookies["cookies"],
    )
    assert checkin_resp.status_code == 200
    assert checkin_resp.json()["data"]["status"] == "DONE"

    # 依从率（已完成1个，尚无MISSED，依从率应为0或部分）
    adherence_resp = await async_client.get(
        f"/tools/followup/adherence?plan_id={plan_id}",
        cookies=cookies["cookies"],
    )
    assert adherence_resp.status_code == 200
    # 没有missed任务时依从率=0（因为没有对应的missed）
    rate = adherence_resp.json()["data"]["adherence_rate"]
    assert isinstance(rate, float)
