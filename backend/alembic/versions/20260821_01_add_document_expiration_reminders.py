"""Add document expiration reminders.

Revision ID: 20260821_01
Revises: 20260820_01
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_01"
down_revision: str | Sequence[str] | None = "20260820_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_expiration_reminders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("channel", sa.String(length=20), server_default="in_app", nullable=False),
        sa.Column("lead_time_days", sa.Integer(), server_default="90", nullable=False),
        sa.Column("acknowledged_expiration_date", sa.Date(), nullable=True),
        sa.Column("snoozed_until", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "channel = 'in_app'", name="ck_document_expiration_reminders_channel_in_app"
        ),
        sa.CheckConstraint(
            "lead_time_days >= 0 AND lead_time_days <= 3650",
            name="ck_document_expiration_reminders_lead_time_days_range",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_expiration_reminders_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name="fk_document_expiration_reminders_household_id_households",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_expiration_reminders"),
        sa.UniqueConstraint("document_id", name="uq_document_expiration_reminders_document"),
    )
    op.create_index(
        "ix_document_expiration_reminders_household_id",
        "document_expiration_reminders",
        ["household_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_expiration_reminders_household_enabled",
        "document_expiration_reminders",
        ["household_id", "enabled"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_expiration_reminders_household_enabled",
        table_name="document_expiration_reminders",
    )
    op.drop_index(
        "ix_document_expiration_reminders_household_id",
        table_name="document_expiration_reminders",
    )
    op.drop_table("document_expiration_reminders")
