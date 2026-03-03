import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy import JSON
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import DiseaseType, IndicatorType


class HealthProfile(Base):
    __tablename__ = "health_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True
    )
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)  # male/female/other
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    waist_cm: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 既往史/家族史/过敏史（JSON列表）
    past_history: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    family_history: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    allergy_history: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 生活方式
    smoking: Mapped[str | None] = mapped_column(String(20), nullable=True)  # never/former/current
    drinking: Mapped[str | None] = mapped_column(String(20), nullable=True)
    exercise_frequency: Mapped[str | None] = mapped_column(String(20), nullable=True)  # never/occasional/regular
    sleep_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    stress_level: Mapped[str | None] = mapped_column(String(20), nullable=True)  # low/medium/high

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ChronicDiseaseRecord(Base):
    __tablename__ = "chronic_disease_records"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    disease_type: Mapped[DiseaseType] = mapped_column(
        Enum(DiseaseType, name="diseasetype"), nullable=False
    )
    diagnosed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    diagnosed_hospital: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # 用药记录（JSON列表）：[{name, dose, frequency, start_date, end_date}]
    medications: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # 并发症
    complications: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # 目标值：{systolic_target: 130, diastolic_target: 80} 或 {hba1c_target: 7.0}
    target_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class HealthIndicator(Base):
    __tablename__ = "health_indicators"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    indicator_type: Mapped[IndicatorType] = mapped_column(
        Enum(IndicatorType, name="indicatortype"), nullable=False, index=True
    )
    # BLOOD_PRESSURE: {systolic: 120, diastolic: 80}
    # BLOOD_GLUCOSE:  {scene: "fasting"|"postmeal_1h"|"postmeal_2h", value: 5.6}
    # WEIGHT:         {value: 65.5}
    # WAIST_CIRCUMFERENCE: {value: 85.0}
    values: Mapped[dict] = mapped_column(JSON, nullable=False)

    scene: Mapped[str | None] = mapped_column(String(50), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
