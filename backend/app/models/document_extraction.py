from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import HouseholdOwnedMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.document import Document


class DocumentExtractionStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentExtraction(HouseholdOwnedMixin, TimestampMixin, Base):
    __tablename__ = "document_extractions"
    __table_args__ = (
        CheckConstraint("length(trim(extractor_name)) > 0", name="extractor_name_not_blank"),
        CheckConstraint("length(trim(extractor_version)) > 0", name="extractor_version_not_blank"),
        CheckConstraint("length(document_sha256) = 64", name="document_sha256_length"),
        CheckConstraint(
            "failure_code IS NULL OR length(trim(failure_code)) > 0",
            name="failure_code_not_blank",
        ),
        CheckConstraint(
            "(status = 'processing' AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'completed' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND failure_code IS NULL) OR "
            "(status = 'failed' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND failure_code IS NOT NULL)",
            name="status_fields_consistent",
        ),
        UniqueConstraint(
            "document_id",
            "extractor_name",
            "extractor_version",
            "document_sha256",
            name="uq_document_extractions_identity",
        ),
        Index("ix_document_extractions_document_created", "document_id", "created_at"),
        Index("ix_document_extractions_status_updated", "status", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[DocumentExtractionStatus] = mapped_column(
        SqlEnum(
            DocumentExtractionStatus,
            name="document_extraction_status",
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        nullable=False,
    )
    extractor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(50), nullable=False)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(100))

    document: Mapped[Document] = relationship(back_populates="extractions")
    spans: Mapped[list[DocumentTextSpan]] = relationship(
        back_populates="extraction",
        cascade="all, delete-orphan",
        order_by=lambda: (DocumentTextSpan.page_number, DocumentTextSpan.section_number),
        passive_deletes=True,
    )


class DocumentTextSpan(HouseholdOwnedMixin, TimestampMixin, Base):
    __tablename__ = "document_text_spans"
    __table_args__ = (
        CheckConstraint("page_number > 0", name="page_number_positive"),
        CheckConstraint("section_number > 0", name="section_number_positive"),
        CheckConstraint("start_offset >= 0", name="start_offset_non_negative"),
        CheckConstraint("end_offset >= start_offset", name="offsets_ordered"),
        CheckConstraint("length(text_sha256) = 64", name="text_sha256_length"),
        UniqueConstraint(
            "extraction_id",
            "page_number",
            "section_number",
            name="uq_document_text_spans_location",
        ),
        Index("ix_document_text_spans_extraction_page", "extraction_id", "page_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    extraction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("document_extractions.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    extraction: Mapped[DocumentExtraction] = relationship(back_populates="spans")
