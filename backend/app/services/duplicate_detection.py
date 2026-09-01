"""Deterministic exact duplicate detection for normalized transactions."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import DuplicateCandidate, Transaction

FINGERPRINT_REASON = "exact_normalized_transaction_v1"
POSTGRES_IMPORT_ADVISORY_LOCK_ID = 0x4849434455504C31
ZERO_AMOUNT = Decimal("0.00")

type FingerprintIdentity = tuple[
    date,
    date | None,
    str,
    Decimal,
    str | None,
    str | None,
    str | None,
    str | None,
]


class FingerprintableTransaction(Protocol):
    transaction_date: date
    posted_date: date | None
    description: str
    amount: Decimal
    account_name: str | None
    merchant_name: str | None
    transaction_type: str | None
    category: str | None


def normalized_identity(record: FingerprintableTransaction) -> FingerprintIdentity:
    """Return the exact normalized fields that define duplicate identity version 1."""
    return (
        record.transaction_date,
        record.posted_date,
        record.description,
        record.amount,
        record.account_name,
        record.merchant_name,
        record.transaction_type,
        record.category,
    )


def fingerprint_identity(identity: FingerprintIdentity) -> str:
    """Create a stable SHA-256 digest without ambiguous field concatenation."""
    (
        transaction_date,
        posted_date,
        description,
        amount,
        account_name,
        merchant_name,
        transaction_type,
        category,
    ) = identity
    payload = json.dumps(
        [
            FINGERPRINT_REASON,
            transaction_date.isoformat(),
            posted_date.isoformat() if posted_date is not None else None,
            description,
            format(ZERO_AMOUNT if amount == 0 else amount, ".2f"),
            account_name,
            merchant_name,
            transaction_type,
            category,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_transaction(record: FingerprintableTransaction) -> str:
    return fingerprint_identity(normalized_identity(record))


def acquire_import_detection_lock(session: Session) -> None:
    """Serialize PostgreSQL imports so concurrent uploads cannot miss one another."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": POSTGRES_IMPORT_ADVISORY_LOCK_ID},
        )


def load_possible_matches(
    session: Session,
    records: Iterable[FingerprintableTransaction],
) -> list[Transaction]:
    """Prefetch the bounded transaction-date window needed for exact comparison."""
    dates = [record.transaction_date for record in records]
    if not dates:
        return []
    return list(
        session.scalars(
            select(Transaction)
            .where(
                Transaction.transaction_date >= min(dates),
                Transaction.transaction_date <= max(dates),
            )
            .order_by(Transaction.created_at, Transaction.id)
        )
    )


def build_duplicate_candidates(
    *,
    new_transactions: list[Transaction],
    existing_transactions: Iterable[Transaction],
) -> list[DuplicateCandidate]:
    """Link each duplicate row to one deterministic canonical representative."""
    matches_by_identity: dict[FingerprintIdentity, list[Transaction]] = defaultdict(list)
    for transaction in existing_transactions:
        matches_by_identity[normalized_identity(transaction)].append(transaction)

    candidates: list[DuplicateCandidate] = []
    for transaction in new_transactions:
        identity = normalized_identity(transaction)
        matches = matches_by_identity[identity]
        if not matches:
            continue
        match = matches[0]
        first_id, second_id = canonical_pair(match.id, transaction.id)
        candidates.append(
            DuplicateCandidate(
                first_transaction_id=first_id,
                second_transaction_id=second_id,
                fingerprint=fingerprint_identity(identity),
                reason=FINGERPRINT_REASON,
            )
        )
    return candidates


def canonical_pair(first_id: UUID, second_id: UUID) -> tuple[UUID, UUID]:
    if first_id == second_id:
        raise ValueError("A duplicate candidate requires two distinct transactions")
    return min(first_id, second_id), max(first_id, second_id)
