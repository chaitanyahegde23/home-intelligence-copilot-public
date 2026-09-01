from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.categorization import TransactionCategoryAssignmentRead
from app.schemas.transaction import TransactionRead

AccountFilter = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
CategoryFilter = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
MerchantFilter = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
Limit = Annotated[int, Field(ge=1, le=100)]
Offset = Annotated[int, Field(ge=0)]


class TransactionQueryParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date | None = None
    end_date: date | None = None
    account_name: AccountFilter | None = None
    category: CategoryFilter | None = None
    merchant_name: MerchantFilter | None = None
    import_batch_id: UUID | None = None
    limit: Limit = 50
    offset: Offset = 0

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("start_date must be on or before end_date")
        return self


class PaginationMetadata(BaseModel):
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    returned: int = Field(ge=0)
    has_more: bool


class TransactionListItem(TransactionRead):
    model_config = ConfigDict(from_attributes=True)

    category_assignment: TransactionCategoryAssignmentRead | None


class TransactionFilterSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: Literal["USD"] = "USD"
    transaction_count: int = Field(ge=0)
    gross_amount: Decimal = Field(max_digits=20, decimal_places=2, ge=0)
    spending_amount: Decimal = Field(max_digits=20, decimal_places=2, ge=0)
    income_amount: Decimal = Field(max_digits=20, decimal_places=2, ge=0)
    net_amount: Decimal = Field(max_digits=20, decimal_places=2)

    @model_validator(mode="after")
    def validate_totals(self) -> Self:
        if self.gross_amount != self.spending_amount + self.income_amount:
            raise ValueError("gross amount must reconcile")
        if self.net_amount != self.income_amount - self.spending_amount:
            raise ValueError("net amount must reconcile")
        return self


class TransactionListResponse(BaseModel):
    items: list[TransactionListItem]
    pagination: PaginationMetadata
    summary: TransactionFilterSummary
