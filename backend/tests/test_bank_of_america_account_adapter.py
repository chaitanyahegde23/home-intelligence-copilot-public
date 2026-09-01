from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import ImportBatch, Transaction
from app.schemas.import_adapter import (
    AdapterNormalizationResult,
    MatchedAdapterDetection,
    UnsupportedAdapterDetection,
)
from app.services.bank_of_america_account_adapter import (
    BANK_OF_AMERICA_DEFAULT_ACCOUNT_LABEL,
    BankOfAmericaAccountAdapter,
)
from app.services.csv_reader import read_csv_document
from app.services.import_adapter import get_adapter_registry

SAMPLE_PATH = (
    Path(__file__).resolve().parents[2] / "sample-data" / "synthetic-bank-of-america-account.csv"
)
PREAMBLE = (
    "Synthetic statement export\n"
    "Synthetic household account\n"
    "Synthetic statement period\n"
    "Synthetic metadata record\n"
    "Synthetic balances section\n\n"
)
BANK_OF_AMERICA_HEADER = "Date,Description,Amount,Running Bal.\n"
OPENING_BALANCE = '06/01/2026,Beginning balance as of 06/01/2026,,"1,000.00"\n'


@pytest.fixture
def client_and_session() -> Iterator[tuple[TestClient, Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as session:

        def override_get_db() -> Iterator[Session]:
            yield session

        settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            max_upload_size_bytes=1024 * 1024,
        )
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_settings] = lambda: settings
        with TestClient(app) as client:
            yield client, session
        app.dependency_overrides.clear()

    engine.dispose()


def upload_bank_of_america(
    client: TestClient,
    content: bytes,
    *,
    account_label: str | None = "Sample Bank of America Account",
) -> Response:
    response = client.post(
        "/imports/transactions",
        files={
            "file": (
                "synthetic-bank-of-america-account.csv",
                content,
                "text/csv",
            )
        },
        data={} if account_label is None else {"account_label": account_label},
    )
    return cast(Response, response)


def select_and_normalize(
    content: str,
    *,
    account_label: str | None = "Sample Bank of America Account",
) -> AdapterNormalizationResult:
    selection = get_adapter_registry().select(read_csv_document(content.encode()))
    assert isinstance(selection.detection, MatchedAdapterDetection)
    return BankOfAmericaAccountAdapter().normalize(
        selection.document,
        account_label=account_label,
    )


def test_bank_of_america_fixture_selects_reviewed_header_row() -> None:
    original = read_csv_document(SAMPLE_PATH.read_bytes())

    selection = get_adapter_registry().select(original)

    assert isinstance(selection.detection, MatchedAdapterDetection)
    assert selection.detection.adapter.name == "bank_of_america_account"
    assert selection.detection.adapter.version == "1"
    assert selection.document.headers == [
        "Date",
        "Description",
        "Amount",
        "Running Bal.",
    ]
    assert selection.document.rows[0].row_number == 8


def test_bank_of_america_fixture_normalizes_signs_grouping_and_opening_balance() -> None:
    result = select_and_normalize(SAMPLE_PATH.read_text(encoding="utf-8"))

    assert result.adapter.name == "bank_of_america_account"
    assert result.adapter.version == "1"
    assert result.ignored_row_count == 1
    assert result.errors == []
    assert [row.transaction_date for row in result.rows] == [
        date(2026, 6, 3),
        date(2026, 6, 5),
        date(2026, 6, 10),
        date(2026, 6, 12),
    ]
    assert [row.amount for row in result.rows] == [
        Decimal("-82.45"),
        Decimal("-18.40"),
        Decimal("1250.00"),
        Decimal("-75.25"),
    ]
    assert result.rows[1].description == "Example Cafe, Downtown"
    assert {row.account_name for row in result.rows} == {"Sample Bank of America Account"}
    assert all(row.posted_date is None for row in result.rows)
    assert all(row.category is None for row in result.rows)
    assert all(row.transaction_type is None for row in result.rows)


def test_missing_account_label_uses_safe_bank_of_america_default() -> None:
    result = select_and_normalize(
        PREAMBLE
        + BANK_OF_AMERICA_HEADER
        + OPENING_BALANCE
        + "06/03/2026,Example Purchase,-10.00,990.00\n",
        account_label=None,
    )

    assert result.account_label == BANK_OF_AMERICA_DEFAULT_ACCOUNT_LABEL
    assert result.rows[0].account_name == BANK_OF_AMERICA_DEFAULT_ACCOUNT_LABEL


def test_preamble_values_and_running_balance_are_not_persisted() -> None:
    private_metadata = "Synthetic preamble value that must not persist"
    content = (
        f"{private_metadata}\n"
        "Synthetic household account\n"
        "Synthetic statement period\n"
        "Synthetic metadata record\n"
        "Synthetic balances section\n\n"
        + BANK_OF_AMERICA_HEADER
        + OPENING_BALANCE
        + '06/03/2026,Example Purchase,-10.00,"9,999.99"\n'
    )

    result = select_and_normalize(content)

    serialized = result.model_dump_json()
    assert private_metadata not in serialized
    assert "9,999.99" not in serialized


