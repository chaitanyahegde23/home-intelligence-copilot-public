"""Add transaction categorization schema.

Revision ID: 20260802_02
Revises: 20260802_01
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260802_02"
down_revision: str | Sequence[str] | None = "20260802_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

rule_match_field = postgresql.ENUM(
    "description",
    "merchant_name",
    name="categorization_rule_match_field",
    create_type=False,
)
rule_match_type = postgresql.ENUM(
    "exact",
    "prefix",
    "contains",
    name="categorization_rule_match_type",
    create_type=False,
)
category_assignment_source = postgresql.ENUM(
    "imported",
    "rule",
    "manual",
    name="category_assignment_source",
    create_type=False,
)


def upgrade() -> None:
    """Create the category catalog, rules, and current assignments."""
    bind = op.get_bind()
    rule_match_field.create(bind, checkfirst=True)
    rule_match_type.create(bind, checkfirst=True)
    category_assignment_source.create(bind, checkfirst=True)

    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
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
            "length(trim(name)) > 0",
            name="ck_categories_name_not_blank",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(trim(description)) > 0",
            name="ck_categories_description_not_blank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        sa.UniqueConstraint("name", name="uq_categories_name"),
    )
    op.create_index("ix_categories_is_active", "categories", ["is_active"])

    op.create_table(
        "categorization_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("match_field", rule_match_field, nullable=False),
        sa.Column("match_type", rule_match_type, nullable=False),
        sa.Column("pattern", sa.String(length=500), nullable=False),
        sa.Column(
            "case_sensitive",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
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
            "length(trim(pattern)) > 0",
            name="ck_categorization_rules_pattern_not_blank",
        ),
        sa.CheckConstraint(
            "priority >= 0",
            name="ck_categorization_rules_priority_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name="fk_categorization_rules_category_id_categories",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_categorization_rules"),
    )
    op.create_index(
        "ix_categorization_rules_category_id",
        "categorization_rules",
        ["category_id"],
    )
    op.create_index(
        "ix_categorization_rules_is_active_priority",
        "categorization_rules",
        ["is_active", "priority"],
    )

    op.create_table(
        "transaction_category_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("source", category_assignment_source, nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
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
            "(source = 'rule' AND rule_id IS NOT NULL) OR "
            "(source IN ('imported', 'manual') AND rule_id IS NULL)",
            name="ck_transaction_category_assignments_source_rule_consistent",
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(trim(note)) > 0",
            name="ck_transaction_category_assignments_note_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name="fk_tx_category_assignments_transaction_id_transactions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name="fk_tx_category_assignments_category_id_categories",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["categorization_rules.id"],
            name="fk_tx_category_assignments_rule_id_rules",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transaction_category_assignments"),
        sa.UniqueConstraint(
            "transaction_id",
            name="uq_transaction_category_assignments_transaction_id",
        ),
    )
    op.create_index(
        "ix_transaction_category_assignments_category_id",
        "transaction_category_assignments",
        ["category_id"],
    )
    op.create_index(
        "ix_transaction_category_assignments_rule_id",
        "transaction_category_assignments",
        ["rule_id"],
    )
    op.create_index(
        "ix_transaction_category_assignments_source",
        "transaction_category_assignments",
        ["source"],
    )


def downgrade() -> None:
    """Remove categorization state without changing transaction rows."""
    op.drop_index(
        "ix_transaction_category_assignments_source",
        table_name="transaction_category_assignments",
    )
    op.drop_index(
        "ix_transaction_category_assignments_rule_id",
        table_name="transaction_category_assignments",
    )
    op.drop_index(
        "ix_transaction_category_assignments_category_id",
        table_name="transaction_category_assignments",
    )
    op.drop_table("transaction_category_assignments")
    op.drop_index(
        "ix_categorization_rules_is_active_priority",
        table_name="categorization_rules",
    )
    op.drop_index(
        "ix_categorization_rules_category_id",
        table_name="categorization_rules",
    )
    op.drop_table("categorization_rules")
    op.drop_index("ix_categories_is_active", table_name="categories")
    op.drop_table("categories")

    bind = op.get_bind()
    category_assignment_source.drop(bind, checkfirst=True)
    rule_match_type.drop(bind, checkfirst=True)
    rule_match_field.drop(bind, checkfirst=True)
