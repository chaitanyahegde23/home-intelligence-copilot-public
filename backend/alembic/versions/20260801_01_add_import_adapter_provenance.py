"""Add import adapter provenance.

Revision ID: 20260801_01
Revises: 20260725_01
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260801_01"
down_revision: str | Sequence[str] | None = "20260725_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record the adapter identity and optional safe account label for each import."""
    op.add_column(
        "import_batches",
        sa.Column(
            "adapter_name",
            sa.String(length=100),
            server_default=sa.text("'canonical_csv'"),
            nullable=False,
        ),
    )
    op.add_column(
        "import_batches",
        sa.Column(
            "adapter_version",
            sa.String(length=50),
            server_default=sa.text("'1'"),
            nullable=False,
        ),
    )
    op.add_column(
        "import_batches",
        sa.Column("account_label", sa.String(length=255), nullable=True),
    )
    op.create_check_constraint(
        "adapter_name_not_blank",
        "import_batches",
        "length(trim(adapter_name)) > 0",
    )
    op.create_check_constraint(
        "adapter_version_not_blank",
        "import_batches",
        "length(trim(adapter_version)) > 0",
    )
    op.create_check_constraint(
        "account_label_not_blank",
        "import_batches",
        "account_label IS NULL OR length(trim(account_label)) > 0",
    )


def downgrade() -> None:
    """Remove import adapter provenance."""
    op.drop_constraint(
        "ck_import_batches_account_label_not_blank",
        "import_batches",
        type_="check",
    )
    op.drop_constraint(
        "ck_import_batches_adapter_version_not_blank",
        "import_batches",
        type_="check",
    )
    op.drop_constraint(
        "ck_import_batches_adapter_name_not_blank",
        "import_batches",
        type_="check",
    )
    op.drop_column("import_batches", "account_label")
    op.drop_column("import_batches", "adapter_version")
    op.drop_column("import_batches", "adapter_name")
