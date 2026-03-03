import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy import JSON
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import BodyType, DiseaseType, PlanStatus, RecommendationCategory


class RecommendationTemplate(Base):
    __tablename__ = "recommendation_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    body_type: Mapped[BodyType] = mapped_column(
        Enum(BodyType, name="bodytype"), nullable=False, index=True
    )
    disease_type: Mapped[DiseaseType | None] = mapped_column(
        Enum(DiseaseType, name="diseasetype"), nullable=True, index=True
    )
    category: Mapped[RecommendationCategory] = mapped_column(
        Enum(RecommendationCategory, name="recommendationcategory"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RecommendationPlan(Base):
    __tablename__ = "recommendation_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("constitution_assessments.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[PlanStatus] = mapped_column(
        Enum(PlanStatus, name="planstatus"), nullable=False, default=PlanStatus.ACTIVE
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # [{category, title, content, priority}]
    items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
