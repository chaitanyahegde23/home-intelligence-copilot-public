"""Add structured document facts.

Revision ID: 20260820_01
Revises: 20260818_01
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260820_01"
down_revision: str | Sequence[str] | None = "20260818_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=True),
        sa.Column("fact_type", sa.String(length=50), nullable=False),
        sa.Column("value_text", sa.String(length=255), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("is_cleared", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("source_page_number", sa.Integer(), nullable=True),
        sa.Column("inference_name", sa.String(length=100), nullable=False),
        sa.Column("inference_version", sa.String(length=50), nullable=False),
        sa.Column("evidence_code", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "fact_type IN ('expiration_date', 'document_date', 'issuer', "
            "'reference_number', 'document_subtype')",
            name="ck_document_facts_fact_type_valid",
        ),
        sa.CheckConstraint(
            "source IN ('automatic', 'user')", name="ck_document_facts_source_valid"
        ),
        sa.CheckConstraint(
            "(CASE WHEN value_text IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN value_date IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN is_cleared THEN 1 ELSE 0 END) = 1",
            name="ck_document_facts_exactly_one_value_or_clear",
        ),
        sa.CheckConstraint(
            "(fact_type IN ('expiration_date', 'document_date') AND value_text IS NULL) OR "
            "(fact_type NOT IN ('expiration_date', 'document_date') AND value_date IS NULL)",
            name="ck_document_facts_value_matches_fact_type",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_document_facts_confidence_range",
        ),
        sa.CheckConstraint(
            "(source = 'automatic' AND extraction_id IS NOT NULL AND confidence IS NOT NULL "
            "AND source_page_number IS NOT NULL AND is_cleared = false) OR "
            "(source = 'user' AND extraction_id IS NULL AND confidence IS NULL "
            "AND source_page_number IS NULL)",
            name="ck_document_facts_provenance_consistent",
        ),
        sa.CheckConstraint(
            "source_page_number IS NULL OR source_page_number > 0",
            name="ck_document_facts_page_positive",
        ),
        sa.CheckConstraint(
            "length(trim(inference_name)) > 0",
            name="ck_document_facts_inference_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(inference_version)) > 0",
            name="ck_document_facts_inference_version_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(evidence_code)) > 0",
            name="ck_document_facts_evidence_code_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name="fk_document_facts_household_id_households",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_facts_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["document_extractions.id"],
            name="fk_document_facts_extraction_id_document_extractions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_facts"),
        sa.UniqueConstraint("document_id", "fact_type", name="uq_document_facts_document_type"),
    )
    op.create_index("ix_document_facts_household_id", "document_facts", ["household_id"])
    op.create_index("ix_document_facts_document", "document_facts", ["document_id"])
    op.create_index(
        "ix_document_facts_household_expiration",
        "document_facts",
        ["household_id", "fact_type", "value_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_facts_household_expiration", table_name="document_facts")
    op.drop_index("ix_document_facts_document", table_name="document_facts")
    op.drop_index("ix_document_facts_household_id", table_name="document_facts")
    op.drop_table("document_facts")
