from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.schemas.import_adapter import AccountLabel, AdapterName, AdapterVersion
from app.schemas.transaction import TransactionRead

FilterText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
NonNegativeMoney = Annotated[
    Decimal,
    Field(ge=0, max_digits=18, decimal_places=2),
]
PositiveMoney = Annotated[
    Decimal,
    Field(gt=0, max_digits=18, decimal_places=2),
]
NonNegativeCount = Annotated[int, Field(ge=0)]
PositiveCount = Annotated[int, Field(gt=0)]
Percentage = Annotated[
    Decimal,
    Field(ge=0, le=100, max_digits=5, decimal_places=2),
]
SignedMoney = Annotated[
    Decimal,
    Field(max_digits=18, decimal_places=2),
]
SignedPercentage = Annotated[
    Decimal,
    Field(max_digits=18, decimal_places=2),
]


class DateRangeAccountFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    account_name: FilterText | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class SpendingFilters(DateRangeAccountFilters):
    category: FilterText | None = None


class CategoryBreakdownFilters(DateRangeAccountFilters):
    pass


class LargeTransactionFilters(SpendingFilters):
    threshold: PositiveMoney
    limit: Annotated[int, Field(ge=1, le=100)] = 50

    @field_validator("threshold", mode="before")
    @classmethod
    def reject_floating_point_threshold(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("monetary values must use Decimal, not float")
        return value


class PeriodComparisonFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_start_date: date
    current_end_date: date
    comparison_start_date: date
    comparison_end_date: date
    account_name: FilterText | None = None

    @model_validator(mode="after")
    def validate_date_ranges(self) -> Self:
        if self.current_start_date > self.current_end_date:
            raise ValueError("current_start_date must be on or before current_end_date")
        if self.comparison_start_date > self.comparison_end_date:
            raise ValueError("comparison_start_date must be on or before comparison_end_date")
        return self


class SpendingSummaryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantics_version: Literal["1.0"] = "1.0"
    metric: Literal["gross_spending"] = "gross_spending"
    currency: Literal["USD"] = "USD"
    applied_filters: SpendingFilters
    total_spending: NonNegativeMoney
    transaction_count: NonNegativeCount

    @field_validator("total_spending", mode="before")
    @classmethod
    def reject_floating_point_money(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("monetary values must use Decimal, not float")
        return value


class CategorySpendingGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str | None
    bucket: Literal["category", "uncategorized"]
    total_spending: PositiveMoney
    transaction_count: PositiveCount
    percentage: Percentage

    @field_validator("total_spending", "percentage", mode="before")
    @classmethod
    def reject_floating_point_decimals(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("decimal values must use Decimal, not float")
        return value

    @model_validator(mode="after")
    def validate_bucket(self) -> Self:
        if self.bucket == "uncategorized" and self.category is not None:
            raise ValueError("uncategorized bucket must have a null category")
        if self.bucket == "category" and self.category is None:
            raise ValueError("category bucket must have a category")
        return self


class CategorySpendingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantics_version: Literal["1.0"] = "1.0"
    metric: Literal["gross_spending_by_category"] = "gross_spending_by_category"
    currency: Literal["USD"] = "USD"
    applied_filters: CategoryBreakdownFilters
    total_spending: NonNegativeMoney
    transaction_count: NonNegativeCount
    groups: list[CategorySpendingGroup]

    @field_validator("total_spending", mode="before")
    @classmethod
    def reject_floating_point_money(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("monetary values must use Decimal, not float")
        return value

    @model_validator(mode="after")
    def validate_reconciliation(self) -> Self:
        group_total = sum(
            (group.total_spending for group in self.groups),
            Decimal("0.00"),
        )
        if group_total != self.total_spending:
            raise ValueError("category totals must reconcile to total_spending")
        if sum(group.transaction_count for group in self.groups) != (self.transaction_count):
            raise ValueError("category counts must reconcile to transaction_count")
        return self


class ComparedSpendingPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    total_spending: NonNegativeMoney
    transaction_count: NonNegativeCount

    @field_validator("total_spending", mode="before")
    @classmethod
    def reject_floating_point_money(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("monetary values must use Decimal, not float")
        return value


class CategorySpendingDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str | None
    bucket: Literal["category", "uncategorized"]
    current_spending: NonNegativeMoney
    comparison_spending: NonNegativeMoney
    absolute_change: SignedMoney
    current_transaction_count: NonNegativeCount
    comparison_transaction_count: NonNegativeCount
    transaction_count_change: int

    @field_validator(
        "current_spending",
        "comparison_spending",
        "absolute_change",
        mode="before",
    )
    @classmethod
    def reject_floating_point_money(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("monetary values must use Decimal, not float")
        return value

    @model_validator(mode="after")
    def validate_delta(self) -> Self:
        if self.bucket == "uncategorized" and self.category is not None:
            raise ValueError("uncategorized bucket must have a null category")
        if self.bucket == "category" and self.category is None:
            raise ValueError("category bucket must have a category")
        if self.absolute_change != self.current_spending - self.comparison_spending:
            raise ValueError("category absolute_change must reconcile to period spending")
        expected_count_change = self.current_transaction_count - self.comparison_transaction_count
        if self.transaction_count_change != expected_count_change:
            raise ValueError("category transaction_count_change must reconcile")
        return self


class PeriodComparisonResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantics_version: Literal["1.0"] = "1.0"
    metric: Literal["gross_spending_period_comparison"] = "gross_spending_period_comparison"
    currency: Literal["USD"] = "USD"
    applied_filters: PeriodComparisonFilters
    current_period: ComparedSpendingPeriod
    comparison_period: ComparedSpendingPeriod
    absolute_change: SignedMoney
    percentage_change: SignedPercentage | None
    category_deltas: list[CategorySpendingDelta]

    @field_validator("absolute_change", "percentage_change", mode="before")
    @classmethod
    def reject_floating_point_decimals(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("decimal values must use Decimal, not float")
        return value

    @model_validator(mode="after")
    def validate_reconciliation(self) -> Self:
        expected_change = self.current_period.total_spending - self.comparison_period.total_spending
        if self.absolute_change != expected_change:
            raise ValueError("absolute_change must reconcile to period totals")
        if self.comparison_period.total_spending == Decimal("0.00"):
            if self.percentage_change is not None:
                raise ValueError("percentage_change must be null for a zero baseline")
        elif self.percentage_change is None:
            raise ValueError("percentage_change is required for a non-zero baseline")
        category_change = sum(
            (delta.absolute_change for delta in self.category_deltas),
            Decimal("0.00"),
        )
        if category_change != self.absolute_change:
            raise ValueError("category deltas must reconcile to absolute_change")
        if (
            sum(
                (delta.current_spending for delta in self.category_deltas),
                Decimal("0.00"),
            )
            != self.current_period.total_spending
        ):
            raise ValueError("category current spending must reconcile")
        if (
            sum(
                (delta.comparison_spending for delta in self.category_deltas),
                Decimal("0.00"),
            )
            != self.comparison_period.total_spending
        ):
            raise ValueError("category comparison spending must reconcile")
        if (
            sum(delta.current_transaction_count for delta in self.category_deltas)
            != self.current_period.transaction_count
        ):
            raise ValueError("category current counts must reconcile")
        if (
            sum(delta.comparison_transaction_count for delta in self.category_deltas)
            != self.comparison_period.transaction_count
        ):
            raise ValueError("category comparison counts must reconcile")
        return self


class LargeTransactionImportProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_batch_id: UUID
    filename: Annotated[str, Field(min_length=1, max_length=512)]
    adapter_name: AdapterName
    adapter_version: AdapterVersion
    account_label: AccountLabel | None


class LargeTransactionItem(TransactionRead):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    spending_magnitude: PositiveMoney
    import_provenance: LargeTransactionImportProvenance

    @field_validator("amount", "spending_magnitude", mode="before")
    @classmethod
    def reject_floating_point_money(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("monetary values must use Decimal, not float")
        return value

    @model_validator(mode="after")
    def validate_gross_outflow(self) -> Self:
        if self.amount >= Decimal("0.00"):
            raise ValueError("large transaction amount must be negative")
        if self.spending_magnitude != -self.amount:
            raise ValueError("spending_magnitude must equal negative amount")
        if self.import_provenance.import_batch_id != self.import_batch_id:
            raise ValueError("import provenance must match transaction batch")
        return self


class LargeTransactionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantics_version: Literal["1.0"] = "1.0"
    metric: Literal["large_gross_spending_transactions"] = "large_gross_spending_transactions"
    currency: Literal["USD"] = "USD"
    applied_filters: LargeTransactionFilters
    total_matching: NonNegativeCount
    returned_count: NonNegativeCount
    has_more: bool
    items: list[LargeTransactionItem]

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.returned_count != len(self.items):
            raise ValueError("returned_count must match items")
        if self.returned_count > self.total_matching:
            raise ValueError("returned_count cannot exceed total_matching")
        if self.returned_count > self.applied_filters.limit:
            raise ValueError("returned_count cannot exceed the applied limit")
        if self.has_more != (self.total_matching > self.returned_count):
            raise ValueError("has_more must reflect bounded results")
        return self
