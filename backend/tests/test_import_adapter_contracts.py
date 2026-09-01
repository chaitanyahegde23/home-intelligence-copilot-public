from datetime import date
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.import_adapter import (
    AdapterDetectionResult,
    AdapterIdentity,
    AdapterNormalizationResult,
    AmbiguousAdapterDetection,
    CanonicalTransactionRow,
    MatchedAdapterDetection,
    UnsupportedAdapterDetection,
)


def adapter_identity(name: str = "canonical_csv", version: str = "1") -> AdapterIdentity:
    return AdapterIdentity(name=name, version=version)


def canonical_row() -> dict[str, object]:
    return {
        "transaction_date": date(2026, 1, 3),
        "posted_date": date(2026, 1, 4),
        "description": "Example Purchase",
        "amount": Decimal("-82.45"),
        "account_name": "Sample Card",
    }


def test_normalization_contract_accepts_strict_canonical_values() -> None:
    result = AdapterNormalizationResult(
        adapter=adapter_identity(),
        account_label="  Sample Card  ",
        rows=[CanonicalTransactionRow.model_validate(canonical_row())],
    )

    assert result.adapter.name == "canonical_csv"
    assert result.adapter.version == "1"
    assert result.account_label == "Sample Card"
    assert result.rows[0].amount == Decimal("-82.45")


@pytest.mark.parametrize("amount", [82.45, "82.45"])
def test_canonical_money_rejects_non_decimal_inputs(amount: object) -> None:
    row = {**canonical_row(), "amount": amount}

    with pytest.raises(ValidationError):
        CanonicalTransactionRow.model_validate(row)


def test_canonical_dates_reject_unparsed_strings() -> None:
    row = {**canonical_row(), "transaction_date": "2026-01-03"}

    with pytest.raises(ValidationError):
        CanonicalTransactionRow.model_validate(row)


def test_detection_contracts_have_distinct_valid_states() -> None:
    matched = MatchedAdapterDetection(adapter=adapter_identity())
    unsupported = UnsupportedAdapterDetection(message="No exact header signature matched")
    ambiguous = AmbiguousAdapterDetection(
        candidates=[adapter_identity(), adapter_identity("citi_card", "1")],
        message="More than one exact signature matched",
    )

    assert matched.status == "matched"
    assert unsupported.status == "unsupported"
    assert ambiguous.status == "ambiguous"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "status": "matched",
            "adapter": {"name": "canonical_csv", "version": "1"},
            "message": "mixed state",
        },
        {"status": "unsupported", "message": ""},
        {
            "status": "ambiguous",
            "candidates": [{"name": "canonical_csv", "version": "1"}],
            "message": "only one candidate",
        },
        {
            "status": "ambiguous",
            "candidates": [
                {"name": "canonical_csv", "version": "1"},
                {"name": "canonical_csv", "version": "1"},
            ],
            "message": "duplicate candidates",
        },
    ],
)
def test_detection_contract_rejects_invalid_or_mixed_states(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(AdapterDetectionResult).validate_python(payload)


@pytest.mark.parametrize(
    ("name", "version"),
    [("Citi Card", "1"), ("canonical_csv", ""), ("_private", "1")],
)
def test_adapter_identity_rejects_unversioned_or_unsafe_values(
    name: str,
    version: str,
) -> None:
    with pytest.raises(ValidationError):
        AdapterIdentity(name=name, version=version)


def test_normalization_contract_tracks_non_transaction_metadata_rows() -> None:
    result = AdapterNormalizationResult(
        adapter=adapter_identity("bank_of_america_account", "1"),
        ignored_row_count=1,
    )

    assert result.ignored_row_count == 1

    with pytest.raises(ValidationError):
        AdapterNormalizationResult(
            adapter=adapter_identity(),
            ignored_row_count=-1,
        )
