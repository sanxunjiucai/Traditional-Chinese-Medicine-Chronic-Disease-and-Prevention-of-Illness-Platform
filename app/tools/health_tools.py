from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import DiseaseType, IndicatorType
from app.models.health import ChronicDiseaseRecord, HealthIndicator, HealthProfile
from app.services.alert_engine import check_indicator
from app.services.audit_service import log_action
from app.tools.response import fail, ok

router = APIRouter(tags=["health-tools"])


# ── Health Profile ──

class ProfileRequest(BaseModel):
    gender: str | None = None
    birth_date: str | None = None  # YYYY-MM-DD
    height_cm: float | None = None
    weight_kg: float | None = None
    waist_cm: float | None = None
    smoking: str | None = None
    drinking: str | None = None
    exercise_frequency: str | None = None
    sleep_hours: float | None = None
    stress_level: str | None = None


@router.get("/profile")
async def get_profile(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    result = await db.execute(
        select(HealthProfile).where(HealthProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        return ok(None)
    return ok({
        "id": str(profile.id),
        "gender": profile.gender,
        "birth_date": str(profile.birth_date) if profile.birth_date else None,
        "height_cm": profile.height_cm,
        "weight_kg": profile.weight_kg,
        "waist_cm": profile.waist_cm,
        "smoking": profile.smoking,
        "drinking": profile.drinking,
        "exercise_frequency": profile.exercise_frequency,
        "sleep_hours": profile.sleep_hours,
        "stress_level": profile.stress_level,
        "updated_at": profile.updated_at.isoformat(),
    })


@router.post("/profile")
async def upsert_profile(
    body: ProfileRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    result = await db.execute(
        select(HealthProfile).where(HealthProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    old_values = None

    if profile is None:
        profile = HealthProfile(user_id=current_user.id)
        db.add(profile)
    else:
        old_values = {
            "height_cm": profile.height_cm,
            "weight_kg": profile.weight_kg,
        }

    for field, value in body.model_dump(exclude_none=True).items():
        if field == "birth_date" and value:
            from datetime import date
            profile.birth_date = date.fromisoformat(value)
        else:
            setattr(profile, field, value)

    await db.flush()
    await log_action(
        db, action="UPDATE_PROFILE", resource_type="HealthProfile",
        user_id=current_user.id, resource_id=str(profile.id),
        old_values=old_values,
        new_values=body.model_dump(exclude_none=True),
    )
    await db.commit()
    return ok({"profile_id": str(profile.id)})


# ── Disease Record ──

class DiseaseRequest(BaseModel):
    disease_type: DiseaseType
    diagnosed_at: str | None = None
    diagnosed_hospital: str | None = None
    medications: list | None = None
    target_values: dict | None = None
    notes: str | None = None


@router.post("/disease")
async def add_disease(
    body: DiseaseRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    from datetime import date
    record = ChronicDiseaseRecord(
        user_id=current_user.id,
        disease_type=body.disease_type,
        diagnosed_at=date.fromisoformat(body.diagnosed_at) if body.diagnosed_at else None,
        diagnosed_hospital=body.diagnosed_hospital,
        medications=body.medications,
        target_values=body.target_values,
        notes=body.notes,
    )
    db.add(record)
    await db.flush()
    await log_action(
        db, action="ADD_DISEASE", resource_type="ChronicDiseaseRecord",
        user_id=current_user.id, resource_id=str(record.id),
        new_values={"disease_type": body.disease_type.value},
    )
    await db.commit()
    return ok({"record_id": str(record.id)}, status_code=201)


@router.get("/disease")
async def list_diseases(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    result = await db.execute(
        select(ChronicDiseaseRecord).where(
            and_(ChronicDiseaseRecord.user_id == current_user.id,
                 ChronicDiseaseRecord.is_active == True)  # noqa: E712
        )
    )
    records = result.scalars().all()
    return ok([
        {
            "id": str(r.id),
            "disease_type": r.disease_type.value,
            "diagnosed_at": str(r.diagnosed_at) if r.diagnosed_at else None,
            "target_values": r.target_values,
            "medications": r.medications,
        }
        for r in records
    ])


# ── Health Indicators ──

class IndicatorRequest(BaseModel):
    indicator_type: IndicatorType
    values: dict
    scene: str | None = None
    note: str | None = None
    recorded_at: str | None = None  # ISO datetime; defaults to now


@router.post("/indicators")
async def add_indicator(
    body: IndicatorRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
):
    recorded_at = (
        datetime.fromisoformat(body.recorded_at)
        if body.recorded_at
        else datetime.now(timezone.utc)
    )
    indicator = HealthIndicator(
        user_id=current_user.id,
        indicator_type=body.indicator_type,
        values=body.values,
        scene=body.scene,
        note=body.note,
        recorded_at=recorded_at,
    )
    db.add(indicator)
    await db.flush()

    # 触发预警检测
    events = await check_indicator(db, current_user.id, indicator)

    await log_action(
        db, action="ADD_INDICATOR", resource_type="HealthIndicator",
        user_id=current_user.id, resource_id=str(indicator.id),
        new_values={"type": body.indicator_type.value, **body.values},
    )
    await db.commit()

    return ok({
        "indicator_id": str(indicator.id),
        "alerts_created": len(events),
    }, status_code=201)


@router.get("/indicators")
async def list_indicators(
    indicator_type: IndicatorType,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user=Depends(get_current_user),
    days: int = Query(default=30, ge=1, le=365),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(HealthIndicator)
        .where(
            and_(
                HealthIndicator.user_id == current_user.id,
                HealthIndicator.indicator_type == indicator_type,
                HealthIndicator.recorded_at >= since,
            )
        )
        .order_by(HealthIndicator.recorded_at.asc())
    )
    indicators = result.scalars().all()
    return ok([
        {
            "id": str(ind.id),
            "values": ind.values,
            "scene": ind.scene,
            "note": ind.note,
            "recorded_at": ind.recorded_at.isoformat(),
        }
        for ind in indicators
    ])
