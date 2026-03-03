import uuid
from typing import Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import BodyType, DiseaseType, PlanStatus
from app.models.recommendation import RecommendationPlan, RecommendationTemplate


async def generate_plan(
    db: AsyncSession,
    user_id: uuid.UUID,
    main_type: BodyType,
    disease_types: list[DiseaseType] | None = None,
    assessment_id: uuid.UUID | None = None,
) -> RecommendationPlan:
    """
    按体质+病种从模板库匹配调护建议，生成新的 RecommendationPlan。
    如存在 ACTIVE 方案，先将其状态改为 REVISED。
    """
    # 归档旧的 ACTIVE 方案
    old_plans_result = await db.execute(
        select(RecommendationPlan).where(
            and_(
                RecommendationPlan.user_id == user_id,
                RecommendationPlan.status == PlanStatus.ACTIVE,
            )
        )
    )
    old_plans = old_plans_result.scalars().all()
    max_version = 0
    for old_plan in old_plans:
        old_plan.status = PlanStatus.REVISED
        max_version = max(max_version, old_plan.version)
        db.add(old_plan)

    # 查询模板（按体质匹配，兼顾病种）
    conditions = [RecommendationTemplate.body_type == main_type]
    if disease_types:
        dt_filter = or_(
            RecommendationTemplate.disease_type.in_(disease_types),
            RecommendationTemplate.disease_type.is_(None),
        )
        conditions.append(dt_filter)
    else:
        conditions.append(
            or_(
                RecommendationTemplate.disease_type.is_(None),
            )
        )

    templates_result = await db.execute(
        select(RecommendationTemplate)
        .where(and_(*conditions, RecommendationTemplate.is_active == True))  # noqa: E712
        .order_by(RecommendationTemplate.category, RecommendationTemplate.priority.desc())
    )
    templates: Sequence[RecommendationTemplate] = templates_result.scalars().all()

    items = [
        {
            "category": t.category.value,
            "title": t.title,
            "content": t.content,
            "priority": t.priority,
        }
        for t in templates
    ]

    new_plan = RecommendationPlan(
        user_id=user_id,
        assessment_id=assessment_id,
        status=PlanStatus.ACTIVE,
        version=max_version + 1,
        items=items,
    )
    db.add(new_plan)
    await db.flush()
    return new_plan
