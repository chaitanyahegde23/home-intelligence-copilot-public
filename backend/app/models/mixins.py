from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.household import BOOTSTRAP_HOUSEHOLD_ID


def utc_now() -> datetime:
    return datetime.now(UTC)


class HouseholdOwnedMixin:
    household_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("households.id", ondelete="RESTRICT"),
        default=BOOTSTRAP_HOUSEHOLD_ID,
        index=True,
        nullable=False,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )
