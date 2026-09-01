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

CHASE_ADAPTER_NAME = "chase_credit_card"
CHASE_ADAPTER_VERSION = "1"
CHASE_DEFAULT_ACCOUNT_LABEL = "Chase Card"
CHASE_HEADERS = frozenset(
    {
        "Transaction Date",
        "Post Date",
        "Description",
        "Category",
        "Type",
        "Amount",
        "Memo",
    }
)


class ChaseCreditCardAdapter:
    header_row_numbers = (1,)
    identity = AdapterIdentity(name=CHASE_ADAPTER_NAME, version=CHASE_ADAPTER_VERSION)
    header_signatures = (CHASE_HEADERS,)

    def normalize(
        self,
        document: CsvDocument,
        *,
        account_label: AccountLabel | None,
    ) -> AdapterNormalizationResult:
        effective_account_label = account_label or CHASE_DEFAULT_ACCOUNT_LABEL
        rows: list[CanonicalTransactionRow] = []
        errors: list[AdapterRowError] = []

        if not document.rows:
            errors.append(AdapterRowError(message="CSV contains no transaction rows"))

        for row in document.rows:
            normalized, row_errors = normalize_chase_row(
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


def normalize_chase_row(
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

    transaction_date = parse_mmddyyyy(values["Transaction Date"])
    if transaction_date is None:
        errors.append(
            AdapterRowError(
                row_number=row.row_number,
                field="transaction_date",
                message="must be a valid date in MM/DD/YYYY format",
            )
        )

    posted_date = parse_mmddyyyy(values["Post Date"])
    if posted_date is None:
        errors.append(
            AdapterRowError(
                row_number=row.row_number,
                field="posted_date",
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
        allow_grouping=False,
    )
    if amount_error is not None:
        errors.append(
            AdapterRowError(
                row_number=row.row_number,
                field="amount",
                message=amount_error,
            )
        )

    if (
        errors
        or transaction_date is None
        or posted_date is None
        or description is None
        or amount is None
    ):
        return None, errors

    try:
        return (
            CanonicalTransactionRow(
                transaction_date=transaction_date,
                posted_date=posted_date,
                description=description,
                amount=amount,
                account_name=account_label,
                transaction_type=normalize_text(values["Type"]),
                category=normalize_text(values["Category"]),
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
