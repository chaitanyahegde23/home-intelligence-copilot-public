"""Add authentication, sessions, audits, and household ownership.

Revision ID: 20260809_04
Revises: 20260809_03
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_04"
down_revision: str | Sequence[str] | None = "20260809_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BOOTSTRAP_HOUSEHOLD_ID = "00000000-0000-4000-8000-000000000001"
OWNED_TABLES = (
    "import_batches",
    "transactions",
    "categories",
    "categorization_rules",
    "transaction_category_assignments",
    "duplicate_candidates",
    "documents",
    "document_deletion_audits",
    "document_extractions",
    "document_text_spans",
    "document_chunks",
)


def upgrade() -> None:
    """Create security roots and backfill one authoritative local household."""
    op.create_table(
        "households",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(trim(display_name)) > 0",
            name="ck_households_display_name_not_blank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_households"),
    )
    op.execute(
        sa.text(
            "INSERT INTO households (id, display_name, is_active) "
            "VALUES (CAST(:household_id AS uuid), 'Local household', true)"
        ).bindparams(household_id=BOOTSTRAP_HOUSEHOLD_ID)
    )

    for table_name in OWNED_TABLES:
        op.add_column(table_name, sa.Column("household_id", sa.Uuid(), nullable=True))
        op.execute(
            sa.text(
                f"UPDATE {table_name} SET household_id = CAST(:household_id AS uuid)"
            ).bindparams(household_id=BOOTSTRAP_HOUSEHOLD_ID)
        )
        op.alter_column(table_name, "household_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table_name}_household_id_households",
            table_name,
            "households",
            ["household_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(f"ix_{table_name}_household_id", table_name, ["household_id"])

    op.drop_constraint("uq_categories_name", "categories", type_="unique")
    op.create_unique_constraint(
        "uq_categories_household_name",
        "categories",
        ["household_id", "name"],
    )
    op.drop_constraint("uq_documents_sha256_size_bytes", "documents", type_="unique")
    op.create_unique_constraint(
        "uq_documents_household_sha256_size",
        "documents",
        ["household_id", "sha256", "size_bytes"],
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_login", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(normalized_login) BETWEEN 3 AND 100",
            name="ck_users_login_length",
        ),
        sa.CheckConstraint("length(password_hash) > 0", name="ck_users_password_hash_not_blank"),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name="fk_users_household_id_households",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("household_id", "normalized_login", name="uq_users_household_login"),
        sa.UniqueConstraint("id", "household_id", name="uq_users_id_household"),
    )
    op.create_index("ix_users_household_id", "users", ["household_id"])
    op.create_index("ix_users_household_active", "users", ["household_id", "is_active"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("csrf_digest", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_fingerprint", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "length(token_digest) = 64", name="ck_auth_sessions_token_digest_length"
        ),
        sa.CheckConstraint("length(csrf_digest) = 64", name="ck_auth_sessions_csrf_digest_length"),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="ck_auth_sessions_expiry_ordered",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name="fk_auth_sessions_household_id_households",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_auth_sessions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.UniqueConstraint("token_digest", name="uq_auth_sessions_token_digest"),
    )
    op.create_index("ix_auth_sessions_household_id", "auth_sessions", ["household_id"])
    op.create_index("ix_auth_sessions_household_user", "auth_sessions", ["household_id", "user_id"])
    op.create_index(
        "ix_auth_sessions_expiry", "auth_sessions", ["absolute_expires_at", "idle_expires_at"]
    )

    op.create_table(
        "security_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("auth_session_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("detail_code", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(event_type)) > 0",
            name="ck_security_audit_events_event_type_not_blank",
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'failed', 'denied')",
            name="ck_security_audit_events_outcome_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name="fk_security_audit_events_household_id_households",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_security_audit_events"),
    )
    op.create_index(
        "ix_security_audit_events_household_id", "security_audit_events", ["household_id"]
    )
    op.create_index(
        "ix_security_audit_household_created",
        "security_audit_events",
        ["household_id", "created_at"],
    )


def downgrade() -> None:
    """Remove authentication roots and the single-household ownership backfill."""
    op.drop_index("ix_security_audit_household_created", table_name="security_audit_events")
    op.drop_index("ix_security_audit_events_household_id", table_name="security_audit_events")
    op.drop_table("security_audit_events")
    op.drop_index("ix_auth_sessions_expiry", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_household_user", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_household_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_users_household_active", table_name="users")
    op.drop_index("ix_users_household_id", table_name="users")
    op.drop_table("users")

    op.drop_constraint("uq_documents_household_sha256_size", "documents", type_="unique")
    op.create_unique_constraint(
        "uq_documents_sha256_size_bytes", "documents", ["sha256", "size_bytes"]
    )
    op.drop_constraint("uq_categories_household_name", "categories", type_="unique")
    op.create_unique_constraint("uq_categories_name", "categories", ["name"])

    for table_name in reversed(OWNED_TABLES):
        op.drop_index(f"ix_{table_name}_household_id", table_name=table_name)
        op.drop_constraint(
            f"fk_{table_name}_household_id_households",
            table_name,
            type_="foreignkey",
        )
        op.drop_column(table_name, "household_id")

    op.drop_table("households")
