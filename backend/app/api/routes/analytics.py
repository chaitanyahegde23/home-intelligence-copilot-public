from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.analytics import (
    CategoryBreakdownFilters,
    CategorySpendingResult,
    LargeTransactionFilters,
    LargeTransactionResult,
    PeriodComparisonFilters,
    PeriodComparisonResult,
    SpendingFilters,
    SpendingSummaryResult,
)
from app.services.analytics_tools import (
    get_category_spending_result,
    get_large_transaction_result,
    get_period_comparison_result,
    get_spending_summary_result,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/spending/summary", response_model=SpendingSummaryResult)
def get_spending_summary(
    filters: Annotated[SpendingFilters, Query()],
    session: Annotated[Session, Depends(get_db)],
) -> SpendingSummaryResult:
    return get_spending_summary_result(session, filters=filters)


@router.get("/spending/by-category", response_model=CategorySpendingResult)
def get_category_spending(
    filters: Annotated[CategoryBreakdownFilters, Query()],
    session: Annotated[Session, Depends(get_db)],
) -> CategorySpendingResult:
    return get_category_spending_result(session, filters=filters)


@router.get("/spending/compare", response_model=PeriodComparisonResult)
def compare_spending_periods(
    filters: Annotated[PeriodComparisonFilters, Query()],
    session: Annotated[Session, Depends(get_db)],
) -> PeriodComparisonResult:
    return get_period_comparison_result(session, filters=filters)


@router.get("/spending/large-transactions", response_model=LargeTransactionResult)
def get_large_transactions(
    filters: Annotated[LargeTransactionFilters, Query()],
    session: Annotated[Session, Depends(get_db)],
) -> LargeTransactionResult:
    return get_large_transaction_result(session, filters=filters)
