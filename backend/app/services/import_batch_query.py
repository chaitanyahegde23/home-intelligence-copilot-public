from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import DuplicateCandidate, ImportBatch, Transaction
from app.models.import_batch import ImportStatus


@dataclass(frozen=True)
class ImportBatchQueryResult:
    items: list[ImportBatch]
    total: int
    offset: int
    limit: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


@dataclass(frozen=True)
class ImportBatchDetailResult:
    batch: ImportBatch
    transaction_count: int
    duplicate_candidate_count: int


def query_import_batches(
    session: Session,
    *,
    status: ImportStatus | None,
    offset: int,
    limit: int,
) -> ImportBatchQueryResult:
    count_statement = select(func.count()).select_from(ImportBatch)
    query_statement = select(ImportBatch)

    if status is not None:
        count_statement = count_statement.where(ImportBatch.status == status)
        query_statement = query_statement.where(ImportBatch.status == status)

    total = session.scalar(count_statement) or 0
    items = list(
        session.scalars(
            query_statement.order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )

    return ImportBatchQueryResult(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


def get_import_batch_detail(
    session: Session,
    *,
    batch_id: UUID,
) -> ImportBatchDetailResult | None:
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        return None

    transaction_count = (
        session.scalar(
            select(func.count(Transaction.id)).where(Transaction.import_batch_id == batch_id)
        )
        or 0
    )
    duplicate_candidate_count = (
        session.scalar(
            select(func.count())
            .select_from(DuplicateCandidate)
            .where(
                or_(
                    DuplicateCandidate.first_transaction.has(
                        Transaction.import_batch_id == batch_id
                    ),
                    DuplicateCandidate.second_transaction.has(
                        Transaction.import_batch_id == batch_id
                    ),
                )
            )
        )
        or 0
    )
    return ImportBatchDetailResult(
        batch=batch,
        transaction_count=transaction_count,
        duplicate_candidate_count=duplicate_candidate_count,
    )
