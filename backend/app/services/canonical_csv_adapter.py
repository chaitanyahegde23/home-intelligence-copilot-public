import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.models.import_batch import CANONICAL_ADAPTER_NAME, CANONICAL_ADAPTER_VERSION
from app.schemas.import_adapter import (
    AccountLabel,
    AdapterIdentity,
    AdapterNormalizationResult,
    AdapterRowError,
    CanonicalTransactionRow,
)
from app.services.csv_reader import CsvDocument, CsvRow

REQUIRED_COLUMNS = {
    "transaction_date",
    "description",
    "amount",
}
OPTIONAL_COLUMNS = ("posted_date", "account_name")
AMOUNT_PATTERN = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
Money = Annotated[Decimal, Field(max_digits=18, decimal_places=2)]


class CanonicalCsvRow(BaseModel):
    transaction_date: date
    posted_date: date | None = None
    description: Annotated[str, Field(min_length=1)]
    amount: Money
    account_name: str | None = None

    @field_validator("transaction_date", mode="before")
    @classmethod
    def validate_transaction_date(cls, value: object) -> date:
        parsed = parse_strict_date(value, optional=False)
        if parsed is None:
            raise ValueError("transaction date is required")
        return parsed

    @field_validator("posted_date", mode="before")
    @classmethod
    def validate_posted_date(cls, value: object) -> date | None:
        return parse_strict_date(value, optional=True)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> str:
        return normalize_text(value) or ""

    @field_validator("account_name", mode="before")
    @classmethod
    def normalize_account_name(cls, value: object) -> str | None:
        return normalize_text(value)

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, value: object) -> Decimal:
        normalized = str(value).strip()
        if not AMOUNT_PATTERN.fullmatch(normalized):
            raise ValueError("must be a decimal number")
        try:
            amount = Decimal(normalized)
        except InvalidOperation as error:
            raise ValueError("must be a decimal number") from error
        if not amount.is_finite():
            raise ValueError("must be a finite decimal number")
        return amount


class CanonicalCsvAdapter:
    header_row_numbers = (1,)
    identity = AdapterIdentity(
        name=CANONICAL_ADAPTER_NAME,
        version=CANONICAL_ADAPTER_VERSION,
    )
    header_signatures = tuple(
        frozenset(REQUIRED_COLUMNS | set(optional_columns))
        for optional_columns in (
            (),
            (OPTIONAL_COLUMNS[0],),
            (OPTIONAL_COLUMNS[1],),
            OPTIONAL_COLUMNS,
        )
    )

    def normalize(
        self,
        document: CsvDocument,
        *,
        account_label: AccountLabel | None,
    ) -> AdapterNormalizationResult:
        rows: list[CanonicalTransactionRow] = []
        errors: list[AdapterRowError] = []

        if not document.rows:
            errors.append(AdapterRowError(message="CSV contains no transaction rows"))

        for row in document.rows:
            normalized, row_errors = validate_row(document.headers, row)
            errors.extend(row_errors)
            if normalized is not None:
                rows.append(
                    CanonicalTransactionRow(
                        transaction_date=normalized.transaction_date,
                        posted_date=normalized.posted_date,
                        description=normalized.description,
                        amount=normalized.amount,
                        account_name=normalized.account_name or account_label,
                    )
                )

        return AdapterNormalizationResult(
            adapter=self.identity,
            account_label=account_label,
            rows=rows,
            errors=errors,
        )


def validate_row(
    headers: list[str],
    row: CsvRow,
) -> tuple[CanonicalCsvRow | None, list[AdapterRowError]]:
    if len(row.values) != len(headers):
        return None, [
            AdapterRowError(
                row_number=row.row_number,
                message=f"expected {len(headers)} columns but found {len(row.values)}",
            )
        ]

    values = dict(zip(headers, row.values, strict=True))
    try:
        return CanonicalCsvRow.model_validate(values), []
    except ValidationError as error:
        errors = [
            AdapterRowError(
                row_number=row.row_number,
                field=str(detail["loc"][0]) if detail["loc"] else None,
                message=str(detail["msg"]).removeprefix("Value error, "),
            )
            for detail in error.errors()
        ]
        return None, errors


def normalize_text(value: object) -> str | None:
    normalized = " ".join(str(value).split())
    return normalized or None


def parse_strict_date(value: object, *, optional: bool) -> date | None:
    normalized = str(value).strip()
    if optional and not normalized:
        return None
    if not DATE_PATTERN.fullmatch(normalized):
        raise ValueError("must be a valid date in YYYY-MM-DD format")
    try:
        return date.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError("must be a valid date in YYYY-MM-DD format") from error
