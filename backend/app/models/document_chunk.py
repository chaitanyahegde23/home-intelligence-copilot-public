from __future__ import annotations

from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    literal_column,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import HouseholdOwnedMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.document_extraction import DocumentExtraction, DocumentTextSpan


class DocumentChunk(HouseholdOwnedMixin, TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        CheckConstraint("length(trim(chunker_name)) > 0", name="chunker_name_not_blank"),
        CheckConstraint("length(trim(chunker_version)) > 0", name="chunker_version_not_blank"),
        CheckConstraint("chunk_index > 0", name="chunk_index_positive"),
        CheckConstraint("page_number > 0", name="page_number_positive"),
        CheckConstraint("section_number > 0", name="section_number_positive"),
        CheckConstraint("start_offset >= 0", name="start_offset_non_negative"),
        CheckConstraint("end_offset > start_offset", name="offsets_non_empty_ordered"),
        CheckConstraint("length(text) > 0", name="text_not_empty"),
        CheckConstraint("length(text_sha256) = 64", name="text_sha256_length"),
        UniqueConstraint(
            "extraction_id",
            "chunker_name",
            "chunker_version",
            "chunk_index",
            name="uq_document_chunks_extraction_chunker_index",
        ),
        Index("ix_document_chunks_document", "document_id"),
        Index("ix_document_chunks_extraction", "extraction_id"),
        Index("ix_document_chunks_text_span", "text_span_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    extraction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("document_extractions.id", ondelete="CASCADE"),
        nullable=False,
    )
    text_span_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("document_text_spans.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunker_name: Mapped[str] = mapped_column(String(100), nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(50), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    document: Mapped[Document] = relationship()
    extraction: Mapped[DocumentExtraction] = relationship()
    text_span: Mapped[DocumentTextSpan] = relationship()


Index(
    "ix_document_chunks_lexical_text",
    literal_column("to_tsvector('simple'::regconfig, text)"),
    postgresql_using="gin",
    _table=cast(Table, DocumentChunk.__table__),
).ddl_if(dialect="postgresql")
