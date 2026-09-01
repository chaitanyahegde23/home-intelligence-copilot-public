from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
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

DocumentFactSource = Literal["automatic", "user"]


class DocumentFactType(StrEnum):
    EXPIRATION_DATE = "expiration_date"
    DOCUMENT_DATE = "document_date"
    ISSUER = "issuer"
    REFERENCE_NUMBER = "reference_number"
    DOCUMENT_SUBTYPE = "document_subtype"


class DocumentFact(HouseholdOwnedMixin, TimestampMixin, Base):
    __tablename__ = "document_facts"
    __table_args__ = (
        CheckConstraint(
            "fact_type IN ('expiration_date', 'document_date', 'issuer', "
            "'reference_number', 'document_subtype')",
            name="fact_type_valid",
        ),
        CheckConstraint("source IN ('automatic', 'user')", name="source_valid"),
        CheckConstraint(
            "(CASE WHEN value_text IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN value_date IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN is_cleared THEN 1 ELSE 0 END) = 1",
            name="exactly_one_value_or_clear",
        ),
        CheckConstraint(
            "(fact_type IN ('expiration_date', 'document_date') AND value_text IS NULL) OR "
            "(fact_type NOT IN ('expiration_date', 'document_date') AND value_date IS NULL)",
            name="value_matches_fact_type",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        CheckConstraint(
            "(source = 'automatic' AND extraction_id IS NOT NULL AND confidence IS NOT NULL "
            "AND source_page_number IS NOT NULL AND is_cleared = false) OR "
            "(source = 'user' AND extraction_id IS NULL AND confidence IS NULL "
            "AND source_page_number IS NULL)",
            name="provenance_consistent",
        ),
        CheckConstraint(
            "source_page_number IS NULL OR source_page_number > 0", name="page_positive"
        ),
        CheckConstraint("length(trim(inference_name)) > 0", name="inference_name_not_blank"),
        CheckConstraint("length(trim(inference_version)) > 0", name="inference_version_not_blank"),
        CheckConstraint("length(trim(evidence_code)) > 0", name="evidence_code_not_blank"),
        UniqueConstraint("document_id", "fact_type", name="uq_document_facts_document_type"),
        Index("ix_document_facts_household_expiration", "household_id", "fact_type", "value_date"),
        Index("ix_document_facts_document", "document_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    extraction_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document_extractions.id", ondelete="CASCADE")
    )
    fact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    value_text: Mapped[str | None] = mapped_column(String(255))
    value_date: Mapped[date | None] = mapped_column(Date)
    is_cleared: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)
    source: Mapped[DocumentFactSource] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    source_page_number: Mapped[int | None] = mapped_column(Integer)
    inference_name: Mapped[str] = mapped_column(String(100), nullable=False)
    inference_version: Mapped[str] = mapped_column(String(50), nullable=False)
    evidence_code: Mapped[str] = mapped_column(String(100), nullable=False)

    document: Mapped[Document] = relationship(back_populates="facts")
    extraction: Mapped[DocumentExtraction | None] = relationship()
