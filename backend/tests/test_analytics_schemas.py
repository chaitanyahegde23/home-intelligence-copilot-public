from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.analytics import (
    CategoryBreakdownFilters,
    CategorySpendingGroup,
    CategorySpendingResult,
    SpendingFilters,
    SpendingSummaryResult,
)


def test_spending_filters_accept_inclusive_single_day_range_and_normalize_text() -> None:
    filters = SpendingFilters(
        start_date=date(2026, 1, 3),
        end_date=date(2026, 1, 3),
        account_name="  Sample Checking  ",
        category="  Groceries  ",
    )

    assert filters.start_date == filters.end_date
    assert filters.account_name == "Sample Checking"
    assert filters.category == "Groceries"


def test_spending_filters_reject_reversed_date_range() -> None:
    with pytest.raises(ValidationError, match="start_date must be on or before end_date"):
        SpendingFilters(start_date=date(2026, 1, 4), end_date=date(2026, 1, 3))


@pytest.mark.parametrize("field", ["account_name", "category"])
def test_spending_filters_reject_blank_exact_match_filter(field: str) -> None:
    with pytest.raises(ValidationError):
        SpendingFilters(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            **{field: "   "},
        )


def test_spending_filters_reject_unexpected_fields() -> None:
    with pytest.raises(ValidationError):
        SpendingFilters.model_validate(
            {
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "merchant_name": "Synthetic Merchant",
            }
        )


def test_spending_summary_serializes_decimal_as_exact_string() -> None:
    result = SpendingSummaryResult(
        applied_filters=SpendingFilters(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        ),
        total_spending=Decimal("1782.45"),
        transaction_count=3,
    )

    assert result.model_dump(mode="json") == {
        "semantics_version": "1.0",
        "metric": "gross_spending",
        "currency": "USD",
        "applied_filters": {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "account_name": None,
            "category": None,
        },
        "total_spending": "1782.45",
        "transaction_count": 3,
    }


def test_spending_summary_rejects_float_money() -> None:
    with pytest.raises(ValidationError, match="must use Decimal, not float"):
        SpendingSummaryResult.model_validate(
            {
                "applied_filters": {
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-31",
                },
                "total_spending": 1.23,
                "transaction_count": 1,
            }
        )


@pytest.mark.parametrize(
    ("total_spending", "transaction_count"),
    [
        (Decimal("-0.01"), 1),
        (Decimal("1.001"), 1),
        (Decimal("1.00"), -1),
    ],
)
def test_spending_summary_rejects_invalid_result_invariants(
    total_spending: Decimal,
    transaction_count: int,
) -> None:
    with pytest.raises(ValidationError):
        SpendingSummaryResult(
            applied_filters=SpendingFilters(
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
            ),
            total_spending=total_spending,
            transaction_count=transaction_count,
        )


def test_spending_summary_contract_rejects_other_currency_or_metric() -> None:
    base = {
        "applied_filters": {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        },
        "total_spending": Decimal("1.00"),
        "transaction_count": 1,
    }

    with pytest.raises(ValidationError):
        SpendingSummaryResult.model_validate({**base, "currency": "EUR"})
    with pytest.raises(ValidationError):
        SpendingSummaryResult.model_validate({**base, "metric": "net_spending"})


def test_normative_document_matches_versioned_summary_contract() -> None:
    document = (Path(__file__).parents[2] / "docs" / "ANALYTICS_SEMANTICS.md").read_text(
        encoding="utf-8"
    )

    for required_rule in (
        "semantics version `1.0`",
        "metric name `gross_spending`",
        'currency: "USD"',
        "Positive and zero amounts do not contribute",
        "Both boundaries are inclusive",
    ):
        assert required_rule in document


def make_category_result() -> CategorySpendingResult:
    return CategorySpendingResult(
        applied_filters=CategoryBreakdownFilters(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        ),
        total_spending=Decimal("10.00"),
        transaction_count=1,
        groups=[
            CategorySpendingGroup(
                category=None,
                bucket="uncategorized",
                total_spending=Decimal("10.00"),
                transaction_count=1,
                percentage=Decimal("100.00"),
            )
        ],
    )


def test_category_result_serializes_decimal_values_as_exact_strings() -> None:
    result = make_category_result()

    assert result.model_dump(mode="json") == {
        "semantics_version": "1.0",
        "metric": "gross_spending_by_category",
        "currency": "USD",
        "applied_filters": {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "account_name": None,
        },
        "total_spending": "10.00",
        "transaction_count": 1,
        "groups": [
            {
                "category": None,
                "bucket": "uncategorized",
                "total_spending": "10.00",
                "transaction_count": 1,
                "percentage": "100.00",
            }
        ],
    }


@pytest.mark.parametrize(
    ("category", "bucket"),
    [
        (None, "category"),
        ("Uncategorized", "uncategorized"),
    ],
)
def test_category_group_rejects_inconsistent_bucket(
    category: str | None,
    bucket: str,
) -> None:
    with pytest.raises(ValidationError):
        CategorySpendingGroup.model_validate(
            {
                "category": category,
                "bucket": bucket,
                "total_spending": Decimal("1.00"),
                "transaction_count": 1,
                "percentage": Decimal("100.00"),
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("total_spending", 1.0),
        ("percentage", 100.0),
    ],
)
def test_category_group_rejects_float_decimals(field: str, value: float) -> None:
    group = {
        "category": "Synthetic",
        "bucket": "category",
        "total_spending": Decimal("1.00"),
        "transaction_count": 1,
        "percentage": Decimal("100.00"),
    }
    group[field] = value

    with pytest.raises(ValidationError, match="must use Decimal, not float"):
        CategorySpendingGroup.model_validate(group)


@pytest.mark.parametrize(
    ("total_spending", "transaction_count"),
    [
        (Decimal("9.99"), 1),
        (Decimal("10.00"), 2),
    ],
)
def test_category_result_rejects_non_reconciling_totals_or_counts(
    total_spending: Decimal,
    transaction_count: int,
) -> None:
    result = make_category_result().model_dump()
    result["total_spending"] = total_spending
    result["transaction_count"] = transaction_count

    with pytest.raises(ValidationError, match="must reconcile"):
        CategorySpendingResult.model_validate(result)
