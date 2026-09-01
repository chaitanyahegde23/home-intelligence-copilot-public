from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import HouseholdOwnedMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.document import Document

DocumentReminderChannel = Literal["in_app"]


class DocumentExpirationReminder(HouseholdOwnedMixin, TimestampMixin, Base):
    __tablename__ = "document_expiration_reminders"
    __table_args__ = (
        CheckConstraint("channel = 'in_app'", name="channel_in_app"),
        CheckConstraint(
            "lead_time_days >= 0 AND lead_time_days <= 3650",
            name="lead_time_days_range",
        ),
        UniqueConstraint("document_id", name="uq_document_expiration_reminders_document"),
        Index(
            "ix_document_expiration_reminders_household_enabled",
            "household_id",
            "enabled",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    channel: Mapped[DocumentReminderChannel] = mapped_column(
        String(20), default="in_app", server_default="in_app", nullable=False
    )
    lead_time_days: Mapped[int] = mapped_column(
        Integer, default=90, server_default="90", nullable=False
    )
    acknowledged_expiration_date: Mapped[date | None] = mapped_column(Date)
    snoozed_until: Mapped[date | None] = mapped_column(Date)

    document: Mapped[Document] = relationship(back_populates="expiration_reminder")
