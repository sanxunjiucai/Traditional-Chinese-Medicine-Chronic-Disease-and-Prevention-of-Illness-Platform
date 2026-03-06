"""
档案标签管理模型
包括：标签分类、标签、患者-标签关联
"""
import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LabelScope(str, PyEnum):
    SYSTEM = "SYSTEM"   # 系统预设（不可删除）
    CUSTOM = "CUSTOM"   # 自定义


class LabelCategory(Base):
    """标签分类"""
    __tablename__ = "label_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#6b7280")   # hex 颜色
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    labels: Mapped[list["Label"]] = relationship(back_populates="category", cascade="all, delete-orphan")


class Label(Base):
    """标签"""
    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("label_categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="CUSTOM")
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#6b7280")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    category: Mapped["LabelCategory | None"] = relationship(back_populates="labels")
    patient_labels: Mapped[list["PatientLabel"]] = relationship(back_populates="label", cascade="all, delete-orphan")


class PatientLabel(Base):
    """患者标签关联"""
    __tablename__ = "patient_labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("patient_archives.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    label_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("labels.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)   # 打标注释
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    label: Mapped["Label"] = relationship(back_populates="patient_labels")
