from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.schemas.analytics import (
    CategoryBreakdownFilters,
    CategorySpendingDelta,
    CategorySpendingGroup,
    CategorySpendingResult,
    ComparedSpendingPeriod,
    LargeTransactionFilters,
    LargeTransactionImportProvenance,
    LargeTransactionItem,
    LargeTransactionResult,
    PeriodComparisonFilters,
    PeriodComparisonResult,
    SpendingFilters,
    SpendingSummaryResult,
)
from app.services.large_transaction_query import query_large_transactions
from app.services.spending_analytics import (
    calculate_category_spending,
    calculate_period_comparison,
    calculate_spending_summary,
)


class AnalyticsToolName(StrEnum):
    GET_SPENDING_SUMMARY = "get_spending_summary"
    GET_SPENDING_BY_CATEGORY = "get_spending_by_category"
    COMPARE_SPENDING_PERIODS = "compare_spending_periods"
    LIST_LARGE_TRANSACTIONS = "list_large_transactions"


type AnalyticsToolResult = (
    SpendingSummaryResult | CategorySpendingResult | PeriodComparisonResult | LargeTransactionResult
)


@dataclass(frozen=True)
class AnalyticsToolContract:
    name: AnalyticsToolName
    description: str
    arguments_model: type[BaseModel]
    result_model: type[BaseModel]
    access: Literal["read_only"] = "read_only"

    def arguments_json_schema(self) -> dict[str, Any]:
        return self.arguments_model.model_json_schema()

    def result_json_schema(self) -> dict[str, Any]:
        return self.result_model.model_json_schema()


APPROVED_ANALYTICS_TOOLS = (
    AnalyticsToolContract(
        name=AnalyticsToolName.GET_SPENDING_SUMMARY,
        description=(
            "Return exact gross spending and the included transaction count for an explicit "
            "inclusive date range, optionally filtered by exact account and category."
        ),
        arguments_model=SpendingFilters,
        result_model=SpendingSummaryResult,
    ),
    AnalyticsToolContract(
        name=AnalyticsToolName.GET_SPENDING_BY_CATEGORY,
        description=(
            "Return an exact category breakdown that reconciles to gross spending for an "
            "explicit inclusive date range and optional exact account."
        ),
        arguments_model=CategoryBreakdownFilters,
        result_model=CategorySpendingResult,
    ),
    AnalyticsToolContract(
        name=AnalyticsToolName.COMPARE_SPENDING_PERIODS,
        description=(
            "Compare exact gross spending between two explicit inclusive date ranges and return "
            "reconciling category changes."
        ),
        arguments_model=PeriodComparisonFilters,
        result_model=PeriodComparisonResult,
    ),
    AnalyticsToolContract(
        name=AnalyticsToolName.LIST_LARGE_TRANSACTIONS,
        description=(
            "List bounded gross-spending transactions at or above an explicit Decimal threshold "
            "for an inclusive date range, with transaction and import provenance."
        ),
        arguments_model=LargeTransactionFilters,
        result_model=LargeTransactionResult,
    ),
)

ANALYTICS_TOOL_CONTRACTS: Mapping[AnalyticsToolName, AnalyticsToolContract] = MappingProxyType(
    {contract.name: contract for contract in APPROVED_ANALYTICS_TOOLS}
)


class UnsupportedAnalyticsToolError(ValueError):
    pass


def _validate_arguments[ArgumentsModelT: BaseModel](
    model: type[ArgumentsModelT], arguments: Mapping[str, object]
) -> ArgumentsModelT:
    return model.model_validate(dict(arguments))


def get_spending_summary_result(
    session: Session, *, filters: SpendingFilters
) -> SpendingSummaryResult:
    calculation = calculate_spending_summary(session, filters=filters)
    return SpendingSummaryResult(
        applied_filters=filters,
        total_spending=calculation.total_spending,
        transaction_count=calculation.transaction_count,
    )


def get_category_spending_result(
    session: Session, *, filters: CategoryBreakdownFilters
) -> CategorySpendingResult:
    calculation = calculate_category_spending(session, filters=filters)
    return CategorySpendingResult(
        applied_filters=filters,
        total_spending=calculation.total_spending,
        transaction_count=calculation.transaction_count,
        groups=[
            CategorySpendingGroup(
                category=group.category,
                bucket="uncategorized" if group.category is None else "category",
                total_spending=group.total_spending,
                transaction_count=group.transaction_count,
                percentage=group.percentage,
            )
            for group in calculation.groups
        ],
    )


