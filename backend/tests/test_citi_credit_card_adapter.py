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
)
from app.services.citi_credit_card_adapter import (
    CITI_DEFAULT_ACCOUNT_LABEL,
    CitiCreditCardAdapter,
)
from app.services.csv_reader import read_csv_document
from app.services.import_adapter import get_adapter_registry

SAMPLE_PATH = Path(__file__).resolve().parents[2] / "sample-data" / "synthetic-citi-credit-card.csv"
ACTIVITY_SAMPLE_PATH = (
    Path(__file__).resolve().parents[2] / "sample-data" / "synthetic-citi-activity-report.csv"
)
CITI_HEADER = "Status,Date,Description,Debit,Credit,Member Name\n"


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


def upload_citi(
    client: TestClient,
    content: bytes,
    *,
    account_label: str | None = "Sample Citi Card",
) -> Response:
    response = client.post(
        "/imports/transactions",
        files={"file": ("synthetic-citi-credit-card.csv", content, "text/csv")},
        data={} if account_label is None else {"account_label": account_label},
    )
    return cast(Response, response)


def normalize_one(
    row: str,
    *,
    account_label: str = "Sample Citi Card",
) -> AdapterNormalizationResult:
    document = read_csv_document((CITI_HEADER + row).encode())
    return CitiCreditCardAdapter().normalize(document, account_label=account_label)


def test_citi_fixture_normalizes_dates_signs_text_and_account_label() -> None:
    result = CitiCreditCardAdapter().normalize(
        read_csv_document(SAMPLE_PATH.read_bytes()),
        account_label="  Sample Citi Card  ",
    )

    assert result.adapter.name == "citi_credit_card"
    assert result.adapter.version == "2"
    assert result.account_label == "Sample Citi Card"
    assert result.errors == []
    assert [row.transaction_date for row in result.rows] == [
        date(2026, 2, 11),
        date(2026, 2, 14),
        date(2026, 2, 18),
        date(2026, 2, 22),
    ]
    assert [row.amount for row in result.rows] == [
        Decimal("-47.25"),
        Decimal("-18.40"),
        Decimal("7.15"),
        Decimal("250.00"),
    ]
    assert result.rows[1].description == "Example Cafe, Downtown"
    assert {row.account_name for row in result.rows} == {"Sample Citi Card"}
    assert all(row.transaction_type is None for row in result.rows)


def test_member_name_is_not_present_in_normalized_output() -> None:
    member_value = "Synthetic Member Value"
    result = normalize_one(f"Cleared,02/11/2026,Example Purchase,10.00,,{member_value}\n")

    assert result.errors == []
    assert member_value not in result.model_dump_json()


def test_missing_account_label_uses_safe_generic_label() -> None:
    document = read_csv_document(
        (CITI_HEADER + "Cleared,02/11/2026,Example Purchase,10.00,,Ignored\n").encode()
    )

    result = CitiCreditCardAdapter().normalize(document, account_label=None)

    assert result.account_label == CITI_DEFAULT_ACCOUNT_LABEL
    assert result.rows[0].account_name == CITI_DEFAULT_ACCOUNT_LABEL


@pytest.mark.parametrize(
    ("row", "field", "message"),
    [
        (
            "Cleared,02/11/2026,Example Purchase,10.00,2.00,Ignored\n",
            "amount",
            "exactly one of Debit or Credit must contain an amount",
        ),
        (
            "Cleared,02/11/2026,Example Purchase,,,Ignored\n",
            "amount",
            "exactly one of Debit or Credit must contain an amount",
        ),
        (
            "Cleared,02/11/2026,Example Purchase,0.00,,Ignored\n",
            "amount",
            "must be greater than zero",
        ),
        (
            "Cleared,02/11/2026,Example Purchase,-10.00,,Ignored\n",
            "amount",
            "must be an unsigned decimal number",
        ),
        (
            "Cleared,02/11/2026,Example Purchase,1.234,,Ignored\n",
            "amount",
            "must have at most two decimal places",
        ),
        (
            "Cleared,2/11/2026,Example Purchase,10.00,,Ignored\n",
            "transaction_date",
            "must be a valid date in MM/DD/YYYY format",
        ),
        (
            "Cleared,02/30/2026,Example Purchase,10.00,,Ignored\n",
            "transaction_date",
            "must be a valid date in MM/DD/YYYY format",
        ),
        (
            "Cleared,02/11/2026,   ,10.00,,Ignored\n",
            "description",
            "description is required",
        ),
    ],
)
def test_invalid_citi_rows_are_rejected(
    row: str,
    field: str,
    message: str,
) -> None:
    result = normalize_one(row)

    assert result.rows == []
    assert len(result.errors) == 1
    assert result.errors[0].row_number == 2
    assert result.errors[0].field == field
    assert result.errors[0].message == message


