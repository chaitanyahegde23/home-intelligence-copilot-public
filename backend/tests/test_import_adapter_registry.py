from datetime import date
from decimal import Decimal

import pytest

from app.schemas.import_adapter import (
    AccountLabel,
    AdapterIdentity,
    AdapterNormalizationResult,
    AmbiguousAdapterDetection,
    CanonicalTransactionRow,
    MatchedAdapterDetection,
    UnsupportedAdapterDetection,
)
from app.services.canonical_csv_adapter import CanonicalCsvAdapter
from app.services.csv_reader import CsvDocument, CsvRow
from app.services.import_adapter import AdapterRegistry, HeaderSignature


class SyntheticAdapter:
    def __init__(
        self,
        *,
        name: str,
        version: str,
        signatures: tuple[HeaderSignature, ...],
        header_row_numbers: tuple[int, ...] = (1,),
    ) -> None:
        self.identity = AdapterIdentity(name=name, version=version)
        self.header_row_numbers = header_row_numbers
        self.header_signatures = signatures

    def normalize(
        self,
        document: CsvDocument,
        *,
        account_label: AccountLabel | None,
    ) -> AdapterNormalizationResult:
        return AdapterNormalizationResult(
            adapter=self.identity,
            account_label=account_label,
            rows=[
                CanonicalTransactionRow(
                    transaction_date=date(2026, 1, 1),
                    description="Synthetic row",
                    amount=Decimal("-1.00"),
                )
            ]
            if document.rows
            else [],
        )


@pytest.mark.parametrize(
    "headers",
    [
        ["transaction_date", "description", "amount"],
        ["amount", "account_name", "description", "transaction_date"],
        ["posted_date", "amount", "description", "transaction_date"],
        [
            "account_name",
            "amount",
            "description",
            "posted_date",
            "transaction_date",
        ],
    ],
)
def test_canonical_signatures_match_exact_sets_in_any_order(headers: list[str]) -> None:
    registry = AdapterRegistry((CanonicalCsvAdapter(),))

    detection = registry.detect(headers)

    assert isinstance(detection, MatchedAdapterDetection)
    assert detection.adapter == AdapterIdentity(name="canonical_csv", version="1")
    assert registry.get(detection.adapter).identity == detection.adapter


@pytest.mark.parametrize(
    "headers",
    [
        [],
        ["transaction_date", "description"],
        ["transaction_date", "description", "amount", "unexpected"],
        ["transaction_date", "description", "amount", "amount"],
    ],
)
def test_unknown_incomplete_unexpected_and_duplicate_headers_are_unsupported(
    headers: list[str],
) -> None:
    detection = AdapterRegistry((CanonicalCsvAdapter(),)).detect(headers)

    assert isinstance(detection, UnsupportedAdapterDetection)


def test_overlapping_exact_signatures_are_ambiguous() -> None:
    signature = frozenset({"transaction_date", "description", "amount"})
    registry = AdapterRegistry(
        (
            SyntheticAdapter(name="first_format", version="1", signatures=(signature,)),
            SyntheticAdapter(name="second_format", version="1", signatures=(signature,)),
        )
    )

    detection = registry.detect(list(signature))

    assert isinstance(detection, AmbiguousAdapterDetection)
    assert [(candidate.name, candidate.version) for candidate in detection.candidates] == [
        ("first_format", "1"),
        ("second_format", "1"),
    ]


def test_duplicate_adapter_identities_are_rejected_at_registry_creation() -> None:
    signature = frozenset({"transaction_date", "description", "amount"})
    with pytest.raises(ValueError, match="identities must be unique"):
        AdapterRegistry(
            (
                SyntheticAdapter(name="same_format", version="1", signatures=(signature,)),
                SyntheticAdapter(name="same_format", version="1", signatures=(signature,)),
            )
        )


def test_unknown_adapter_identity_cannot_be_resolved() -> None:
    registry = AdapterRegistry((CanonicalCsvAdapter(),))

    with pytest.raises(LookupError, match="Expected one registered adapter"):
        registry.get(AdapterIdentity(name="unknown_format", version="1"))


def test_registry_selects_an_exact_reviewed_later_header_row() -> None:
    signature = frozenset({"Date", "Description", "Amount", "Running Bal."})
    registry = AdapterRegistry(
        (
            SyntheticAdapter(
                name="later_header",
                version="1",
                signatures=(signature,),
                header_row_numbers=(3,),
            ),
        )
    )
    document = CsvDocument(
        headers=["Synthetic preamble"],
        rows=[
            CsvRow(row_number=2, values=["More metadata"]),
            CsvRow(
                row_number=3,
                values=["Date", "Description", "Amount", "Running Bal."],
            ),
            CsvRow(
                row_number=4,
                values=["06/01/2026", "Example", "-1.00", "9.00"],
            ),
        ],
    )

    selection = registry.select(document)

    assert isinstance(selection.detection, MatchedAdapterDetection)
    assert selection.detection.adapter.name == "later_header"
    assert selection.document.headers == [
        "Date",
        "Description",
        "Amount",
        "Running Bal.",
    ]
    assert selection.document.rows[0].row_number == 4


@pytest.mark.parametrize("header_row_numbers", [(), (0,), (1, 1)])
def test_invalid_adapter_header_locations_are_rejected(
    header_row_numbers: tuple[int, ...],
) -> None:
    with pytest.raises(ValueError, match="unique positive integers"):
        AdapterRegistry(
            (
                SyntheticAdapter(
                    name="invalid_location",
                    version="1",
                    signatures=(frozenset({"Header"}),),
                    header_row_numbers=header_row_numbers,
                ),
            )
        )
