from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.household import BOOTSTRAP_HOUSEHOLD_ID
from app.db.base import Base
from app.db.household_scope import SESSION_HOUSEHOLD_KEY, HouseholdScopeViolation
from app.models import (
    AuthSession,
    CategorizationRule,
    Category,
    Document,
    DocumentChunk,
    DocumentDeletionAudit,
    DocumentExtraction,
    DocumentTextSpan,
    DuplicateCandidate,
    Household,
    ImportBatch,
    SecurityAuditEvent,
    Transaction,
    TransactionCategoryAssignment,
    User,
)
from app.models.mixins import HouseholdOwnedMixin
from app.services.import_batch_management import delete_import_batch

HOUSEHOLD_MODELS = (
    User,
    AuthSession,
    SecurityAuditEvent,
    ImportBatch,
    Transaction,
    Category,
    CategorizationRule,
    TransactionCategoryAssignment,
    DuplicateCandidate,
    Document,
    DocumentDeletionAudit,
    DocumentExtraction,
    DocumentTextSpan,
    DocumentChunk,
)


def _batch(household_id: object, suffix: str) -> ImportBatch:
    batch = ImportBatch(household_id=household_id, filename=f"{suffix}.csv")
    batch.transactions.append(
        Transaction(
            household_id=household_id,
            transaction_date=date(2026, 6, 1),
            description=f"Synthetic {suffix}",
            amount=Decimal("10.00"),
            source_file=f"{suffix}.csv",
        )
    )
    return batch


def test_every_sensitive_model_declares_non_nullable_household_ownership() -> None:
    for model in HOUSEHOLD_MODELS:
        assert issubclass(model, HouseholdOwnedMixin)
        column = model.__table__.c.household_id
        assert column.nullable is False
        assert column.foreign_keys


def test_queries_and_writes_are_isolated_by_household() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    other_household_id = uuid4()

    with Session(engine) as session:
        session.add(Household(id=other_household_id, display_name="Other synthetic household"))
        session.commit()

        session.info[SESSION_HOUSEHOLD_KEY] = BOOTSTRAP_HOUSEHOLD_ID
        session.add_all(
            [
                _batch(BOOTSTRAP_HOUSEHOLD_ID, "first"),
                Category(household_id=BOOTSTRAP_HOUSEHOLD_ID, name="Shared name"),
                Document(
                    household_id=BOOTSTRAP_HOUSEHOLD_ID,
                    original_filename="first.pdf",
                    size_bytes=1,
                    sha256="a" * 64,
                    storage_key="first.pdf",
                ),
            ]
        )
        session.commit()

        session.info[SESSION_HOUSEHOLD_KEY] = other_household_id
        session.add_all(
            [
                _batch(other_household_id, "second"),
                Category(household_id=other_household_id, name="Shared name"),
                Document(
                    household_id=other_household_id,
                    original_filename="second.pdf",
                    size_bytes=1,
                    sha256="a" * 64,
                    storage_key="second.pdf",
                ),
            ]
        )
        session.commit()

        for household_id, expected_filename in (
            (BOOTSTRAP_HOUSEHOLD_ID, "first.csv"),
            (other_household_id, "second.csv"),
        ):
            session.info[SESSION_HOUSEHOLD_KEY] = household_id
            assert session.scalars(select(ImportBatch)).one().filename == expected_filename
            assert session.scalars(select(Transaction)).one().source_file == expected_filename
            assert len(session.scalars(select(Category)).all()) == 1
            assert len(session.scalars(select(Document)).all()) == 1
        other_batch_id = session.scalar(
            select(ImportBatch.id).where(ImportBatch.filename == "second.csv")
        )
        assert other_batch_id is not None
        session.info[SESSION_HOUSEHOLD_KEY] = BOOTSTRAP_HOUSEHOLD_ID
        session.add(
            Transaction(
                import_batch_id=other_batch_id,
                transaction_date=date(2026, 6, 2),
                description="Cross tenant relationship",
                amount=Decimal("1.00"),
                source_file="blocked.csv",
            )
        )
        with pytest.raises(HouseholdScopeViolation, match="cross-household relationship denied"):
            session.flush()
        session.rollback()

        session.info[SESSION_HOUSEHOLD_KEY] = BOOTSTRAP_HOUSEHOLD_ID
        session.add(Category(household_id=other_household_id, name="Cross tenant write"))
        with pytest.raises(HouseholdScopeViolation, match="cross-household write denied"):
            session.flush()
        session.rollback()

        session.info[SESSION_HOUSEHOLD_KEY] = BOOTSTRAP_HOUSEHOLD_ID
        assert delete_import_batch(session, batch_id=other_batch_id) is False
        session.info[SESSION_HOUSEHOLD_KEY] = other_household_id
        assert session.get(ImportBatch, other_batch_id) is not None

    engine.dispose()
