"""
中医干预模块 ORM 模型
包含：干预方案主表（Intervention）、干预执行记录（InterventionRecord）
"""
import uuid
from datetime import date, datetime
from enum import Enum

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ── 枚举定义 ─────────────────────────────────────────────────────────

class InterventionType(str, Enum):
    ACUPUNCTURE = "ACUPUNCTURE"   # 针灸
    MASSAGE     = "MASSAGE"       # 推拿
    HERBAL      = "HERBAL"        # 中药
    DIET        = "DIET"          # 食疗
    EXERCISE    = "EXERCISE"      # 运动疗法
    BATH        = "BATH"          # 药浴/熏蒸
    COMBINED    = "COMBINED"      # 综合干预


class InterventionStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED   = "COMPLETED"
    PAUSED      = "PAUSED"


class InterventionEffectiveness(str, Enum):
    EFFECTIVE    = "EFFECTIVE"      # 有效
    PARTIAL      = "PARTIAL"        # 部分有效
    INEFFECTIVE  = "INEFFECTIVE"    # 无效
    NOT_ASSESSED = "NOT_ASSESSED"   # 未评估


# ── ORM 模型 ──────────────────────────────────────────────────────────

class Intervention(Base):
    """干预方案主表"""
    __tablename__ = "interventions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 关联患者档案（patient_archives 主键为 UUID）
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("patient_archives.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    plan_name: Mapped[str] = mapped_column(String(200), nullable=False)
    intervention_type: Mapped[str] = mapped_column(String(50), nullable=False)   # InterventionType
    target_constitution: Mapped[str | None] = mapped_column(String(50), nullable=True)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_detail: Mapped[str | None] = mapped_column(Text, nullable=True)      # 穴位/用药/动作
    precaution: Mapped[str | None] = mapped_column(Text, nullable=True)           # 注意事项

    # 执行医师（users 主键为 UUID）
    executor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    duration_weeks: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    frequency: Mapped[str] = mapped_column(String(50), nullable=False, default="WEEKLY")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="IN_PROGRESS")

    # 创建人
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # 关系
    records: Mapped[list["InterventionRecord"]] = relationship(
        back_populates="intervention", cascade="all, delete-orphan"
    )


class InterventionRecord(Base):
    """干预执行记录（每次执行）"""
    __tablename__ = "intervention_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intervention_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("interventions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    session_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)   # 第几次
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    effectiveness: Mapped[str] = mapped_column(
        String(50), nullable=False, default="NOT_ASSESSED"
    )
    patient_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 记录人
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 关系
    intervention: Mapped["Intervention"] = relationship(back_populates="records")
