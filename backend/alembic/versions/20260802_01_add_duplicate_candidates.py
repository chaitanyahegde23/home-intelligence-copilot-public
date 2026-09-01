"""Add duplicate transaction candidates.

Revision ID: 20260802_01
Revises: 20260801_01
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260802_01"
down_revision: str | Sequence[str] | None = "20260801_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DUPLICATE_STATUSES = ("unresolved", "confirmed", "dismissed")
duplicate_candidate_status = postgresql.ENUM(
    *DUPLICATE_STATUSES,
    name="duplicate_candidate_status",
    create_type=False,
)


def upgrade() -> None:
    """Create non-destructive duplicate candidate review state."""
    duplicate_candidate_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "duplicate_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("first_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("second_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            duplicate_candidate_status,
            server_default=sa.text("'unresolved'"),
            nullable=False,
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(fingerprint) = 64",
            name="ck_duplicate_candidates_fingerprint_sha256_length",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_duplicate_candidates_reason_not_blank",
        ),
        sa.CheckConstraint(
            "(status = 'unresolved' AND resolved_at IS NULL) OR "
            "(status IN ('confirmed', 'dismissed') AND resolved_at IS NOT NULL)",
            name="ck_duplicate_candidates_resolution_state_consistent",
        ),
        sa.CheckConstraint(
            "first_transaction_id < second_transaction_id",
            name="ck_duplicate_candidates_transaction_pair_canonical_order",
        ),
        sa.ForeignKeyConstraint(
            ["first_transaction_id"],
            ["transactions.id"],
            name="fk_duplicate_candidates_first_transaction_id_transactions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["second_transaction_id"],
            ["transactions.id"],
            name="fk_duplicate_candidates_second_transaction_id_transactions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_duplicate_candidates"),
        sa.UniqueConstraint(
            "first_transaction_id",
            "second_transaction_id",
            name="uq_duplicate_candidates_first_transaction_id",
        ),
    )
    op.create_index(
        "ix_duplicate_candidates_fingerprint",
        "duplicate_candidates",
        ["fingerprint"],
        unique=False,
    )
    op.create_index(
        "ix_duplicate_candidates_first_transaction_id",
        "duplicate_candidates",
        ["first_transaction_id"],
        unique=False,
    )
    op.create_index(
        "ix_duplicate_candidates_second_transaction_id",
        "duplicate_candidates",
        ["second_transaction_id"],
        unique=False,
    )
    op.create_index(
        "ix_duplicate_candidates_status",
        "duplicate_candidates",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Remove duplicate candidate review state."""
    op.drop_index("ix_duplicate_candidates_status", table_name="duplicate_candidates")
    op.drop_index(
        "ix_duplicate_candidates_second_transaction_id",
        table_name="duplicate_candidates",
    )
    op.drop_index(
        "ix_duplicate_candidates_first_transaction_id",
        table_name="duplicate_candidates",
    )
    op.drop_index("ix_duplicate_candidates_fingerprint", table_name="duplicate_candidates")
    op.drop_table("duplicate_candidates")
    duplicate_candidate_status.drop(op.get_bind(), checkfirst=True)
