from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.models import Transaction


@dataclass(frozen=True)
class TransactionFilters:
    start_date: date | None = None
    end_date: date | None = None
    account_name: str | None = None
    category: str | None = None
    merchant_name: str | None = None
    import_batch_id: UUID | None = None


@dataclass(frozen=True)
class TransactionQueryResult:
    items: list[Transaction]
    total: int
    offset: int
    limit: int
    gross_amount: Decimal
    spending_amount: Decimal
    income_amount: Decimal
    net_amount: Decimal

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


def query_transactions(
    session: Session,
    *,
    filters: TransactionFilters,
    offset: int,
    limit: int,
) -> TransactionQueryResult:
    predicates: list[ColumnElement[bool]] = []

    if filters.start_date is not None:
        predicates.append(Transaction.transaction_date >= filters.start_date)
    if filters.end_date is not None:
        predicates.append(Transaction.transaction_date <= filters.end_date)
    if filters.account_name is not None:
        predicates.append(Transaction.account_name == filters.account_name)
    if filters.category is not None:
        predicates.append(Transaction.category == filters.category)
    if filters.merchant_name is not None:
        predicates.append(Transaction.merchant_name == filters.merchant_name)
    if filters.import_batch_id is not None:
        predicates.append(Transaction.import_batch_id == filters.import_batch_id)

    aggregate = session.execute(
        select(
            func.count(Transaction.id),
            func.sum(case((Transaction.amount < 0, -Transaction.amount), else_=Decimal("0.00"))),
            func.sum(case((Transaction.amount > 0, Transaction.amount), else_=Decimal("0.00"))),
            func.sum(Transaction.amount),
        ).where(*predicates)
    ).one()
    total = int(aggregate[0] or 0)
    spending_amount = _money(aggregate[1])
    income_amount = _money(aggregate[2])
    net_amount = _money(aggregate[3])
    items = list(
        session.scalars(
            select(Transaction)
            .options(selectinload(Transaction.category_assignment))
            .where(*predicates)
            .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )

    return TransactionQueryResult(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        gross_amount=spending_amount + income_amount,
        spending_amount=spending_amount,
        income_amount=income_amount,
        net_amount=net_amount,
    )


def _money(value: object) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"))
