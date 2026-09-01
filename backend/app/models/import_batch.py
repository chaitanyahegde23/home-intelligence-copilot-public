from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Integer, String, Uuid
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import HouseholdOwnedMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.transaction import Transaction

CANONICAL_ADAPTER_NAME = "canonical_csv"
CANONICAL_ADAPTER_VERSION = "1"


class ImportStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class ImportBatch(HouseholdOwnedMixin, TimestampMixin, Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint("row_count >= 0", name="row_count_non_negative"),
        CheckConstraint("imported_count >= 0", name="imported_count_non_negative"),
        CheckConstraint("rejected_count >= 0", name="rejected_count_non_negative"),
        CheckConstraint("length(trim(adapter_name)) > 0", name="adapter_name_not_blank"),
        CheckConstraint("length(trim(adapter_version)) > 0", name="adapter_version_not_blank"),
        CheckConstraint(
            "account_label IS NULL OR length(trim(account_label)) > 0",
            name="account_label_not_blank",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    adapter_name: Mapped[str] = mapped_column(
        String(100),
        default=CANONICAL_ADAPTER_NAME,
        server_default=CANONICAL_ADAPTER_NAME,
        nullable=False,
    )
    adapter_version: Mapped[str] = mapped_column(
        String(50),
        default=CANONICAL_ADAPTER_VERSION,
        server_default=CANONICAL_ADAPTER_VERSION,
        nullable=False,
    )
    account_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ImportStatus] = mapped_column(
        SqlEnum(
            ImportStatus,
            name="import_batch_status",
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        default=ImportStatus.PENDING,
        server_default=ImportStatus.PENDING.value,
        nullable=False,
    )
    row_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    imported_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    rejected_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="import_batch",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
