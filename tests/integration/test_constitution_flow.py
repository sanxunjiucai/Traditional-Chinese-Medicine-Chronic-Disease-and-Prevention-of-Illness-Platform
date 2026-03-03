"""
体质问卷 → 评分 → 调护建议方案 集成测试。
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import BodyType, RecommendationCategory
from app.models.constitution import ConstitutionQuestion
from app.models.recommendation import RecommendationTemplate
from app.models.enums import AssessmentStatus
from tests.conftest import make_auth_cookie


async def seed_questions(db: AsyncSession):
    """插入简化版9体质问卷（每体质2题，共18题）。"""
    seq = 0
    for bt in BodyType:
        for i in range(2):
            q = ConstitutionQuestion(
                code=f"{bt.value}_{i+1:02d}",
                body_type=bt,
                seq=i + 1,
                content=f"[测试]{bt.value} 第{i+1}题",
                options=[
                    {"value": 1, "label": "没有"},
                    {"value": 2, "label": "很少"},
                    {"value": 3, "label": "有时"},
                    {"value": 4, "label": "经常"},
                    {"value": 5, "label": "总是"},
                ],
                is_reverse=False,
            )
            db.add(q)
    await db.flush()


async def seed_templates(db: AsyncSession):
    """插入调护建议模板（气虚质）。"""
    for cat in list(RecommendationCategory)[:2]:
        t = RecommendationTemplate(
            body_type=BodyType.QI_DEFICIENCY,
            category=cat,
            title=f"气虚-{cat.value}",
            content="测试内容",
            is_active=True,
        )
        db.add(t)
    await db.flush()


@pytest.mark.asyncio
async def test_constitution_full_flow(async_client: AsyncClient, patient_user, db_session):
    await seed_questions(db_session)
    await seed_templates(db_session)

    cookies = make_auth_cookie(patient_user)

    # 1. 开始评估
    resp = await async_client.post("/tools/constitution/start", cookies=cookies["cookies"])
    assert resp.status_code == 201
    assessment_id = resp.json()["data"]["assessment_id"]

    # 2. 获取题目列表
    resp = await async_client.get("/tools/constitution/questions", cookies=cookies["cookies"])
    assert resp.status_code == 200
    questions = resp.json()["data"]
    assert len(questions) > 0

    # 3. 提交答案（气虚质全答5，其余全答1）
    answers = []
    for q in questions:
        value = 5 if q["body_type"] == "QI_DEFICIENCY" else 1
        answers.append({"question_id": q["id"], "answer_value": value})

    resp = await async_client.post(
        "/tools/constitution/answer",
        json={"assessment_id": assessment_id, "answers": answers},
        cookies=cookies["cookies"],
    )
    assert resp.status_code == 200

    # 4. 提交评分
    resp = await async_client.post(
        "/tools/constitution/submit",
        json={"assessment_id": assessment_id},
        cookies=cookies["cookies"],
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["main_type"] == "QI_DEFICIENCY"
    assert "recommendation_plan_id" in data

    # 5. 验证最新评估
    resp = await async_client.get("/tools/constitution/latest", cookies=cookies["cookies"])
    assert resp.status_code == 200
    latest = resp.json()["data"]
    assert latest is not None
    assert latest["main_type"] == "QI_DEFICIENCY"


@pytest.mark.asyncio
async def test_cannot_submit_twice(async_client: AsyncClient, patient_user, db_session):
    await seed_questions(db_session)

    cookies = make_auth_cookie(patient_user)
    resp = await async_client.post("/tools/constitution/start", cookies=cookies["cookies"])
    assessment_id = resp.json()["data"]["assessment_id"]

    questions_resp = await async_client.get("/tools/constitution/questions", cookies=cookies["cookies"])
    questions = questions_resp.json()["data"]
    answers = [{"question_id": q["id"], "answer_value": 3} for q in questions]

    await async_client.post(
        "/tools/constitution/answer",
        json={"assessment_id": assessment_id, "answers": answers},
        cookies=cookies["cookies"],
    )
    await async_client.post(
        "/tools/constitution/submit",
        json={"assessment_id": assessment_id},
        cookies=cookies["cookies"],
    )

    # 第二次提交应返回 STATE_ERROR
    resp = await async_client.post(
        "/tools/constitution/submit",
        json={"assessment_id": assessment_id},
        cookies=cookies["cookies"],
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "STATE_ERROR"
