"""Add deterministic document chunks and PostgreSQL lexical index.

Revision ID: 20260809_03
Revises: 20260809_02
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_03"
down_revision: str | Sequence[str] | None = "20260809_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create provenance-preserving chunks and a simple-config GIN index."""
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("text_span_id", sa.Uuid(), nullable=False),
        sa.Column("chunker_name", sa.String(length=100), nullable=False),
        sa.Column("chunker_version", sa.String(length=50), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
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
            "length(trim(chunker_name)) > 0",
            name="ck_document_chunks_chunker_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(chunker_version)) > 0",
            name="ck_document_chunks_chunker_version_not_blank",
        ),
        sa.CheckConstraint(
            "chunk_index > 0",
            name="ck_document_chunks_chunk_index_positive",
        ),
        sa.CheckConstraint(
            "page_number > 0",
            name="ck_document_chunks_page_number_positive",
        ),
        sa.CheckConstraint(
            "section_number > 0",
            name="ck_document_chunks_section_number_positive",
        ),
        sa.CheckConstraint(
            "start_offset >= 0",
            name="ck_document_chunks_start_offset_non_negative",
        ),
        sa.CheckConstraint(
            "end_offset > start_offset",
            name="ck_document_chunks_offsets_non_empty_ordered",
        ),
        sa.CheckConstraint(
            "length(text) > 0",
            name="ck_document_chunks_text_not_empty",
        ),
        sa.CheckConstraint(
            "length(text_sha256) = 64",
            name="ck_document_chunks_text_sha256_length",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_chunks_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["document_extractions.id"],
            name="fk_document_chunks_extraction_id_document_extractions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["text_span_id"],
            ["document_text_spans.id"],
            name="fk_document_chunks_text_span_id_document_text_spans",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        sa.UniqueConstraint(
            "extraction_id",
            "chunker_name",
            "chunker_version",
            "chunk_index",
            name="uq_document_chunks_extraction_chunker_index",
        ),
    )
    op.create_index("ix_document_chunks_document", "document_chunks", ["document_id"])
    op.create_index("ix_document_chunks_extraction", "document_chunks", ["extraction_id"])
    op.create_index("ix_document_chunks_text_span", "document_chunks", ["text_span_id"])
    op.create_index(
        "ix_document_chunks_lexical_text",
        "document_chunks",
        [sa.text("to_tsvector('simple', text)")],
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Remove lexical chunks and indexes."""
    op.drop_index("ix_document_chunks_lexical_text", table_name="document_chunks")
    op.drop_index("ix_document_chunks_text_span", table_name="document_chunks")
    op.drop_index("ix_document_chunks_extraction", table_name="document_chunks")
    op.drop_index("ix_document_chunks_document", table_name="document_chunks")
    op.drop_table("document_chunks")
