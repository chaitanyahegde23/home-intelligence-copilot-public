"""Add document collections and tags.

Revision ID: 20260821_02
Revises: 20260821_01
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_02"
down_revision: str | Sequence[str] | None = "20260821_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("collection_name", sa.String(length=100)))
    op.add_column(
        "documents",
        sa.Column("tags", sa.JSON(), server_default="[]", nullable=False),
    )
    op.create_check_constraint(
        "collection_name_valid",
        "documents",
        "collection_name IS NULL OR "
        "(length(trim(collection_name)) > 0 AND length(collection_name) <= 100)",
    )
    op.create_index(
        "ix_documents_household_collection",
        "documents",
        ["household_id", "collection_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_household_collection", table_name="documents")
    op.drop_constraint("ck_documents_collection_name_valid", "documents", type_="check")
    op.drop_column("documents", "tags")
    op.drop_column("documents", "collection_name")
