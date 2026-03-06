"""
患者通知模型 - 系统向患者推送的各类消息
notif_type: RISK_ALERT / PLAN_ISSUED / FOLLOWUP_REMINDER / CONSULTATION_REPLY
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 接收方：患者档案
    archive_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("patient_archives.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    # 发送方：医生（系统自动发送时为 NULL）
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 通知类型
    notif_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="SYSTEM",
        # RISK_ALERT / PLAN_ISSUED / FOLLOWUP_REMINDER / CONSULTATION_REPLY / SYSTEM
    )

    # 状态
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNREAD"
        # UNREAD / READ
    )

    # 点击后跳转的 H5 URL
    action_url: Mapped[str | None] = mapped_column(String(300), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
