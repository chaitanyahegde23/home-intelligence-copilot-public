from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import (
    DuplicateCandidate,
    DuplicateStatus,
    ImportBatch,
    Transaction,
)
from app.schemas import (
    DuplicateCandidateCreate,
    DuplicateCandidateRead,
    DuplicateCandidateReview,
)

FINGERPRINT = "a" * 64


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session
    engine.dispose()


def make_transactions(session: Session) -> tuple[Transaction, Transaction]:
    batch = ImportBatch(filename="synthetic-duplicate-candidates.csv")
    first = Transaction(
        id=UUID(int=1),
        import_batch=batch,
        transaction_date=date(2026, 8, 1),
        description="Synthetic first transaction",
        amount=Decimal("-42.15"),
        source_file=batch.filename,
    )
    second = Transaction(
        id=UUID(int=2),
        import_batch=batch,
        transaction_date=date(2026, 8, 1),
        description="Synthetic second transaction",
        amount=Decimal("-42.15"),
        source_file=batch.filename,
    )
    session.add_all([first, second])
    session.flush()
    return first, second


def make_candidate(first: Transaction, second: Transaction) -> DuplicateCandidate:
    return DuplicateCandidate(
        first_transaction=first,
        second_transaction=second,
        fingerprint=FINGERPRINT,
        reason="exact_normalized_fingerprint",
    )


def test_create_unresolved_candidate_with_relationships_and_timestamps(
    session: Session,
) -> None:
    first, second = make_transactions(session)
    candidate = make_candidate(first, second)
    session.add(candidate)
    session.flush()

    stored = session.scalar(select(DuplicateCandidate).where(DuplicateCandidate.id == candidate.id))

    assert stored is candidate
    assert candidate.status is DuplicateStatus.UNRESOLVED
    assert candidate.resolved_at is None
    assert candidate in first.duplicate_candidates_as_first
    assert candidate in second.duplicate_candidates_as_second
    assert candidate.first_transaction.import_batch is second.import_batch
    assert candidate.created_at.tzinfo is not None
    assert candidate.updated_at.tzinfo is not None


def test_resolved_status_requires_timestamp(session: Session) -> None:
    first, second = make_transactions(session)
    candidate = make_candidate(first, second)
    candidate.status = DuplicateStatus.CONFIRMED
    session.add(candidate)

    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_confirmed_and_dismissed_candidates_are_supported(session: Session) -> None:
    first, second = make_transactions(session)
    resolved_at = datetime.now(UTC)
    confirmed = make_candidate(first, second)
    confirmed.status = DuplicateStatus.CONFIRMED
    confirmed.resolved_at = resolved_at
    confirmed.resolution_note = "Confirmed using synthetic source evidence"
    session.add(confirmed)
    session.flush()

    assert confirmed.status is DuplicateStatus.CONFIRMED
    assert confirmed.resolved_at == resolved_at

    session.delete(confirmed)
    session.flush()
    dismissed = make_candidate(first, second)
    dismissed.status = DuplicateStatus.DISMISSED
    dismissed.resolved_at = resolved_at
    session.add(dismissed)
    session.flush()

    assert dismissed.status is DuplicateStatus.DISMISSED


@pytest.mark.parametrize(
    ("first_id", "second_id"),
    [(UUID(int=1), UUID(int=1)), (UUID(int=2), UUID(int=1))],
)
def test_database_rejects_self_or_reversed_pairs(
    session: Session, first_id: UUID, second_id: UUID
) -> None:
    first, second = make_transactions(session)
    session.add(
        DuplicateCandidate(
            first_transaction_id=first_id,
            second_transaction_id=second_id,
            fingerprint=FINGERPRINT,
            reason="exact_normalized_fingerprint",
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    assert first.id == UUID(int=1)
    assert second.id == UUID(int=2)


def test_database_rejects_duplicate_pair(session: Session) -> None:
    first, second = make_transactions(session)
    session.add(make_candidate(first, second))
    session.flush()
    session.add(make_candidate(first, second))

    with pytest.raises(IntegrityError):
        session.flush()


def test_create_schema_normalizes_reason_and_serializes_model(session: Session) -> None:
    first, second = make_transactions(session)
    candidate = make_candidate(first, second)
    session.add(candidate)
    session.flush()

    create = DuplicateCandidateCreate(
        first_transaction_id=first.id,
        second_transaction_id=second.id,
        fingerprint=FINGERPRINT,
        reason="  exact_normalized_fingerprint  ",
    )
    read = DuplicateCandidateRead.model_validate(candidate)

    assert create.reason == "exact_normalized_fingerprint"
    assert read.id == candidate.id
    assert read.status is DuplicateStatus.UNRESOLVED
    assert read.resolved_at is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "first_transaction_id": UUID(int=1),
            "second_transaction_id": UUID(int=1),
            "fingerprint": FINGERPRINT,
            "reason": "exact",
        },
        {
            "first_transaction_id": UUID(int=2),
            "second_transaction_id": UUID(int=1),
            "fingerprint": FINGERPRINT,
            "reason": "exact",
        },
        {
            "first_transaction_id": UUID(int=1),
            "second_transaction_id": UUID(int=2),
            "fingerprint": "A" * 64,
            "reason": "exact",
        },
        {
            "first_transaction_id": UUID(int=1),
            "second_transaction_id": UUID(int=2),
            "fingerprint": "a" * 63,
            "reason": "exact",
        },
        {
            "first_transaction_id": UUID(int=1),
            "second_transaction_id": UUID(int=2),
            "fingerprint": FINGERPRINT,
            "reason": "   ",
        },
    ],
)
def test_create_schema_rejects_invalid_pairs_fingerprints_and_reasons(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        DuplicateCandidateCreate.model_validate(payload)


@pytest.mark.parametrize("status", [DuplicateStatus.CONFIRMED, DuplicateStatus.DISMISSED])
def test_review_schema_accepts_only_resolution_statuses(
    status: Literal[DuplicateStatus.CONFIRMED, DuplicateStatus.DISMISSED],
) -> None:
    review = DuplicateCandidateReview(
        status=status,
        resolution_note="  Reviewed using synthetic evidence  ",
    )

    assert review.status is status
    assert review.resolution_note == "Reviewed using synthetic evidence"


def test_review_schema_rejects_unresolved_status() -> None:
    with pytest.raises(ValidationError):
        DuplicateCandidateReview.model_validate({"status": "unresolved"})
