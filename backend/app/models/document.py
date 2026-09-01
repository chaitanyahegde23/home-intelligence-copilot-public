from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.document_extraction import DocumentExtraction
    from app.models.document_fact import DocumentFact
    from app.models.document_metadata import DocumentMetadataInference
    from app.models.document_reminder import DocumentExpirationReminder

from app.db.base import Base
from app.models.mixins import HouseholdOwnedMixin, TimestampMixin, utc_now

PRIVATE_FILESYSTEM_BACKEND = "private_filesystem_v1"
PDF_MEDIA_TYPE = "application/pdf"
DocumentMetadataSource = Literal["automatic", "user"]


class DocumentStatus(StrEnum):
    PENDING = "pending"
    STORED = "stored"
    DELETING = "deleting"
    FAILED = "failed"


class DocumentSource(StrEnum):
    USER_UPLOAD = "user_upload"
    GMAIL_ATTACHMENT = "gmail_attachment"


class Document(HouseholdOwnedMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "length(trim(original_filename)) > 0",
            name="original_filename_not_blank",
        ),
        CheckConstraint("media_type = 'application/pdf'", name="media_type_pdf"),
        CheckConstraint("size_bytes > 0", name="size_bytes_positive"),
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
        CheckConstraint(
            "storage_backend = 'private_filesystem_v1'", name="storage_backend_private"
        ),
        CheckConstraint(
            "length(trim(storage_backend)) > 0",
            name="storage_backend_not_blank",
        ),
        CheckConstraint(
            "length(trim(storage_key)) > 0",
            name="storage_key_not_blank",
        ),
        CheckConstraint(
            "failure_code IS NULL OR length(trim(failure_code)) > 0",
            name="failure_code_not_blank",
        ),
        CheckConstraint(
            "title IS NULL OR (length(trim(title)) > 0 AND length(title) <= 255)",
            name="title_valid",
        ),
        CheckConstraint(
            "document_type IS NULL OR "
            "(length(trim(document_type)) > 0 AND length(document_type) <= 50)",
            name="document_type_valid",
        ),
        CheckConstraint(
            "notes IS NULL OR (length(trim(notes)) > 0 AND length(notes) <= 2000)",
            name="notes_valid",
        ),
        CheckConstraint(
            "collection_name IS NULL OR "
            "(length(trim(collection_name)) > 0 AND length(collection_name) <= 100)",
            name="collection_name_valid",
        ),
        CheckConstraint(
            "title_source IS NULL OR title_source IN ('automatic', 'user')",
            name="title_source_valid",
        ),
        CheckConstraint(
            "document_type_source IS NULL OR document_type_source IN ('automatic', 'user')",
            name="document_type_source_valid",
        ),
        UniqueConstraint(
            "household_id",
            "sha256",
            "size_bytes",
            name="uq_documents_household_sha256_size",
        ),
        UniqueConstraint("storage_key", name="uq_documents_storage_key"),
        Index("ix_documents_status_created_at", "status", "created_at"),
        Index(
            "ix_documents_household_type_created_at",
            "household_id",
            "document_type",
            "created_at",
        ),
        Index("ix_documents_household_collection", "household_id", "collection_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    status: Mapped[DocumentStatus] = mapped_column(
        SqlEnum(
            DocumentStatus,
            name="document_status",
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        default=DocumentStatus.PENDING,
        server_default=DocumentStatus.PENDING.value,
        nullable=False,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(
        String(100),
        default=PDF_MEDIA_TYPE,
        server_default=PDF_MEDIA_TYPE,
        nullable=False,
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_backend: Mapped[str] = mapped_column(
        String(50),
        default=PRIVATE_FILESYSTEM_BACKEND,
        server_default=PRIVATE_FILESYSTEM_BACKEND,
        nullable=False,
    )
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[DocumentSource] = mapped_column(
        SqlEnum(
            DocumentSource,
            name="document_source",
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        default=DocumentSource.USER_UPLOAD,
        server_default=DocumentSource.USER_UPLOAD.value,
        nullable=False,
    )
    failure_code: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(String(255))
    title_source: Mapped[DocumentMetadataSource | None] = mapped_column(String(20))
    document_type: Mapped[str | None] = mapped_column(String(50))
    document_type_source: Mapped[DocumentMetadataSource | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    collection_name: Mapped[str | None] = mapped_column(String(100))
    tags: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list, server_default="[]", nullable=False
    )

    extractions: Mapped[list[DocumentExtraction]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    metadata_inferences: Mapped[list[DocumentMetadataInference]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    facts: Mapped[list[DocumentFact]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentFact.fact_type",
    )
    expiration_reminder: Mapped[DocumentExpirationReminder | None] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class DocumentDeletionAudit(HouseholdOwnedMixin, Base):
    __tablename__ = "document_deletion_audits"
    __table_args__ = (
        CheckConstraint("event_type = 'deleted'", name="event_type_deleted"),
        CheckConstraint("outcome = 'completed'", name="outcome_completed"),
        UniqueConstraint("document_id", name="uq_document_deletion_audits_document_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(
        String(20), default="deleted", server_default="deleted", nullable=False
    )
    outcome: Mapped[str] = mapped_column(
        String(20), default="completed", server_default="completed", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
