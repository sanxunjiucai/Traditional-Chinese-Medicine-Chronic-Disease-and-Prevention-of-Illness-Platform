import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy import JSON
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import AssessmentStatus, BodyType


class ConstitutionQuestion(Base):
    __tablename__ = "constitution_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    body_type: Mapped[BodyType] = mapped_column(
        Enum(BodyType, name="bodytype"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # 在该体质题目中的序号
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # options: [{"value": 1, "label": "没有"}, ..., {"value": 5, "label": "总是"}]
    options: Mapped[list] = mapped_column(JSON, nullable=False)
    # 是否反向计分（平和质中部分题目需反向）
    is_reverse: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    answers: Mapped[list["ConstitutionAnswer"]] = relationship(back_populates="question")


class ConstitutionAssessment(Base):
    __tablename__ = "constitution_assessments"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[AssessmentStatus] = mapped_column(
        Enum(AssessmentStatus, name="assessmentstatus"),
        nullable=False,
        default=AssessmentStatus.ANSWERING,
    )
    main_type: Mapped[BodyType | None] = mapped_column(
        Enum(BodyType, name="bodytype"), nullable=True
    )
    # {body_type: {raw_score, converted_score, level: "yes"|"tendency"|"no"}}
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    secondary_types: Mapped[list | None] = mapped_column(JSON, nullable=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    answers: Mapped[list["ConstitutionAnswer"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )


class ConstitutionAnswer(Base):
    __tablename__ = "constitution_answers"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("constitution_assessments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("constitution_questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    answer_value: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    assessment: Mapped["ConstitutionAssessment"] = relationship(back_populates="answers")
    question: Mapped["ConstitutionQuestion"] = relationship(back_populates="answers")
