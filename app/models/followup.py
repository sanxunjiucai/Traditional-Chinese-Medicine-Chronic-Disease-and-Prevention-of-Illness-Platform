import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy import JSON
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import CheckInStatus, DiseaseType, FollowupStatus, TaskType


class FollowupTemplate(Base):
    __tablename__ = "followup_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    disease_type: Mapped[DiseaseType] = mapped_column(
        Enum(DiseaseType, name="diseasetype"), nullable=False, index=True
    )
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # [{task_type, name, required, every_day: true/false, days: [1,2,...]}]
    tasks: Mapped[list] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FollowupPlan(Base):
    __tablename__ = "followup_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("followup_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    disease_type: Mapped[DiseaseType] = mapped_column(
        Enum(DiseaseType, name="diseasetype"), nullable=False
    )
    status: Mapped[FollowupStatus] = mapped_column(
        Enum(FollowupStatus, name="followupstatus"),
        nullable=False,
        default=FollowupStatus.CREATED,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    tasks: Mapped[list["FollowupTask"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    template: Mapped["FollowupTemplate | None"] = relationship()


class FollowupTask(Base):
    __tablename__ = "followup_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("followup_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_type: Mapped[TaskType] = mapped_column(
        Enum(TaskType, name="tasktype"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    # 任务元数据：{indicator_type: "BLOOD_PRESSURE"} 等
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    plan: Mapped["FollowupPlan"] = relationship(back_populates="tasks")
    checkins: Mapped[list["CheckIn"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class CheckIn(Base):
    __tablename__ = "checkins"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("followup_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[CheckInStatus] = mapped_column(
        Enum(CheckInStatus, name="checkinstatus"),
        nullable=False,
        default=CheckInStatus.PENDING,
    )
    # 打卡数据：{value: 120} 或 {systolic: 120, diastolic: 80} 或 {done: true}
    value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    task: Mapped["FollowupTask"] = relationship(back_populates="checkins")
