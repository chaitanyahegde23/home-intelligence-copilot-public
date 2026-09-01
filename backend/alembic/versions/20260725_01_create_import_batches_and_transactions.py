"""Create import batches and transactions.

Revision ID: 20260725_01
Revises:
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260725_01"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMPORT_STATUSES = (
    "pending",
    "processing",
    "completed",
    "completed_with_errors",
    "failed",
)
import_batch_status = postgresql.ENUM(
    *IMPORT_STATUSES,
    name="import_batch_status",
    create_type=False,
)


def upgrade() -> None:
    """Create import batches, transactions, constraints, and indexes."""
    import_batch_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column(
            "status",
            import_batch_status,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("row_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("imported_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("rejected_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
            "imported_count >= 0",
            name="imported_count_non_negative",
        ),
        sa.CheckConstraint(
            "rejected_count >= 0",
            name="rejected_count_non_negative",
        ),
        sa.CheckConstraint("row_count >= 0", name="row_count_non_negative"),
        sa.PrimaryKeyConstraint("id", name="pk_import_batches"),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("import_batch_id", sa.Uuid(), nullable=False),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("posted_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("merchant_name", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("transaction_type", sa.String(length=100), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("source_file", sa.String(length=512), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["import_batches.id"],
            name="fk_transactions_import_batch_id_import_batches",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
    )
    op.create_index(
        "ix_transactions_account_name",
        "transactions",
        ["account_name"],
        unique=False,
    )
    op.create_index("ix_transactions_category", "transactions", ["category"], unique=False)
    op.create_index(
        "ix_transactions_import_batch_id",
        "transactions",
        ["import_batch_id"],
        unique=False,
    )
    op.create_index(
        "ix_transactions_merchant_name",
        "transactions",
        ["merchant_name"],
        unique=False,
    )
    op.create_index(
        "ix_transactions_transaction_date",
        "transactions",
        ["transaction_date"],
        unique=False,
    )


def downgrade() -> None:
    """Drop transactions and import batches."""
    op.drop_index("ix_transactions_transaction_date", table_name="transactions")
    op.drop_index("ix_transactions_merchant_name", table_name="transactions")
    op.drop_index("ix_transactions_import_batch_id", table_name="transactions")
    op.drop_index("ix_transactions_category", table_name="transactions")
    op.drop_index("ix_transactions_account_name", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("import_batches")
    import_batch_status.drop(op.get_bind(), checkfirst=True)
