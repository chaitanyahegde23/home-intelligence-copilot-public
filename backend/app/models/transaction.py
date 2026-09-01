from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import HouseholdOwnedMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.categorization import TransactionCategoryAssignment
    from app.models.duplicate_candidate import DuplicateCandidate
    from app.models.import_batch import ImportBatch


class Transaction(HouseholdOwnedMixin, TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_transaction_date", "transaction_date"),
        Index("ix_transactions_category", "category"),
        Index("ix_transactions_merchant_name", "merchant_name"),
        Index("ix_transactions_import_batch_id", "import_batch_id"),
        Index("ix_transactions_account_name", "account_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    import_batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("import_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_name: Mapped[str | None] = mapped_column(String(255))
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    posted_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    transaction_type: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(255))
    source_file: Mapped[str] = mapped_column(String(512), nullable=False)

    import_batch: Mapped[ImportBatch] = relationship(back_populates="transactions")
    duplicate_candidates_as_first: Mapped[list[DuplicateCandidate]] = relationship(
        foreign_keys="DuplicateCandidate.first_transaction_id",
        back_populates="first_transaction",
        passive_deletes=True,
    )
    duplicate_candidates_as_second: Mapped[list[DuplicateCandidate]] = relationship(
        foreign_keys="DuplicateCandidate.second_transaction_id",
        back_populates="second_transaction",
        passive_deletes=True,
    )

    category_assignment: Mapped[TransactionCategoryAssignment | None] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
