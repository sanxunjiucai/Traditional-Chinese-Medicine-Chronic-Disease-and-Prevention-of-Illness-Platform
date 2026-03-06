"""
量表管理模型
- Scale: 量表定义
- ScaleQuestion: 量表题目
- ScaleRecord: 量表作答记录
"""
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ScaleType(str, Enum):
    CONSTITUTION = "CONSTITUTION"    # 体质辨识
    MENTAL_HEALTH = "MENTAL_HEALTH"  # 心理健康
    FUNCTION = "FUNCTION"            # 功能评估
    DISEASE = "DISEASE"              # 疾病专项
    COMPOSITE = "COMPOSITE"          # 组合量表
    CUSTOM = "CUSTOM"                # 自定义


class QuestionType(str, Enum):
    SINGLE = "SINGLE"            # 单选
    MULTIPLE = "MULTIPLE"        # 多选
    SCALE_SCORE = "SCALE_SCORE"  # 评分尺
    TEXT = "TEXT"                # 文本


class Scale(Base):
    """量表定义"""
    __tablename__ = "scales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scale_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # JSON 计分规则，如 {"method": "sum"} 或 {"method": "weighted", "weights": {...}}
    scoring_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON 分层规则，如 [{"min": 0, "max": 4, "level": "正常", "label": "无抑郁"}]
    level_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ScaleQuestion(Base):
    """量表题目"""
    __tablename__ = "scale_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scale_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scales.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_no: Mapped[int] = mapped_column(Integer, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(50), nullable=False, default="SINGLE")
    # JSON: [{"text": "没有", "score": 0}, {"text": "偶尔", "score": 1}, ...]
    options: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 所属维度/因子，用于多维度量表，如 PHQ-9 各条目均属单一维度
    dimension: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ScaleRecord(Base):
    """量表作答记录。

    status 推导规则（无独立字段，通过 property 暴露）：
      - DRAFT:     completed_at 为空（作答中）
      - SUBMITTED: completed_at 非空 且 conclusion 为空（已提交未报告）
      - REPORTED:  completed_at 非空 且 conclusion 非空（已出报告）
    """
    __tablename__ = "scale_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scale_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scales.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 使用整数外键，因为 patient_archives.id 在项目中实际为 UUID；
    # 为兼容演示模式，此处存储为字符串型外键（patient_archive_id 字段）
    patient_archive_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # JSON: {"q1": 2, "q2": 1, ...} 或 [{"question_id": 1, "value": 2}, ...]
    answers: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    level: Mapped[str | None] = mapped_column(String(50), nullable=True)    # 分层结果，如"轻度抑郁"
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)     # 结论/建议文字
    recorded_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @property
    def status(self) -> str:
        """从 completed_at / conclusion 推导状态，统一在模型层处理。"""
        if self.completed_at is None:
            return "DRAFT"
        if not self.conclusion:
            return "SUBMITTED"
        return "REPORTED"
