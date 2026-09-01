from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import Transaction
from app.schemas.analytics import (
    CategoryBreakdownFilters,
    PeriodComparisonFilters,
    SpendingFilters,
)

PERCENTAGE_QUANTUM = Decimal("0.01")
ONE_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class SpendingSummaryCalculation:
    total_spending: Decimal
    transaction_count: int


@dataclass(frozen=True)
class CategorySpendingGroupCalculation:
    category: str | None
    total_spending: Decimal
    transaction_count: int
    percentage: Decimal


@dataclass(frozen=True)
class CategorySpendingCalculation:
    total_spending: Decimal
    transaction_count: int
    groups: tuple[CategorySpendingGroupCalculation, ...]


@dataclass(frozen=True)
class CategorySpendingDeltaCalculation:
    category: str | None
    current_spending: Decimal
    comparison_spending: Decimal
    absolute_change: Decimal
    current_transaction_count: int
    comparison_transaction_count: int
    transaction_count_change: int


@dataclass(frozen=True)
class PeriodComparisonCalculation:
    current: CategorySpendingCalculation
    comparison: CategorySpendingCalculation
    absolute_change: Decimal
    percentage_change: Decimal | None
    category_deltas: tuple[CategorySpendingDeltaCalculation, ...]


def _spending_predicates(
    filters: SpendingFilters | CategoryBreakdownFilters,
) -> list[ColumnElement[bool]]:
    predicates: list[ColumnElement[bool]] = [
        Transaction.amount < Decimal("0.00"),
        Transaction.transaction_date >= filters.start_date,
        Transaction.transaction_date <= filters.end_date,
    ]
    if filters.account_name is not None:
        predicates.append(Transaction.account_name == filters.account_name)
    return predicates


def calculate_spending_summary(
    session: Session,
    *,
    filters: SpendingFilters,
) -> SpendingSummaryCalculation:
    predicates = _spending_predicates(filters)
    if filters.category is not None:
        predicates.append(Transaction.category == filters.category)

    total_spending, transaction_count = session.execute(
        select(
            func.coalesce(func.sum(-Transaction.amount), Decimal("0.00")),
            func.count(Transaction.id),
        ).where(*predicates)
    ).one()

    return SpendingSummaryCalculation(
        total_spending=cast(Decimal, total_spending),
        transaction_count=cast(int, transaction_count),
    )


def calculate_category_spending(
    session: Session,
    *,
    filters: CategoryBreakdownFilters,
) -> CategorySpendingCalculation:
    rows = session.execute(
        select(
            Transaction.category,
            func.sum(-Transaction.amount),
            func.count(Transaction.id),
        )
        .where(*_spending_predicates(filters))
        .group_by(Transaction.category)
    ).all()

    grouped_values = [
        (
            cast(str | None, category),
            cast(Decimal, total_spending),
            cast(int, transaction_count),
        )
        for category, total_spending, transaction_count in rows
    ]
    grouped_values.sort(
        key=lambda group: (
            -group[1],
            group[0] is None,
            group[0] or "",
        )
    )

    total_spending = sum(
        (group[1] for group in grouped_values),
        Decimal("0.00"),
    )
    transaction_count = sum(group[2] for group in grouped_values)
    groups = tuple(
        CategorySpendingGroupCalculation(
            category=category,
            total_spending=group_total,
            transaction_count=group_count,
            percentage=((group_total / total_spending) * ONE_HUNDRED).quantize(
                PERCENTAGE_QUANTUM, rounding=ROUND_HALF_UP
            ),
        )
        for category, group_total, group_count in grouped_values
    )

    return CategorySpendingCalculation(
        total_spending=total_spending,
        transaction_count=transaction_count,
        groups=groups,
    )


def calculate_period_comparison(
    session: Session,
    *,
    filters: PeriodComparisonFilters,
) -> PeriodComparisonCalculation:
    current = calculate_category_spending(
        session,
        filters=CategoryBreakdownFilters(
            start_date=filters.current_start_date,
            end_date=filters.current_end_date,
            account_name=filters.account_name,
        ),
    )
    comparison = calculate_category_spending(
        session,
        filters=CategoryBreakdownFilters(
            start_date=filters.comparison_start_date,
            end_date=filters.comparison_end_date,
            account_name=filters.account_name,
        ),
    )

    current_by_category = {group.category: group for group in current.groups}
    comparison_by_category = {group.category: group for group in comparison.groups}
    category_deltas = []
    for category in current_by_category.keys() | comparison_by_category.keys():
        current_group = current_by_category.get(category)
        comparison_group = comparison_by_category.get(category)
        current_spending = (
            current_group.total_spending if current_group is not None else Decimal("0.00")
        )
        comparison_spending = (
            comparison_group.total_spending if comparison_group is not None else Decimal("0.00")
        )
        current_count = current_group.transaction_count if current_group is not None else 0
        comparison_count = comparison_group.transaction_count if comparison_group is not None else 0
        category_deltas.append(
            CategorySpendingDeltaCalculation(
                category=category,
                current_spending=current_spending,
                comparison_spending=comparison_spending,
                absolute_change=current_spending - comparison_spending,
                current_transaction_count=current_count,
                comparison_transaction_count=comparison_count,
                transaction_count_change=current_count - comparison_count,
            )
        )

    category_deltas.sort(
        key=lambda delta: (
            -abs(delta.absolute_change),
            delta.category is None,
            delta.category or "",
        )
    )
    absolute_change = current.total_spending - comparison.total_spending
    percentage_change = (
        None
        if comparison.total_spending == Decimal("0.00")
        else ((absolute_change / comparison.total_spending) * ONE_HUNDRED).quantize(
            PERCENTAGE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
    )

    return PeriodComparisonCalculation(
        current=current,
        comparison=comparison,
        absolute_change=absolute_change,
        percentage_change=percentage_change,
        category_deltas=tuple(category_deltas),
    )
