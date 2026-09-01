from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.interfaces import ORMOption
from sqlalchemy.sql.elements import ColumnElement

from app.models import DuplicateCandidate, DuplicateStatus, Transaction


@dataclass(frozen=True)
class DuplicateCandidateFilters:
    status: DuplicateStatus | None = None
    import_batch_id: UUID | None = None


@dataclass(frozen=True)
class DuplicateCandidateQueryResult:
    items: list[DuplicateCandidate]
    total: int
    offset: int
    limit: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


def candidate_load_options() -> tuple[ORMOption, ORMOption]:
    return (
        selectinload(DuplicateCandidate.first_transaction).selectinload(Transaction.import_batch),
        selectinload(DuplicateCandidate.second_transaction).selectinload(Transaction.import_batch),
    )


def query_duplicate_candidates(
    session: Session,
    *,
    filters: DuplicateCandidateFilters,
    offset: int,
    limit: int,
) -> DuplicateCandidateQueryResult:
    predicates = candidate_predicates(filters)
    total = (
        session.scalar(select(func.count()).select_from(DuplicateCandidate).where(*predicates)) or 0
    )
    items = list(
        session.scalars(
            select(DuplicateCandidate)
            .options(*candidate_load_options())
            .where(*predicates)
            .order_by(DuplicateCandidate.created_at.desc(), DuplicateCandidate.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return DuplicateCandidateQueryResult(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


def get_duplicate_candidate(
    session: Session,
    *,
    candidate_id: UUID,
) -> DuplicateCandidate | None:
    return session.scalar(
        select(DuplicateCandidate)
        .options(*candidate_load_options())
        .where(DuplicateCandidate.id == candidate_id)
    )


def review_duplicate_candidate(
    session: Session,
    *,
    candidate_id: UUID,
    status: DuplicateStatus,
    resolution_note: str | None,
) -> DuplicateCandidate | None:
    if status is DuplicateStatus.UNRESOLVED:
        raise ValueError("Review status must be confirmed or dismissed")
    with session.begin():
        candidate = session.scalar(
            select(DuplicateCandidate)
            .options(*candidate_load_options())
            .where(DuplicateCandidate.id == candidate_id)
            .with_for_update()
        )
        if candidate is None:
            return None
        candidate.status = status
        candidate.resolution_note = resolution_note
        candidate.resolved_at = datetime.now(UTC)
        session.flush()
    return candidate


def candidate_predicates(
    filters: DuplicateCandidateFilters,
) -> list[ColumnElement[bool]]:
    predicates: list[ColumnElement[bool]] = []
    if filters.status is not None:
        predicates.append(DuplicateCandidate.status == filters.status)
    if filters.import_batch_id is not None:
        predicates.append(
            or_(
                DuplicateCandidate.first_transaction.has(
                    Transaction.import_batch_id == filters.import_batch_id
                ),
                DuplicateCandidate.second_transaction.has(
                    Transaction.import_batch_id == filters.import_batch_id
                ),
            )
        )
    return predicates