@pytest.mark.parametrize(
    ("row", "field"),
    [
        ("2026-06-03,Example Purchase,-10.00,990.00\n", "transaction_date"),
        ("06/31/2026,Example Purchase,-10.00,990.00\n", "transaction_date"),
        ("06/03/2026,   ,-10.00,990.00\n", "description"),
        ("06/03/2026,Example Purchase,,990.00\n", "amount"),
        ("06/03/2026,Example Purchase,0.00,990.00\n", "amount"),
        ("06/03/2026,Example Purchase,+10.00,990.00\n", "amount"),
        ("06/03/2026,Example Purchase,10.001,990.00\n", "amount"),
        ('06/03/2026,Example Purchase,"12,34.56",990.00\n', "amount"),
    ],
)
def test_bank_of_america_invalid_transaction_rows_are_rejected(
    row: str,
    field: str,
) -> None:
    result = select_and_normalize(PREAMBLE + BANK_OF_AMERICA_HEADER + OPENING_BALANCE + row)

    assert result.ignored_row_count == 1
    assert result.rows == []
    assert len(result.errors) == 1
    assert result.errors[0].row_number == 9
    assert result.errors[0].field == field


@pytest.mark.parametrize(
    "opening_row",
    [
        '06/01/2026,Beginning balance as of 06/01/2026,-1.00,"1,000.00"\n',
        '06/01/2026,Opening balance as of 06/01/2026,,"1,000.00"\n',
        '06/01/2026,Beginning balance as of 06/02/2026,,"1,000.00"\n',
        "06/01/2026,Beginning balance as of 06/01/2026,,invalid\n",
    ],
)
def test_changed_opening_balance_layout_fails_without_importing_rows(
    opening_row: str,
) -> None:
    result = select_and_normalize(
        PREAMBLE
        + BANK_OF_AMERICA_HEADER
        + opening_row
        + "06/03/2026,Example Purchase,-10.00,990.00\n"
    )

    assert result.rows == []
    assert result.ignored_row_count == 0
    assert len(result.errors) == 1
    assert "beginning balance record" in result.errors[0].message


def test_changed_preamble_length_is_not_detected() -> None:
    content = (
        "Synthetic statement export\n"
        "Synthetic household account\n"
        "Synthetic statement period\n"
        "Synthetic metadata record\n" + BANK_OF_AMERICA_HEADER + OPENING_BALANCE
    )

    selection = get_adapter_registry().select(read_csv_document(content.encode()))

    assert isinstance(selection.detection, UnsupportedAdapterDetection)


def test_bank_of_america_header_on_first_row_is_not_detected() -> None:
    selection = get_adapter_registry().select(
        read_csv_document((BANK_OF_AMERICA_HEADER + OPENING_BALANCE).encode())
    )

    assert isinstance(selection.detection, UnsupportedAdapterDetection)


def test_mixed_bank_of_america_rows_preserve_valid_rows_and_source_errors() -> None:
    result = select_and_normalize(
        PREAMBLE
        + BANK_OF_AMERICA_HEADER
        + OPENING_BALANCE
        + "06/03/2026,Example Purchase,-10.00,990.00\n"
        + "invalid,Example Invalid,-5.00,985.00\n"
    )

    assert result.ignored_row_count == 1
    assert len(result.rows) == 1
    assert result.rows[0].amount == Decimal("-10.00")
    assert len(result.errors) == 1
    assert result.errors[0].row_number == 10


def test_bank_of_america_fixture_upload_excludes_metadata_from_counters(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session

    response = upload_bank_of_america(client, SAMPLE_PATH.read_bytes())

    assert response.status_code == 201
    assert response.json() == {
        "import_batch_id": response.json()["import_batch_id"],
        "filename": "synthetic-bank-of-america-account.csv",
        "adapter_name": "bank_of_america_account",
        "adapter_version": "1",
        "account_label": "Sample Bank of America Account",
        "status": "completed",
        "total_rows": 4,
        "imported_rows": 4,
        "rejected_rows": 0,
        "duplicate_candidates_created": 0,
        "errors": [],
    }
    batch = session.scalar(select(ImportBatch))
    transactions = list(session.scalars(select(Transaction).order_by(Transaction.transaction_date)))
    assert batch is not None
    assert batch.adapter_name == "bank_of_america_account"
    assert batch.row_count == 4
    assert batch.imported_count == 4
    assert batch.rejected_count == 0
    assert len(transactions) == 4
    assert [transaction.amount for transaction in transactions] == [
        Decimal("-82.45"),
        Decimal("-18.40"),
        Decimal("1250.00"),
        Decimal("-75.25"),
    ]


def test_bank_of_america_database_error_rolls_back_batch_and_transactions(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session

    def fail_flush(*_args: object) -> None:
        raise RuntimeError("synthetic Bank of America database failure")

    event.listen(session, "before_flush", fail_flush)
    with pytest.raises(RuntimeError, match="synthetic Bank of America database failure"):
        upload_bank_of_america(client, SAMPLE_PATH.read_bytes())
    event.remove(session, "before_flush", fail_flush)

    assert session.scalar(select(func.count()).select_from(ImportBatch)) == 0
    assert session.scalar(select(func.count()).select_from(Transaction)) == 0
