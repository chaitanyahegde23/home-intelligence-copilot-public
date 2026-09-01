from pydantic import ValidationError

from app.schemas.import_adapter import (
    AccountLabel,
    AdapterIdentity,
    AdapterNormalizationResult,
    AdapterRowError,
    CanonicalTransactionRow,
)
from app.services.csv_reader import CsvDocument, CsvRow
from app.services.institution_csv_utils import (
    normalize_text,
    parse_mmddyyyy,
    parse_signed_amount,
)

BANK_OF_AMERICA_ADAPTER_NAME = "bank_of_america_account"
BANK_OF_AMERICA_ADAPTER_VERSION = "1"
BANK_OF_AMERICA_DEFAULT_ACCOUNT_LABEL = "Bank of America Account"
BANK_OF_AMERICA_HEADER_ROW_NUMBER = 7
BANK_OF_AMERICA_HEADERS = frozenset({"Date", "Description", "Amount", "Running Bal."})


class BankOfAmericaAccountAdapter:
    header_row_numbers = (BANK_OF_AMERICA_HEADER_ROW_NUMBER,)
    identity = AdapterIdentity(
        name=BANK_OF_AMERICA_ADAPTER_NAME,
        version=BANK_OF_AMERICA_ADAPTER_VERSION,
    )
    header_signatures = (BANK_OF_AMERICA_HEADERS,)

    def normalize(
        self,
        document: CsvDocument,
        *,
        account_label: AccountLabel | None,
    ) -> AdapterNormalizationResult:
        effective_account_label = account_label or BANK_OF_AMERICA_DEFAULT_ACCOUNT_LABEL
        rows: list[CanonicalTransactionRow] = []
        errors: list[AdapterRowError] = []
        ignored_row_count = 0

        if not document.rows:
            errors.append(AdapterRowError(message="CSV contains no transaction rows"))
        elif not is_opening_balance_row(document.headers, document.rows[0]):
            errors.append(
                AdapterRowError(
                    row_number=document.rows[0].row_number,
                    message=(
                        "first data row must be the reviewed Bank of America "
                        "beginning balance record"
                    ),
                )
            )
            return AdapterNormalizationResult(
                adapter=self.identity,
                account_label=effective_account_label,
                errors=errors,
            )
        else:
            ignored_row_count = 1

        for row in document.rows[ignored_row_count:]:
            normalized, row_errors = normalize_bank_of_america_row(
                document.headers,
                row,
                account_label=effective_account_label,
            )
            errors.extend(row_errors)
            if normalized is not None:
                rows.append(normalized)

        if ignored_row_count == 1 and len(document.rows) == 1:
            errors.append(AdapterRowError(message="CSV contains no transaction rows"))

        return AdapterNormalizationResult(
            adapter=self.identity,
            account_label=effective_account_label,
            rows=rows,
            errors=errors,
            ignored_row_count=ignored_row_count,
        )


def is_opening_balance_row(headers: list[str], row: CsvRow) -> bool:
    if len(row.values) != len(headers):
        return False
    values = dict(zip(headers, row.values, strict=True))
    source_date = values["Date"].strip()
    if parse_mmddyyyy(source_date) is None:
        return False
    if values["Amount"].strip():
        return False
    description = normalize_text(values["Description"])
    if description != f"Beginning balance as of {source_date}":
        return False
    running_balance, running_balance_error = parse_signed_amount(
        values["Running Bal."],
        allow_grouping=True,
    )
    return running_balance is not None and running_balance_error is None


def normalize_bank_of_america_row(
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

    transaction_date = parse_mmddyyyy(values["Date"])
    if transaction_date is None:
        errors.append(
            AdapterRowError(
                row_number=row.row_number,
                field="transaction_date",
                message="must be a valid date in MM/DD/YYYY format",
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

    amount, amount_error = parse_signed_amount(
        values["Amount"],
        allow_grouping=True,
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