def test_mixed_citi_rows_preserve_valid_rows_and_errors() -> None:
    document = read_csv_document(
        (
            CITI_HEADER
            + "Cleared,02/11/2026,Example Purchase,10.00,,Ignored\n"
            + "Cleared,invalid,Example Invalid,5.00,,Ignored\n"
        ).encode()
    )

    result = CitiCreditCardAdapter().normalize(
        document,
        account_label="Sample Citi Card",
    )

    assert len(result.rows) == 1
    assert result.rows[0].amount == Decimal("-10.00")
    assert len(result.errors) == 1
    assert result.errors[0].row_number == 3


def test_default_registry_detects_citi_signature_in_any_order() -> None:
    detection = get_adapter_registry().detect(
        ["Credit", "Member Name", "Description", "Status", "Debit", "Date"]
    )

    assert isinstance(detection, MatchedAdapterDetection)
    assert detection.adapter.name == "citi_credit_card"
    assert detection.adapter.version == "2"


def test_citi_activity_report_normalizes_metadata_dates_signs_and_categories() -> None:
    selection = get_adapter_registry().select(read_csv_document(ACTIVITY_SAMPLE_PATH.read_bytes()))

    assert isinstance(selection.detection, MatchedAdapterDetection)
    assert selection.detection.adapter.name == "citi_credit_card"
    assert selection.detection.adapter.version == "2"
    result = CitiCreditCardAdapter().normalize(
        selection.document,
        account_label="Sample Citi Card",
    )

    assert result.errors == []
    assert [row.transaction_date for row in result.rows] == [
        date(2026, 7, 3),
        date(2026, 7, 5),
    ]
    assert [row.amount for row in result.rows] == [
        Decimal("-82.45"),
        Decimal("10.00"),
    ]
    assert [row.category for row in result.rows] == ["Groceries", "Shopping"]


@pytest.mark.parametrize(
    ("row", "field", "message"),
    [
        (
            '"07/03/2026",Example Purchase,10.00,,Shopping\n',
            "transaction_date",
            "must be a valid date in Mon D, YYYY format",
        ),
        (
            '"Jul 03, 2026",Example Purchase,-10.00,,Shopping\n',
            "amount",
            "must be a positive debit or negative credit decimal number",
        ),
        (
            '"Jul 03, 2026",Example Refund,,10.00,Shopping\n',
            "amount",
            "must be a positive debit or negative credit decimal number",
        ),
    ],
)
def test_invalid_citi_activity_rows_are_rejected(
    row: str,
    field: str,
    message: str,
) -> None:
    content = (
        'Time period of report:,"Jul. 01, 2026 to Jul. 31, 2026",,,\n\n'
        "Date,Description,Debit,Credit,Category\n" + row
    )
    selection = get_adapter_registry().select(read_csv_document(content.encode()))
    assert isinstance(selection.detection, MatchedAdapterDetection)

    result = CitiCreditCardAdapter().normalize(
        selection.document,
        account_label="Sample Citi Card",
    )

    assert result.rows == []
    assert [(error.row_number, error.field, error.message) for error in result.errors] == [
        (4, field, message)
    ]


def test_citi_fixture_upload_persists_transactions_and_provenance(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session

    response = upload_citi(client, SAMPLE_PATH.read_bytes())

    assert response.status_code == 201
    assert response.json() == {
        "import_batch_id": response.json()["import_batch_id"],
        "filename": "synthetic-citi-credit-card.csv",
        "adapter_name": "citi_credit_card",
        "adapter_version": "2",
        "account_label": "Sample Citi Card",
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
    assert batch.adapter_name == "citi_credit_card"
    assert batch.adapter_version == "2"
    assert batch.account_label == "Sample Citi Card"
    assert [transaction.amount for transaction in transactions] == [
        Decimal("-47.25"),
        Decimal("-18.40"),
        Decimal("7.15"),
        Decimal("250.00"),
    ]


def test_citi_database_error_rolls_back_batch_and_transactions(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session

    def fail_flush(*_args: object) -> None:
        raise RuntimeError("synthetic Citi database failure")

    event.listen(session, "before_flush", fail_flush)
    with pytest.raises(RuntimeError, match="synthetic Citi database failure"):
        upload_citi(client, SAMPLE_PATH.read_bytes())
    event.remove(session, "before_flush", fail_flush)

    assert session.scalar(select(func.count()).select_from(ImportBatch)) == 0
    assert session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_citi_activity_fixture_upload_persists_category_and_provenance(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session

    response = upload_citi(client, ACTIVITY_SAMPLE_PATH.read_bytes())

    assert response.status_code == 201
    assert response.json()["adapter_name"] == "citi_credit_card"
    assert response.json()["adapter_version"] == "2"
    assert response.json()["total_rows"] == 2
    transactions = list(session.scalars(select(Transaction).order_by(Transaction.transaction_date)))
    assert [transaction.category for transaction in transactions] == ["Groceries", "Shopping"]
    assert [transaction.amount for transaction in transactions] == [
        Decimal("-82.45"),
        Decimal("10.00"),
    ]
