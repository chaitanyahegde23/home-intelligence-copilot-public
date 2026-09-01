import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from app.schemas.import_adapter import (
    AccountLabel,
    AdapterIdentity,
    AdapterNormalizationResult,
    AdapterRowError,
    CanonicalTransactionRow,
)
from app.services.csv_reader import CsvDocument, CsvRow

CITI_ADAPTER_NAME = "citi_credit_card"
CITI_ADAPTER_VERSION = "2"
CITI_DEFAULT_ACCOUNT_LABEL = "Citi Card"
CITI_STATEMENT_HEADERS = frozenset(
    {"Status", "Date", "Description", "Debit", "Credit", "Member Name"}
)
CITI_ACTIVITY_REPORT_HEADERS = frozenset({"Date", "Description", "Debit", "Credit", "Category"})
DATE_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{4}$")
ACTIVITY_DATE_PATTERN = re.compile(r"^[A-Z][a-z]{2} \d{1,2}, \d{4}$")
AMOUNT_PATTERN = re.compile(r"^\d+(?:\.\d+)?$")
NEGATIVE_AMOUNT_PATTERN = re.compile(r"^-\d+(?:\.\d+)?$")


class CitiCreditCardAdapter:
    header_row_numbers = (1, 3)
    identity = AdapterIdentity(name=CITI_ADAPTER_NAME, version=CITI_ADAPTER_VERSION)
    header_signatures = (CITI_STATEMENT_HEADERS, CITI_ACTIVITY_REPORT_HEADERS)

    def normalize(
        self,
        document: CsvDocument,
        *,
        account_label: AccountLabel | None,
    ) -> AdapterNormalizationResult:
        effective_account_label = account_label or CITI_DEFAULT_ACCOUNT_LABEL
        rows: list[CanonicalTransactionRow] = []
        errors: list[AdapterRowError] = []

        if not document.rows:
            errors.append(AdapterRowError(message="CSV contains no transaction rows"))

        for row in document.rows:
            normalized, row_errors = normalize_citi_row(
                document.headers,
                row,
                account_label=effective_account_label,
            )
            errors.extend(row_errors)
            if normalized is not None:
                rows.append(normalized)

        return AdapterNormalizationResult(
            adapter=self.identity,
            account_label=effective_account_label,
            rows=rows,
            errors=errors,
        )


def normalize_citi_row(
    headers: list[str],
    row: CsvRow,
    *,
    account_label: AccountLabel,
) -> tuple[CanonicalTransactionRow | None, list[AdapterRowError]]:
    if len(row.values) != len(headers):
        return None, [
            AdapterRowError(
                row_number=row.row_number,
                message=f"expected {len(headers)} columns but found {len(row.values)}",
            )
        ]

    values = dict(zip(headers, row.values, strict=True))
    errors: list[AdapterRowError] = []

    is_activity_report = frozenset(headers) == CITI_ACTIVITY_REPORT_HEADERS
    transaction_date = (
        parse_citi_activity_date(values["Date"])
        if is_activity_report
        else parse_citi_date(values["Date"])
    )
    if transaction_date is None:
        errors.append(
            AdapterRowError(
                row_number=row.row_number,
                field="transaction_date",
                message=(
                    "must be a valid date in Mon D, YYYY format"
                    if is_activity_report
                    else "must be a valid date in MM/DD/YYYY format"
                ),
            )
        )

    description = normalize_text(values["Description"])
    if description is None:
        errors.append(
            AdapterRowError(
                row_number=row.row_number,
                field="description",
                message="description is required",
            )
        )

    amount, amount_error = (
        parse_citi_activity_amount(
            debit=values["Debit"],
            credit=values["Credit"],
        )
        if is_activity_report
        else parse_citi_amount(
            debit=values["Debit"],
            credit=values["Credit"],
        )
    )
    if amount_error is not None:
        errors.append(
            AdapterRowError(
                row_number=row.row_number,
                field="amount",
                message=amount_error,
            )
        )

    if errors or transaction_date is None or description is None or amount is None:
        return None, errors

    try:
        return (
            CanonicalTransactionRow(
                transaction_date=transaction_date,
                description=description,
                amount=amount,
                account_name=account_label,
                category=normalize_text(values.get("Category", "")),
            ),
            [],
        )
    except ValidationError as error:
        return None, [
            AdapterRowError(
                row_number=row.row_number,
                field=str(detail["loc"][0]) if detail["loc"] else None,
                message=str(detail["msg"]).removeprefix("Value error, "),
            )
            for detail in error.errors()
        ]


def parse_citi_date(value: str) -> date | None:
    normalized = value.strip()
    if not DATE_PATTERN.fullmatch(normalized):
        return None
    try:
        return datetime.strptime(normalized, "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_citi_activity_date(value: str) -> date | None:
    normalized = value.strip()
    if not ACTIVITY_DATE_PATTERN.fullmatch(normalized):
        return None
    try:
        return datetime.strptime(normalized, "%b %d, %Y").date()
    except ValueError:
        return None


def parse_citi_amount(*, debit: str, credit: str) -> tuple[Decimal | None, str | None]:
    normalized_debit = debit.strip()
    normalized_credit = credit.strip()
    populated = [value for value in (normalized_debit, normalized_credit) if value]
    if len(populated) != 1:
        return None, "exactly one of Debit or Credit must contain an amount"

    raw_amount = populated[0]
    if not AMOUNT_PATTERN.fullmatch(raw_amount):
        return None, "must be an unsigned decimal number"
    if "." in raw_amount and len(raw_amount.rsplit(".", maxsplit=1)[1]) > 2:
        return None, "must have at most two decimal places"
    try:
        amount = Decimal(raw_amount)
    except InvalidOperation:
        return None, "must be an unsigned decimal number"
    if not amount.is_finite():
        return None, "must be a finite decimal number"
    if amount <= 0:
        return None, "must be greater than zero"

    return (-amount if normalized_debit else amount), None


def parse_citi_activity_amount(*, debit: str, credit: str) -> tuple[Decimal | None, str | None]:
    normalized_debit = debit.strip()
    normalized_credit = credit.strip()
    populated = [value for value in (normalized_debit, normalized_credit) if value]
    if len(populated) != 1:
        return None, "exactly one of Debit or Credit must contain an amount"

    raw_amount = populated[0]
    pattern = AMOUNT_PATTERN if normalized_debit else NEGATIVE_AMOUNT_PATTERN
    expected = "a positive debit or negative credit decimal number"
    if not pattern.fullmatch(raw_amount):
        return None, f"must be {expected}"
    if "." in raw_amount and len(raw_amount.rsplit(".", maxsplit=1)[1]) > 2:
        return None, "must have at most two decimal places"
    try:
        amount = Decimal(raw_amount)
    except InvalidOperation:
        return None, f"must be {expected}"
    if not amount.is_finite():
        return None, "must be a finite decimal number"
    if normalized_debit and amount <= 0:
        return None, f"must be {expected}"
    if normalized_credit and amount >= 0:
        return None, f"must be {expected}"

    return -amount, None


def normalize_text(value: str) -> str | None:
    normalized = " ".join(value.split())
    return normalized or None
