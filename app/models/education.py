"""
中医宣教模型：EducationRecord（宣教发送记录）、EducationDelivery（投递记录）、
EducationTemplate（宣教模板）。
"""
import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ════════════════════════════════════
# 枚举
# ════════════════════════════════════

class EducationType(str, Enum):
    CONSTITUTION = "CONSTITUTION"   # 体质宣教
    DISEASE = "DISEASE"             # 疾病知识
    DIET = "DIET"                   # 饮食指导
    EXERCISE = "EXERCISE"           # 运动健康
    SEASONAL = "SEASONAL"           # 节气养生
    MEDICATION = "MEDICATION"       # 用药指导
    GENERAL = "GENERAL"             # 一般健康知识


class SendMethod(str, Enum):
    APP = "APP"
    STATION = "STATION"    # 站内消息
    SMS = "SMS"
    WECHAT = "WECHAT"


class SendScope(str, Enum):
    SINGLE = "SINGLE"      # 单个患者
    BATCH = "BATCH"        # 批量


class ReadStatus(str, Enum):
    UNREAD = "UNREAD"
    READ = "READ"


# ════════════════════════════════════
# ORM 模型
# ════════════════════════════════════

class EducationRecord(Base):
    """宣教发送记录（一次宣教活动对应一条记录，可覆盖多个患者）。"""
    __tablename__ = "education_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    edu_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    send_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="SINGLE")
    # JSON 序列化的发送方式列表，如 '["APP","STATION"]'
    send_methods: Mapped[str | None] = mapped_column(String(200), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    deliveries: Mapped[list["EducationDelivery"]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )


class EducationDelivery(Base):
    """宣教投递记录（每个患者一条，记录阅读状态）。"""
    __tablename__ = "education_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("education_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 关联患者档案（patient_archives 的 UUID 主键）
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("patient_archives.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    send_method: Mapped[str] = mapped_column(String(50), nullable=False)
    read_status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNREAD")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    record: Mapped["EducationRecord"] = relationship(back_populates="deliveries")


class EducationTemplate(Base):
    """宣教模板（PUBLIC / DEPT / PERSONAL 三级复用）。"""
    __tablename__ = "education_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    edu_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # PUBLIC=公开  DEPT=科室  PERSONAL=个人
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="PERSONAL")
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
