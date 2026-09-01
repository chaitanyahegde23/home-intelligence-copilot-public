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
    from app.models.transaction import Transaction


class DuplicateStatus(StrEnum):
    UNRESOLVED = "unresolved"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class DuplicateCandidate(HouseholdOwnedMixin, TimestampMixin, Base):
    __tablename__ = "duplicate_candidates"
    __table_args__ = (
        CheckConstraint(
            "first_transaction_id < second_transaction_id",
            name="transaction_pair_canonical_order",
        ),
        CheckConstraint("length(fingerprint) = 64", name="fingerprint_sha256_length"),
        CheckConstraint("length(trim(reason)) > 0", name="reason_not_blank"),
        CheckConstraint(
            "(status = 'unresolved' AND resolved_at IS NULL) OR "
            "(status IN ('confirmed', 'dismissed') AND resolved_at IS NOT NULL)",
            name="resolution_state_consistent",
        ),
        UniqueConstraint("first_transaction_id", "second_transaction_id"),
        Index("ix_duplicate_candidates_fingerprint", "fingerprint"),
        Index("ix_duplicate_candidates_status", "status"),
        Index("ix_duplicate_candidates_first_transaction_id", "first_transaction_id"),
        Index("ix_duplicate_candidates_second_transaction_id", "second_transaction_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    first_transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    second_transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[DuplicateStatus] = mapped_column(
        SqlEnum(
            DuplicateStatus,
            name="duplicate_candidate_status",
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        default=DuplicateStatus.UNRESOLVED,
        server_default=DuplicateStatus.UNRESOLVED.value,
        nullable=False,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    first_transaction: Mapped[Transaction] = relationship(
        foreign_keys=[first_transaction_id],
        back_populates="duplicate_candidates_as_first",
    )
    second_transaction: Mapped[Transaction] = relationship(
        foreign_keys=[second_transaction_id],
        back_populates="duplicate_candidates_as_second",
    )
