"""中医指导 / 干预 / 宣教 数据模型。"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import GuidanceStatus, GuidanceType, TemplateScope


class GuidanceTemplate(Base):
    """指导/干预/宣教 模板库（公开/科室/个人三级）。"""
    __tablename__ = "guidance_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    guidance_type: Mapped[GuidanceType] = mapped_column(
        Enum(GuidanceType, name="guidancetype"), nullable=False, index=True
    )
    scope: Mapped[TemplateScope] = mapped_column(
        Enum(TemplateScope, name="templatescope"),
        nullable=False,
        default=TemplateScope.PERSONAL,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 逗号分隔
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    records: Mapped[list["GuidanceRecord"]] = relationship(back_populates="template")


class GuidanceRecord(Base):
    """已下达的指导/干预/宣教 记录（一条=对一位患者下达一次）。"""
    __tablename__ = "guidance_records"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    guidance_type: Mapped[GuidanceType] = mapped_column(
        Enum(GuidanceType, name="guidancetype"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[GuidanceStatus] = mapped_column(
        Enum(GuidanceStatus, name="guidancestatus"),
        nullable=False,
        default=GuidanceStatus.PUBLISHED,
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("guidance_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    template: Mapped["GuidanceTemplate | None"] = relationship(back_populates="records")
