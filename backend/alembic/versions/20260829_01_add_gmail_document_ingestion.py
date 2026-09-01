"""Add Gmail document ingestion audit records.

Revision ID: 20260829_01
Revises: 20260821_02
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260829_01"
down_revision: str | Sequence[str] | None = "20260821_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE document_source ADD VALUE IF NOT EXISTS 'gmail_attachment'")
    gmail_status = postgresql.ENUM(
        "processing",
        "imported",
        "duplicate",
        "rejected",
        "failed",
        name="gmail_ingestion_status",
        create_type=False,
    )
    gmail_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "gmail_ingestions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("gmail_message_id", sa.String(length=255), nullable=False),
        sa.Column("gmail_attachment_id", sa.String(length=255), nullable=False),
        sa.Column("sender", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=500)),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("status", gmail_status, nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("failure_code", sa.String(length=100)),
        sa.Column("document_id", sa.Uuid()),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(trim(gmail_message_id)) > 0", name="gmail_message_id_not_blank"),
        sa.CheckConstraint(
            "length(trim(gmail_attachment_id)) > 0", name="gmail_attachment_id_not_blank"
        ),
        sa.CheckConstraint("length(trim(sender)) > 0", name="sender_not_blank"),
        sa.CheckConstraint(
            "length(trim(original_filename)) > 0", name="original_filename_not_blank"
        ),
        sa.CheckConstraint("attempt_count > 0", name="attempt_count_positive"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "household_id",
            "gmail_message_id",
            "gmail_attachment_id",
            name="uq_gmail_ingestions_household_message_attachment",
        ),
    )
    op.create_index("ix_gmail_ingestions_document_id", "gmail_ingestions", ["document_id"])
    op.create_index("ix_gmail_ingestions_household_id", "gmail_ingestions", ["household_id"])
    op.create_index(
        "ix_gmail_ingestions_household_status_updated",
        "gmail_ingestions",
        ["household_id", "status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_gmail_ingestions_household_status_updated", table_name="gmail_ingestions")
    op.drop_index("ix_gmail_ingestions_household_id", table_name="gmail_ingestions")
    op.drop_index("ix_gmail_ingestions_document_id", table_name="gmail_ingestions")
    op.drop_table("gmail_ingestions")
    postgresql.ENUM(name="gmail_ingestion_status").drop(op.get_bind(), checkfirst=True)
    # PostgreSQL enum values cannot be safely removed while preserving existing rows.
