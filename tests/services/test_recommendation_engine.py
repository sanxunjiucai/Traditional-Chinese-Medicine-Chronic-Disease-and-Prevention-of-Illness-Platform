"""
调护建议引擎单测。
"""
import pytest
from sqlalchemy import select

from app.models.enums import BodyType, DiseaseType, PlanStatus, RecommendationCategory
from app.models.recommendation import RecommendationPlan, RecommendationTemplate
from app.services.recommendation_engine import generate_plan


@pytest.mark.asyncio
async def test_generate_plan_matches_body_type(db_session, patient_user):
    """按体质匹配模板，生成 ACTIVE 方案。"""
    # 插入模板
    for cat in RecommendationCategory:
        t = RecommendationTemplate(
            body_type=BodyType.QI_DEFICIENCY,
            disease_type=None,
            category=cat,
            title=f"气虚-{cat.value}",
            content=f"气虚调护内容 {cat.value}",
            priority=0,
            is_active=True,
        )
        db_session.add(t)
    await db_session.flush()

    plan = await generate_plan(
        db=db_session,
        user_id=patient_user.id,
        main_type=BodyType.QI_DEFICIENCY,
    )
    assert plan.status == PlanStatus.ACTIVE
    assert len(plan.items) == len(list(RecommendationCategory))
    assert all(item["category"] for item in plan.items)


@pytest.mark.asyncio
async def test_old_plan_archived_on_new_generation(db_session, patient_user):
    """生成新方案时，旧的 ACTIVE 方案应变为 REVISED。"""
    # 插入至少一条模板
    t = RecommendationTemplate(
        body_type=BodyType.YIN_DEFICIENCY,
        disease_type=None,
        category=RecommendationCategory.DIET,
        title="阴虚-饮食",
        content="滋阴饮食建议",
        priority=0,
        is_active=True,
    )
    db_session.add(t)
    await db_session.flush()

    # 第一次生成
    plan1 = await generate_plan(db_session, patient_user.id, BodyType.YIN_DEFICIENCY)
    assert plan1.status == PlanStatus.ACTIVE
    assert plan1.version == 1

    # 第二次生成
    plan2 = await generate_plan(db_session, patient_user.id, BodyType.YIN_DEFICIENCY)

    # plan1 应被 REVISED
    await db_session.refresh(plan1)
    assert plan1.status == PlanStatus.REVISED
    assert plan2.status == PlanStatus.ACTIVE
    assert plan2.version == 2
