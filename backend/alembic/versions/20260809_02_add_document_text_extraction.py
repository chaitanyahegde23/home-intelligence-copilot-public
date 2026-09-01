"""Add versioned document text extraction provenance.

Revision ID: 20260809_02
Revises: 20260809_01
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260809_02"
down_revision: str | Sequence[str] | None = "20260809_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

document_extraction_status = postgresql.ENUM(
    "processing",
    "completed",
    "failed",
    name="document_extraction_status",
    create_type=False,
)


def upgrade() -> None:
    """Create extraction runs and page/section text provenance."""
    bind = op.get_bind()
    document_extraction_status.create(bind, checkfirst=True)

    op.create_table(
        "document_extractions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("status", document_extraction_status, nullable=False),
        sa.Column("extractor_name", sa.String(length=100), nullable=False),
        sa.Column("extractor_version", sa.String(length=50), nullable=False),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "length(trim(extractor_name)) > 0",
            name="ck_document_extractions_extractor_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(extractor_version)) > 0",
            name="ck_document_extractions_extractor_version_not_blank",
        ),
        sa.CheckConstraint(
            "length(document_sha256) = 64",
            name="ck_document_extractions_document_sha256_length",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR length(trim(failure_code)) > 0",
            name="ck_document_extractions_failure_code_not_blank",
        ),
        sa.CheckConstraint(
            "(status = 'processing' AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'completed' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND failure_code IS NULL) OR "
            "(status = 'failed' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND failure_code IS NOT NULL)",
            name="ck_document_extractions_status_fields_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_extractions_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_extractions"),
        sa.UniqueConstraint(
            "document_id",
            "extractor_name",
            "extractor_version",
            "document_sha256",
            name="uq_document_extractions_identity",
        ),
    )
    op.create_index(
        "ix_document_extractions_document_created",
        "document_extractions",
        ["document_id", "created_at"],
    )
    op.create_index(
        "ix_document_extractions_status_updated",
        "document_extractions",
        ["status", "updated_at"],
    )

    op.create_table(
        "document_text_spans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("section_number", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
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
            "page_number > 0",
            name="ck_document_text_spans_page_number_positive",
        ),
        sa.CheckConstraint(
            "section_number > 0",
            name="ck_document_text_spans_section_number_positive",
        ),
        sa.CheckConstraint(
            "start_offset >= 0",
            name="ck_document_text_spans_start_offset_non_negative",
        ),
        sa.CheckConstraint(
            "end_offset >= start_offset",
            name="ck_document_text_spans_offsets_ordered",
        ),
        sa.CheckConstraint(
            "length(text_sha256) = 64",
            name="ck_document_text_spans_text_sha256_length",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["document_extractions.id"],
            name="fk_document_text_spans_extraction_id_document_extractions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_text_spans"),
        sa.UniqueConstraint(
            "extraction_id",
            "page_number",
            "section_number",
            name="uq_document_text_spans_location",
        ),
    )
    op.create_index(
        "ix_document_text_spans_extraction_page",
        "document_text_spans",
        ["extraction_id", "page_number"],
    )


def downgrade() -> None:
    """Remove extracted text provenance and status type."""
    op.drop_index(
        "ix_document_text_spans_extraction_page",
        table_name="document_text_spans",
    )
    op.drop_table("document_text_spans")
    op.drop_index(
        "ix_document_extractions_status_updated",
        table_name="document_extractions",
    )
    op.drop_index(
        "ix_document_extractions_document_created",
        table_name="document_extractions",
    )
    op.drop_table("document_extractions")

    bind = op.get_bind()
    document_extraction_status.drop(bind, checkfirst=True)
