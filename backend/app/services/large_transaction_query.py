from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql.elements import ColumnElement

from app.models import Transaction
from app.schemas.analytics import LargeTransactionFilters


@dataclass(frozen=True)
class LargeTransactionQueryResult:
    items: tuple[Transaction, ...]
    total_matching: int
    limit: int

    @property
    def has_more(self) -> bool:
        return self.total_matching > len(self.items)


def query_large_transactions(
    session: Session,
    *,
    filters: LargeTransactionFilters,
) -> LargeTransactionQueryResult:
    predicates: list[ColumnElement[bool]] = [
        Transaction.amount < Decimal("0.00"),
        -Transaction.amount >= filters.threshold,
        Transaction.transaction_date >= filters.start_date,
        Transaction.transaction_date <= filters.end_date,
    ]
    if filters.account_name is not None:
        predicates.append(Transaction.account_name == filters.account_name)
    if filters.category is not None:
        predicates.append(Transaction.category == filters.category)

    total_matching = (
        session.scalar(select(func.count()).select_from(Transaction).where(*predicates)) or 0
    )
    items = tuple(
        session.scalars(
            select(Transaction)
            .options(joinedload(Transaction.import_batch))
            .where(*predicates)
            .order_by(
                (-Transaction.amount).desc(),
                Transaction.transaction_date.desc(),
                Transaction.id.desc(),
            )
            .limit(filters.limit)
        )
    )

    return LargeTransactionQueryResult(
        items=items,
        total_matching=total_matching,
        limit=filters.limit,
    )
