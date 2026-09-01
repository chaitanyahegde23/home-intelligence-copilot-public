"""Add private document metadata and deletion audit.

Revision ID: 20260809_01
Revises: 20260802_02
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260809_01"
down_revision: str | Sequence[str] | None = "20260802_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

document_status = postgresql.ENUM(
    "pending",
    "stored",
    "deleting",
    "failed",
    name="document_status",
    create_type=False,
)
document_source = postgresql.ENUM(
    "user_upload",
    name="document_source",
    create_type=False,
)


def upgrade() -> None:
    """Create document metadata and privacy-safe deletion audits."""
    bind = op.get_bind()
    document_status.create(bind, checkfirst=True)
    document_source.create(bind, checkfirst=True)

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            document_status,
            server_default="pending",
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column(
            "media_type",
            sa.String(length=100),
            server_default="application/pdf",
            nullable=False,
        ),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "storage_backend",
            sa.String(length=50),
            server_default="private_filesystem_v1",
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column(
            "source",
            document_source,
            server_default="user_upload",
            nullable=False,
        ),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
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
            "length(trim(original_filename)) > 0",
            name="ck_documents_original_filename_not_blank",
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_documents_size_bytes_positive",
        ),
        sa.CheckConstraint(
            "media_type = 'application/pdf'",
            name="ck_documents_media_type_pdf",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_documents_sha256_length",
        ),
        sa.CheckConstraint(
            "length(trim(storage_backend)) > 0",
            name="ck_documents_storage_backend_not_blank",
        ),
        sa.CheckConstraint(
            "storage_backend = 'private_filesystem_v1'",
            name="ck_documents_storage_backend_private",
        ),
        sa.CheckConstraint(
            "length(trim(storage_key)) > 0",
            name="ck_documents_storage_key_not_blank",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR length(trim(failure_code)) > 0",
            name="ck_documents_failure_code_not_blank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.UniqueConstraint(
            "sha256",
            "size_bytes",
            name="uq_documents_sha256_size_bytes",
        ),
        sa.UniqueConstraint("storage_key", name="uq_documents_storage_key"),
    )
    op.create_index(
        "ix_documents_status_created_at",
        "documents",
        ["status", "created_at"],
    )

    op.create_table(
        "document_deletion_audits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "event_type",
            sa.String(length=20),
            server_default="deleted",
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.String(length=20),
            server_default="completed",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type = 'deleted'",
            name="ck_document_deletion_audits_event_type_deleted",
        ),
        sa.CheckConstraint(
            "outcome = 'completed'",
            name="ck_document_deletion_audits_outcome_completed",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_deletion_audits"),
        sa.UniqueConstraint(
            "document_id",
            name="uq_document_deletion_audits_document_id",
        ),
    )


def downgrade() -> None:
    """Remove document storage metadata and enum types."""
    op.drop_table("document_deletion_audits")
    op.drop_index("ix_documents_status_created_at", table_name="documents")
    op.drop_table("documents")

    bind = op.get_bind()
    document_source.drop(bind, checkfirst=True)
    document_status.drop(bind, checkfirst=True)
