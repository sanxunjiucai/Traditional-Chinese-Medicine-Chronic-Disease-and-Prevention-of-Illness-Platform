"""
临床数据模型 - 对接 HIS/LIS/PACS/设备的就诊与临床文档。
演示模式下使用 mock 数据；生产环境通过接口同步填充。
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text, func
from sqlalchemy import JSON
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import DocumentType


class ClinicalDocument(Base):
    """
    临床文档统一对象。
    doc_type 区分：就诊记录/门诊病历/住院病历/处方/治疗/检验/影像/设备
    """
    __tablename__ = "clinical_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 关联患者档案（用 archive_id）
    archive_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    patient_name: Mapped[str | None] = mapped_column(String(50), nullable=True)

    doc_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType, name="documenttype"), nullable=False, index=True
    )
    source_system: Mapped[str | None] = mapped_column(String(20), nullable=True)  # HIS/LIS/PACS/DEVICE

    # 外部引用号（report_no、prescription_id等）
    external_ref_no: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    encounter_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 就诊号

    # 基础元数据
    dept: Mapped[str | None] = mapped_column(String(100), nullable=True)
    doctor: Mapped[str | None] = mapped_column(String(50), nullable=True)
    doc_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    # 文档内容（结构化JSON，按 doc_type 不同而不同）
    content: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 同步状态
    sync_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)  # AUTO/MANUAL/PUSHED
    sync_batch: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 同步批次号

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SyncLog(Base):
    """数据同步日志"""
    __tablename__ = "sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    sync_type: Mapped[str] = mapped_column(String(50), nullable=False)  # HIS_ENCOUNTER 等
    trigger_mode: Mapped[str] = mapped_column(String(20), nullable=False)  # AUTO/MANUAL
    status: Mapped[str] = mapped_column(String(20), nullable=False)       # SUCCESS/PARTIAL/FAILED
    total_count: Mapped[int] = mapped_column(default=0)
    success_count: Mapped[int] = mapped_column(default=0)
    fail_count: Mapped[int] = mapped_column(default=0)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
