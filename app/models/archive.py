"""
档案管理模型 - PatientArchive（居民健康档案）
包括：档案主体、档案标签、家庭档案、家庭成员关系
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy import JSON
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import ArchiveType, IdType


class PatientArchive(Base):
    """居民健康档案主表"""
    __tablename__ = "patient_archives"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 关联系统用户（可选，H5端用户建档后关联）
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, unique=True, index=True
    )

    # ── 基本信息 ──
    name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)  # male/female
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    ethnicity: Mapped[str | None] = mapped_column(String(20), nullable=True, default="汉族")
    occupation: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ── 证件信息 ──
    id_type: Mapped[IdType] = mapped_column(
        Enum(IdType, name="idtype"), nullable=False, default=IdType.ID_CARD
    )
    id_number: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)

    # ── 联系方式 ──
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    phone2: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── 地址信息 ──
    province: Mapped[str | None] = mapped_column(String(50), nullable=True)
    city: Mapped[str | None] = mapped_column(String(50), nullable=True)
    district: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ── 紧急联系人 ──
    emergency_contact_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    emergency_contact_relation: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ── 机构归属 ──
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    responsible_doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── 档案分类 ──
    archive_type: Mapped[ArchiveType] = mapped_column(
        Enum(ArchiveType, name="archivetype"), nullable=False, default=ArchiveType.NORMAL
    )

    # ── 标签（JSON列表）──
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)

    # ── 既往史/家族史/过敏史 ──
    past_history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    family_history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    allergy_history: Mapped[list | None] = mapped_column(JSON, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── 软删除（回收站）──
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FamilyArchive(Base):
    """家庭档案"""
    __tablename__ = "family_archives"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    family_name: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[str | None] = mapped_column(String(200), nullable=True)
    head_archive_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("patient_archives.id", ondelete="SET NULL"), nullable=True
    )
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ArchiveFamilyMember(Base):
    """家庭档案成员关系"""
    __tablename__ = "archive_family_members"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("family_archives.id", ondelete="CASCADE"), nullable=False
    )
    archive_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("patient_archives.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 户主/配偶/子女/父母
    notes: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ArchiveTransfer(Base):
    """档案移交记录"""
    __tablename__ = "archive_transfers"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    archive_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("patient_archives.id", ondelete="CASCADE"), nullable=False
    )
    from_doctor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    to_doctor_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notify: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
