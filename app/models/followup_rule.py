"""
随访规则模型
- FollowupRule: 随访规则定义（触发条件 + 频率 + 方式）
"""
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FollowupTrigger(str, Enum):
    NEW_ARCHIVE = "NEW_ARCHIVE"              # 新建档案时触发
    DISEASE_ADDED = "DISEASE_ADDED"          # 新增疾病诊断时触发
    ALERT_TRIGGERED = "ALERT_TRIGGERED"      # 预警触发时
    ASSESS_COMPLETED = "ASSESS_COMPLETED"    # 评估完成时
    MANUAL = "MANUAL"                        # 手动触发


class FollowupFrequency(str, Enum):
    DAILY = "DAILY"            # 每日
    TWICE_WEEK = "TWICE_WEEK"  # 每周两次
    WEEKLY = "WEEKLY"          # 每周一次
    BIWEEKLY = "BIWEEKLY"      # 每两周一次
    MONTHLY = "MONTHLY"        # 每月一次
    QUARTERLY = "QUARTERLY"    # 每季度一次
    ONCE = "ONCE"              # 仅一次


class FollowupRule(Base):
    """随访规则"""
    __tablename__ = "followup_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 触发条件：NEW_ARCHIVE / DISEASE_ADDED / ALERT_TRIGGERED / ASSESS_COMPLETED / MANUAL
    trigger: Mapped[str] = mapped_column(String(50), nullable=False)
    # 随访频率
    frequency: Mapped[str] = mapped_column(String(50), nullable=False)
    # 随访方式：PHONE（电话）/ ONLINE（网络）/ APP（App 推送）/ VISIT（上门）
    method: Mapped[str] = mapped_column(String(50), nullable=False)
    # 档案类型过滤：对应 ArchiveType 枚举值，为空则不限
    archive_type_filter: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
