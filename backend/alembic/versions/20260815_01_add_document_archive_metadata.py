"""Add user-managed document archive metadata.

Revision ID: 20260815_01
Revises: 20260809_04
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260815_01"
down_revision: str | Sequence[str] | None = "20260809_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("title", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("document_type", sa.String(length=50), nullable=True))
    op.add_column("documents", sa.Column("notes", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_documents_title_valid",
        "documents",
        "title IS NULL OR (length(trim(title)) > 0 AND length(title) <= 255)",
    )
    op.create_check_constraint(
        "ck_documents_document_type_valid",
        "documents",
        "document_type IS NULL OR "
        "(length(trim(document_type)) > 0 AND length(document_type) <= 50)",
    )
    op.create_check_constraint(
        "ck_documents_notes_valid",
        "documents",
        "notes IS NULL OR (length(trim(notes)) > 0 AND length(notes) <= 2000)",
    )
    op.create_index(
        "ix_documents_household_type_created_at",
        "documents",
        ["household_id", "document_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_household_type_created_at", table_name="documents")
    op.drop_constraint("ck_documents_notes_valid", "documents", type_="check")
    op.drop_constraint("ck_documents_document_type_valid", "documents", type_="check")
    op.drop_constraint("ck_documents_title_valid", "documents", type_="check")
    op.drop_column("documents", "notes")
    op.drop_column("documents", "document_type")
    op.drop_column("documents", "title")