def get_period_comparison_result(
    session: Session, *, filters: PeriodComparisonFilters
) -> PeriodComparisonResult:
    calculation = calculate_period_comparison(session, filters=filters)
    return PeriodComparisonResult(
        applied_filters=filters,
        current_period=ComparedSpendingPeriod(
            start_date=filters.current_start_date,
            end_date=filters.current_end_date,
            total_spending=calculation.current.total_spending,
            transaction_count=calculation.current.transaction_count,
        ),
        comparison_period=ComparedSpendingPeriod(
            start_date=filters.comparison_start_date,
            end_date=filters.comparison_end_date,
            total_spending=calculation.comparison.total_spending,
            transaction_count=calculation.comparison.transaction_count,
        ),
        absolute_change=calculation.absolute_change,
        percentage_change=calculation.percentage_change,
        category_deltas=[
            CategorySpendingDelta(
                category=delta.category,
                bucket="uncategorized" if delta.category is None else "category",
                current_spending=delta.current_spending,
                comparison_spending=delta.comparison_spending,
                absolute_change=delta.absolute_change,
                current_transaction_count=delta.current_transaction_count,
                comparison_transaction_count=delta.comparison_transaction_count,
                transaction_count_change=delta.transaction_count_change,
            )
            for delta in calculation.category_deltas
        ],
    )


def get_large_transaction_result(
    session: Session, *, filters: LargeTransactionFilters
) -> LargeTransactionResult:
    result = query_large_transactions(session, filters=filters)
    return LargeTransactionResult(
        applied_filters=filters,
        total_matching=result.total_matching,
        returned_count=len(result.items),
        has_more=result.has_more,
        items=[
            LargeTransactionItem(
                id=transaction.id,
                import_batch_id=transaction.import_batch_id,
                account_name=transaction.account_name,
                transaction_date=transaction.transaction_date,
                posted_date=transaction.posted_date,
                description=transaction.description,
                merchant_name=transaction.merchant_name,
                amount=transaction.amount,
                transaction_type=transaction.transaction_type,
                category=transaction.category,
                source_file=transaction.source_file,
                created_at=transaction.created_at,
                updated_at=transaction.updated_at,
                spending_magnitude=-transaction.amount,
                import_provenance=LargeTransactionImportProvenance(
                    import_batch_id=transaction.import_batch.id,
                    filename=transaction.import_batch.filename,
                    adapter_name=transaction.import_batch.adapter_name,
                    adapter_version=transaction.import_batch.adapter_version,
                    account_label=transaction.import_batch.account_label,
                ),
            )
            for transaction in result.items
        ],
    )


def _execute_spending_summary(
    session: Session, arguments: Mapping[str, object]
) -> AnalyticsToolResult:
    return get_spending_summary_result(
        session,
        filters=_validate_arguments(SpendingFilters, arguments),
    )


def _execute_category_spending(
    session: Session, arguments: Mapping[str, object]
) -> AnalyticsToolResult:
    return get_category_spending_result(
        session,
        filters=_validate_arguments(CategoryBreakdownFilters, arguments),
    )


def _execute_period_comparison(
    session: Session, arguments: Mapping[str, object]
) -> AnalyticsToolResult:
    return get_period_comparison_result(
        session,
        filters=_validate_arguments(PeriodComparisonFilters, arguments),
    )


def _execute_large_transactions(
    session: Session, arguments: Mapping[str, object]
) -> AnalyticsToolResult:
    return get_large_transaction_result(
        session,
        filters=_validate_arguments(LargeTransactionFilters, arguments),
    )


type ToolExecutor = Callable[[Session, Mapping[str, object]], AnalyticsToolResult]

_TOOL_EXECUTORS: Mapping[AnalyticsToolName, ToolExecutor] = MappingProxyType(
    {
        AnalyticsToolName.GET_SPENDING_SUMMARY: _execute_spending_summary,
        AnalyticsToolName.GET_SPENDING_BY_CATEGORY: _execute_category_spending,
        AnalyticsToolName.COMPARE_SPENDING_PERIODS: _execute_period_comparison,
        AnalyticsToolName.LIST_LARGE_TRANSACTIONS: _execute_large_transactions,
    }
)


def execute_analytics_tool(
    session: Session,
    *,
    tool_name: str | AnalyticsToolName,
    arguments: Mapping[str, object],
) -> AnalyticsToolResult:
    try:
        approved_name = AnalyticsToolName(tool_name)
    except ValueError as exc:
        raise UnsupportedAnalyticsToolError(f"unsupported analytics tool: {tool_name}") from exc

    return _TOOL_EXECUTORS[approved_name](session, arguments)
