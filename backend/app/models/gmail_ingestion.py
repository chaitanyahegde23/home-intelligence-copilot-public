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
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import HouseholdOwnedMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.document import Document


class GmailIngestionStatus(StrEnum):
    PROCESSING = "processing"
    IMPORTED = "imported"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    FAILED = "failed"


class GmailIngestion(HouseholdOwnedMixin, TimestampMixin, Base):
    __tablename__ = "gmail_ingestions"
    __table_args__ = (
        CheckConstraint("length(trim(gmail_message_id)) > 0", name="gmail_message_id_not_blank"),
        CheckConstraint(
            "length(trim(gmail_attachment_id)) > 0", name="gmail_attachment_id_not_blank"
        ),
        CheckConstraint("length(trim(sender)) > 0", name="sender_not_blank"),
        CheckConstraint("length(trim(original_filename)) > 0", name="original_filename_not_blank"),
        CheckConstraint("attempt_count > 0", name="attempt_count_positive"),
        UniqueConstraint(
            "household_id",
            "gmail_message_id",
            "gmail_attachment_id",
            name="uq_gmail_ingestions_household_message_attachment",
        ),
        Index(
            "ix_gmail_ingestions_household_status_updated", "household_id", "status", "updated_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    gmail_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    gmail_attachment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sender: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(500))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[GmailIngestionStatus] = mapped_column(
        SqlEnum(
            GmailIngestionStatus,
            name="gmail_ingestion_status",
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    failure_code: Mapped[str | None] = mapped_column(String(100))
    document_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
    )
    document: Mapped[Document | None] = relationship()
