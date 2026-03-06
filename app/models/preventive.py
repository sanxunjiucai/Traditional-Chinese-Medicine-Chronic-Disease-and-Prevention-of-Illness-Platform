"""
治未病·预防保健方案 数据模型

核心实体：
  LifestyleProfile      — 生活方式档案（对话/问卷提取）
  TcmTraitAssessment    — 中医特征评估（AI 生成，区别于问卷式 ConstitutionAssessment）
  RiskInference         — 未来风险推断（AI 生成）
  PreventivePlan        — 预防保健方案（含四件套 + 套餐 + 经济选项）
  PlanDistribution      — 方案分发记录（多渠道）
  PatientIntent         — 患者意向/预约
  PreventiveFollowUpTask— 治未病专属随访任务
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey, Integer,
    String, Text, func, JSON
)
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import (
    DistributionChannel, DistributionStatus,
    IntentStatus, IntentType,
    LifestyleSource,
    PreventivePlanStatus,
    PreventiveTaskStatus, PreventiveTaskType,
)


class LifestyleProfile(Base):
    """生活方式档案：从对话/问卷/HIS 提取的结构化生活方式条目。"""
    __tablename__ = "lifestyle_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    encounter_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    source: Mapped[LifestyleSource] = mapped_column(
        Enum(LifestyleSource, name="lifestylesource"),
        nullable=False, default=LifestyleSource.MANUAL
    )
    # [{key, label, value, unit?, confidence, evidence}]
    items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    raw_dialogue: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TcmTraitAssessment(Base):
    """中医特征评估：AI 从生活方式 + 症状推断中医证候（非问卷）。"""
    __tablename__ = "tcm_trait_assessments"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    lifestyle_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("lifestyle_profiles.id", ondelete="SET NULL"),
        nullable=True
    )
    encounter_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 主要证候
    primary_trait: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # [{trait, level, evidence_items, score}]
    traits: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    secondary_traits: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    dialogue_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    symptom_items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    lifestyle_profile: Mapped["LifestyleProfile | None"] = relationship()


class RiskInference(Base):
    """未来风险推断：AI 综合生活方式、体质、慢病史推断未来健康风险。"""
    __tablename__ = "risk_inferences"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    lifestyle_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("lifestyle_profiles.id", ondelete="SET NULL"),
        nullable=True
    )
    encounter_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # [{category, probability, severity, timeframe, rationale}]
    risks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    rationale_chain: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    vitals_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    lifestyle_profile: Mapped["LifestyleProfile | None"] = relationship()


class PreventivePlan(Base):
    """预防保健方案：整合四件套 + 套餐选择 + 经济方案 + 分发记录。"""
    __tablename__ = "preventive_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    encounter_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    status: Mapped[PreventivePlanStatus] = mapped_column(
        Enum(PreventivePlanStatus, name="preventiveplanstatus"),
        nullable=False, default=PreventivePlanStatus.DRAFT
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # 方案摘要引用（四件套 ID）
    # {lifestyle_profile_id, tcm_assessment_id, risk_inference_id}
    summary_blocks: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # 套餐选择 [{template_id, name, overrides...}]
    selected_packages: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # 单项选择 [{intervention_item_id, name, count, unit, price_override}]
    selected_items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # 经济方案 [{tier, duration_weeks, visits, price_range, rationale}]
    economic_options: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    doctor_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    patient_readable_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    distributions: Mapped[list["PlanDistribution"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    intents: Mapped[list["PatientIntent"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    followup_tasks: Mapped[list["PreventiveFollowUpTask"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class PlanDistribution(Base):
    """方案分发记录：记录向各渠道推送的状态。"""
    __tablename__ = "plan_distributions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("preventive_plans.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    channel: Mapped[DistributionChannel] = mapped_column(
        Enum(DistributionChannel, name="distributionchannel"), nullable=False
    )
    status: Mapped[DistributionStatus] = mapped_column(
        Enum(DistributionStatus, name="distributionstatus"),
        nullable=False, default=DistributionStatus.PENDING
    )
    payload_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    plan: Mapped["PreventivePlan"] = relationship(back_populates="distributions")


class PatientIntent(Base):
    """患者意向/预约：记录患者对方案的响应意向。"""
    __tablename__ = "patient_intents"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("preventive_plans.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    type: Mapped[IntentType] = mapped_column(
        Enum(IntentType, name="intenttype"), nullable=False
    )
    status: Mapped[IntentStatus] = mapped_column(
        Enum(IntentStatus, name="intentstatus"),
        nullable=False, default=IntentStatus.PENDING
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    plan: Mapped["PreventivePlan | None"] = relationship(back_populates="intents")


class PreventiveFollowUpTask(Base):
    """治未病专属随访任务（与常规随访任务分离）。"""
    __tablename__ = "preventive_followup_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("preventive_plans.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    task_type: Mapped[PreventiveTaskType] = mapped_column(
        Enum(PreventiveTaskType, name="preventivetasktype"), nullable=False
    )
    status: Mapped[PreventiveTaskStatus] = mapped_column(
        Enum(PreventiveTaskStatus, name="preventivetaskstatus"),
        nullable=False, default=PreventiveTaskStatus.TODO
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 患者反馈或医生备注
    result_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    plan: Mapped["PreventivePlan"] = relationship(back_populates="followup_tasks")
