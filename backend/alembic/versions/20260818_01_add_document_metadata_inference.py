"""Add automated document metadata inference.

Revision ID: 20260818_01
Revises: 20260815_01
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_01"
down_revision: str | Sequence[str] | None = "20260815_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("title_source", sa.String(length=20), nullable=True))
    op.add_column(
        "documents", sa.Column("document_type_source", sa.String(length=20), nullable=True)
    )
    op.execute("UPDATE documents SET title_source = 'user' WHERE title IS NOT NULL")
    op.execute("UPDATE documents SET document_type_source = 'user' WHERE document_type IS NOT NULL")
    op.create_check_constraint(
        "ck_documents_title_source_valid",
        "documents",
        "title_source IS NULL OR title_source IN ('automatic', 'user')",
    )
    op.create_check_constraint(
        "ck_documents_document_type_source_valid",
        "documents",
        "document_type_source IS NULL OR document_type_source IN ('automatic', 'user')",
    )

    op.create_table(
        "document_metadata_inferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("classifier_name", sa.String(length=100), nullable=False),
        sa.Column("classifier_version", sa.String(length=50), nullable=False),
        sa.Column("suggested_title", sa.String(length=255), nullable=False),
        sa.Column("title_evidence_code", sa.String(length=100), nullable=False),
        sa.Column("suggested_document_type", sa.String(length=50), nullable=True),
        sa.Column("document_type_confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("evidence_codes", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(trim(classifier_name)) > 0",
            name="ck_document_metadata_inferences_classifier_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(classifier_version)) > 0",
            name="ck_document_metadata_inferences_classifier_version_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(suggested_title)) > 0",
            name="ck_document_metadata_inferences_suggested_title_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(title_evidence_code)) > 0",
            name="ck_document_metadata_inferences_title_evidence_code_not_blank",
        ),
        sa.CheckConstraint(
            "suggested_document_type IS NULL OR length(trim(suggested_document_type)) > 0",
            name="ck_document_metadata_inferences_suggested_document_type_not_blank",
        ),
        sa.CheckConstraint(
            "document_type_confidence IS NULL OR "
            "(document_type_confidence >= 0 AND document_type_confidence <= 1)",
            name="ck_document_metadata_inferences_document_type_confidence_range",
        ),
        sa.CheckConstraint(
            "(suggested_document_type IS NULL AND document_type_confidence IS NULL) OR "
            "(suggested_document_type IS NOT NULL AND document_type_confidence IS NOT NULL)",
            name="ck_document_metadata_inferences_document_type_confidence_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name="fk_document_metadata_inferences_household_id_households",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_doc_metadata_inference_document",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["document_extractions.id"],
            name="fk_doc_metadata_inference_extraction",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_metadata_inferences"),
        sa.UniqueConstraint(
            "extraction_id",
            "classifier_name",
            "classifier_version",
            name="uq_document_metadata_inferences_identity",
        ),
    )
    op.create_index(
        "ix_document_metadata_inferences_household_id",
        "document_metadata_inferences",
        ["household_id"],
    )
    op.create_index(
        "ix_document_metadata_inferences_document_created",
        "document_metadata_inferences",
        ["document_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_metadata_inferences_document_created",
        table_name="document_metadata_inferences",
    )
    op.drop_index(
        "ix_document_metadata_inferences_household_id",
        table_name="document_metadata_inferences",
    )
    op.drop_table("document_metadata_inferences")
    op.drop_constraint("ck_documents_document_type_source_valid", "documents", type_="check")
    op.drop_constraint("ck_documents_title_source_valid", "documents", type_="check")
    op.drop_column("documents", "document_type_source")
    op.drop_column("documents", "title_source")
