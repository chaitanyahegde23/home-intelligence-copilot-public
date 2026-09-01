from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import HouseholdOwnedMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.document_extraction import DocumentExtraction


class DocumentMetadataInference(HouseholdOwnedMixin, TimestampMixin, Base):
    __tablename__ = "document_metadata_inferences"
    __table_args__ = (
        CheckConstraint("length(trim(classifier_name)) > 0", name="classifier_name_not_blank"),
        CheckConstraint(
            "length(trim(classifier_version)) > 0", name="classifier_version_not_blank"
        ),
        CheckConstraint("length(trim(suggested_title)) > 0", name="suggested_title_not_blank"),
        CheckConstraint(
            "length(trim(title_evidence_code)) > 0", name="title_evidence_code_not_blank"
        ),
        CheckConstraint(
            "suggested_document_type IS NULL OR length(trim(suggested_document_type)) > 0",
            name="suggested_document_type_not_blank",
        ),
        CheckConstraint(
            "document_type_confidence IS NULL OR "
            "(document_type_confidence >= 0 AND document_type_confidence <= 1)",
            name="document_type_confidence_range",
        ),
        CheckConstraint(
            "(suggested_document_type IS NULL AND document_type_confidence IS NULL) OR "
            "(suggested_document_type IS NOT NULL AND document_type_confidence IS NOT NULL)",
            name="document_type_confidence_consistent",
        ),
        UniqueConstraint(
            "extraction_id",
            "classifier_name",
            "classifier_version",
            name="uq_document_metadata_inferences_identity",
        ),
        Index("ix_document_metadata_inferences_document_created", "document_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE", name="fk_doc_metadata_inference_document"),
        nullable=False,
    )
    extraction_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "document_extractions.id",
            ondelete="CASCADE",
            name="fk_doc_metadata_inference_extraction",
        ),
        nullable=False,
    )
    classifier_name: Mapped[str] = mapped_column(String(100), nullable=False)
    classifier_version: Mapped[str] = mapped_column(String(50), nullable=False)
    suggested_title: Mapped[str] = mapped_column(String(255), nullable=False)
    title_evidence_code: Mapped[str] = mapped_column(String(100), nullable=False)
    suggested_document_type: Mapped[str | None] = mapped_column(String(50))
    document_type_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    evidence_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    document: Mapped[Document] = relationship(back_populates="metadata_inferences")
    extraction: Mapped[DocumentExtraction] = relationship()
