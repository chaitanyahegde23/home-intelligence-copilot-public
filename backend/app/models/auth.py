from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    event,
)
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.household import BOOTSTRAP_HOUSEHOLD_ID
from app.db.base import Base
from app.models.mixins import HouseholdOwnedMixin, TimestampMixin


class UserRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"


class Household(TimestampMixin, Base):
    __tablename__ = "households"
    __table_args__ = (
        CheckConstraint("length(trim(display_name)) > 0", name="display_name_not_blank"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true", nullable=False)

    users: Mapped[list[User]] = relationship(back_populates="household")


@event.listens_for(Household.__table__, "after_create")
def create_local_household(target: object, connection: Connection, **_: object) -> None:
    del target
    connection.execute(
        cast(Table, Household.__table__)
        .insert()
        .values(
            id=BOOTSTRAP_HOUSEHOLD_ID,
            display_name="Local household",
            is_active=True,
        )
    )


class User(HouseholdOwnedMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(normalized_login) BETWEEN 3 AND 100", name="login_length"),
        CheckConstraint("length(password_hash) > 0", name="password_hash_not_blank"),
        UniqueConstraint("household_id", "normalized_login", name="uq_users_household_login"),
        UniqueConstraint("id", "household_id", name="uq_users_id_household"),
        Index("ix_users_household_active", "household_id", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    normalized_login: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default=UserRole.OWNER, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true", nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    household: Mapped[Household] = relationship(back_populates="users")
    sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class AuthSession(HouseholdOwnedMixin, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("length(token_digest) = 64", name="token_digest_length"),
        CheckConstraint("length(csrf_digest) = 64", name="csrf_digest_length"),
        CheckConstraint("idle_expires_at <= absolute_expires_at", name="expiry_ordered"),
        UniqueConstraint("token_digest", name="uq_auth_sessions_token_digest"),
        Index("ix_auth_sessions_household_user", "household_id", "user_id"),
        Index("ix_auth_sessions_expiry", "absolute_expires_at", "idle_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_fingerprint: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="sessions")


class SecurityAuditEvent(HouseholdOwnedMixin, Base):
    __tablename__ = "security_audit_events"
    __table_args__ = (
        CheckConstraint("length(trim(event_type)) > 0", name="event_type_not_blank"),
        CheckConstraint("outcome IN ('succeeded', 'failed', 'denied')", name="outcome_allowed"),
        Index("ix_security_audit_household_created", "household_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    auth_session_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    detail_code: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
