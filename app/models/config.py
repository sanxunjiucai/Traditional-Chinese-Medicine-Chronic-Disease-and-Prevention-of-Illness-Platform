"""系统配置 / 定时任务 数据模型。"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, Text, func
from sqlalchemy import Uuid, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import ScheduledTaskStatus


class SystemConfig(Base):
    """动态参数配置（键值对）。"""
    __tablename__ = "system_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    group: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否对前端暴露
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ScheduledTask(Base):
    """定时任务配置与执行记录。"""
    __tablename__ = "scheduled_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    task_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cron_expr: Mapped[str | None] = mapped_column(String(100), nullable=True)  # cron表达式
    status: Mapped[ScheduledTaskStatus] = mapped_column(
        Enum(ScheduledTaskStatus, name="scheduledtaskstatus"),
        nullable=False,
        default=ScheduledTaskStatus.ACTIVE,
    )
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)       # 动态参数
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_result: Mapped[str | None] = mapped_column(Text, nullable=True)   # 最近执行结果
    run_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
