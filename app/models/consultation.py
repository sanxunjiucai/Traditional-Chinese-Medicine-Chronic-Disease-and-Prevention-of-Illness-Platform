"""
在线咨询模型
Consultation: 咨询工单主表（患者发起，医生接诊）
ConsultationMessage: 咨询消息（支持医患双向对话）
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Consultation(Base):
    __tablename__ = "consultations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 患者档案
    archive_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("patient_archives.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    # 接诊医生（患者发起时为 NULL，医生接单后填入）
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    # 状态：OPEN / REPLIED / CLOSED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")

    # 优先级：NORMAL / URGENT
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="NORMAL")

    # 关联消息
    messages: Mapped[list["ConsultationMessage"]] = relationship(
        "ConsultationMessage",
        back_populates="consultation",
        cascade="all, delete-orphan",
        order_by="ConsultationMessage.created_at",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConsultationMessage(Base):
    __tablename__ = "consultation_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    consultation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("consultations.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    # 发送人（医生用 users.id，患者用 archive_id 映射，统一存 UUID）
    sender_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)

    # DOCTOR / PATIENT
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)

    # TEXT / IMAGE / ATTACHMENT
    msg_type: Mapped[str] = mapped_column(String(20), nullable=False, default="TEXT")

    consultation: Mapped["Consultation"] = relationship(
        "Consultation", back_populates="messages"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
