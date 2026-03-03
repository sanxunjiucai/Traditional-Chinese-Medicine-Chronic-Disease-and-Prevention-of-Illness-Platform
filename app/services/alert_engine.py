import uuid
from typing import Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import AlertEvent, AlertRule
from app.models.enums import AlertStatus, IndicatorType
from app.models.health import HealthIndicator


def _evaluate_condition(value: dict, condition: dict) -> bool:
    """
    评估单条规则条件。
    condition: {"field": "systolic", "op": ">", "value": 180}
    """
    field = condition.get("field")
    op = condition.get("op")
    threshold = condition.get("value")

    actual = value.get(field)
    if actual is None:
        return False

    try:
        actual = float(actual)
        threshold = float(threshold)
    except (TypeError, ValueError):
        return False

    if op == ">":
        return actual > threshold
    elif op == ">=":
        return actual >= threshold
    elif op == "<":
        return actual < threshold
    elif op == "<=":
        return actual <= threshold
    elif op == "==":
        return actual == threshold
    elif op == "!=":
        return actual != threshold
    return False


def _all_conditions_met(indicator_values: dict, conditions: list[dict]) -> bool:
    return all(_evaluate_condition(indicator_values, cond) for cond in conditions)


async def check_indicator(
    db: AsyncSession,
    user_id: uuid.UUID,
    indicator: HealthIndicator,
) -> list[AlertEvent]:
    """
    检测新录入的指标是否触发预警规则。
    同一规则对同一用户已有 OPEN 事件时不重复创建。
    """
    # 加载该指标类型的激活规则
    rules_result = await db.execute(
        select(AlertRule).where(
            and_(
                AlertRule.is_active == True,  # noqa: E712
                AlertRule.indicator_type == indicator.indicator_type,
            )
        )
    )
    rules: Sequence[AlertRule] = rules_result.scalars().all()

    created_events: list[AlertEvent] = []

    for rule in rules:
        if not _all_conditions_met(indicator.values, rule.conditions):
            continue

        # 检查是否已有 OPEN 事件（防重复）
        existing_result = await db.execute(
            select(AlertEvent).where(
                and_(
                    AlertEvent.user_id == user_id,
                    AlertEvent.rule_id == rule.id,
                    AlertEvent.status == AlertStatus.OPEN,
                )
            ).limit(1)
        )
        if existing_result.scalar_one_or_none() is not None:
            continue

        # 渲染消息
        message = rule.message_template.format(
            **{k: v for k, v in indicator.values.items() if isinstance(v, (int, float, str))}
        )

        event = AlertEvent(
            user_id=user_id,
            rule_id=rule.id,
            indicator_id=indicator.id,
            severity=rule.severity,
            status=AlertStatus.OPEN,
            trigger_value=indicator.values,
            message=message,
        )
        db.add(event)
        created_events.append(event)

    if created_events:
        await db.flush()

    return created_events
