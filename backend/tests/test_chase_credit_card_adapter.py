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
from app.services.chase_credit_card_adapter import (
    CHASE_DEFAULT_ACCOUNT_LABEL,
    ChaseCreditCardAdapter,
)
from app.services.csv_reader import read_csv_document
from app.services.import_adapter import get_adapter_registry

SAMPLE_PATH = (
    Path(__file__).resolve().parents[2] / "sample-data" / "synthetic-chase-credit-card.csv"
)
CHASE_HEADER = "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"


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


def upload_chase(
    client: TestClient,
    content: bytes,
    *,
    account_label: str | None = "Sample Chase Card",
) -> Response:
    response = client.post(
        "/imports/transactions",
        files={"file": ("synthetic-chase-credit-card.csv", content, "text/csv")},
        data={} if account_label is None else {"account_label": account_label},
    )
    return cast(Response, response)


def normalize_one(
    row: str,
    *,
    account_label: str = "Sample Chase Card",
) -> AdapterNormalizationResult:
    document = read_csv_document((CHASE_HEADER + row).encode())
    return ChaseCreditCardAdapter().normalize(
        document,
        account_label=account_label,
    )


def test_chase_fixture_normalizes_dates_signs_fields_and_whitespace() -> None:
    result = ChaseCreditCardAdapter().normalize(
        read_csv_document(SAMPLE_PATH.read_bytes()),
        account_label="  Sample Chase Card  ",
    )

    assert result.adapter.name == "chase_credit_card"
    assert result.adapter.version == "1"
    assert result.account_label == "Sample Chase Card"
    assert result.errors == []
    assert [row.transaction_date for row in result.rows] == [
        date(2026, 6, 3),
        date(2026, 6, 8),
        date(2026, 6, 12),
        date(2026, 6, 20),
    ]
    assert [row.posted_date for row in result.rows] == [
        date(2026, 6, 4),
        date(2026, 6, 9),
        date(2026, 6, 13),
        date(2026, 6, 21),
    ]
    assert [row.amount for row in result.rows] == [
        Decimal("-82.45"),
        Decimal("-18.40"),
        Decimal("7.15"),
        Decimal("250.00"),
    ]
    assert result.rows[1].description == "Example Cafe, Downtown"
    assert result.rows[0].category == "Groceries"
    assert result.rows[2].category is None
    assert [row.transaction_type for row in result.rows] == [
        "Sale",
        "Sale",
        "Return",
        "Payment",
    ]


def test_chase_memo_is_ignored_and_safe_label_is_used() -> None:
    memo = "Synthetic memo that must not persist"
    result = normalize_one(f"06/03/2026,06/04/2026,Example Purchase,,Sale,-10.00,{memo}\n")

    assert result.errors == []
    assert result.rows[0].account_name == "Sample Chase Card"
    assert memo not in result.model_dump_json()


def test_missing_account_label_uses_safe_chase_default() -> None:
    result = ChaseCreditCardAdapter().normalize(
        read_csv_document(
            (CHASE_HEADER + "06/03/2026,06/04/2026,Example Purchase,,Sale,-10.00,\n").encode()
        ),
        account_label=None,
    )

    assert result.account_label == CHASE_DEFAULT_ACCOUNT_LABEL
    assert result.rows[0].account_name == CHASE_DEFAULT_ACCOUNT_LABEL


@pytest.mark.parametrize(
    ("row", "field"),
    [
        (
            "2026-06-03,06/04/2026,Example Purchase,,Sale,-10.00,\n",
            "transaction_date",
        ),
        (
            "06/03/2026,2026-06-04,Example Purchase,,Sale,-10.00,\n",
            "posted_date",
        ),
        (
            "06/31/2026,06/04/2026,Example Purchase,,Sale,-10.00,\n",
            "transaction_date",
        ),
        (
            "06/03/2026,06/04/2026,   ,,Sale,-10.00,\n",
            "description",
        ),
        (
            "06/03/2026,06/04/2026,Example Purchase,,Sale,0.00,\n",
            "amount",
        ),
        (
            "06/03/2026,06/04/2026,Example Purchase,,Sale,+10.00,\n",
            "amount",
        ),
        (
            "06/03/2026,06/04/2026,Example Purchase,,Sale,-10.001,\n",
            "amount",
        ),
        (
            '06/03/2026,06/04/2026,Example Purchase,,Sale,"-1,000.00",\n',
            "amount",
        ),
    ],
)
def test_chase_invalid_rows_are_rejected(row: str, field: str) -> None:
    result = normalize_one(row)

    assert result.rows == []
    assert len(result.errors) == 1
    assert result.errors[0].row_number == 2
    assert result.errors[0].field == field


def test_chase_optional_text_fields_may_be_blank() -> None:
    result = normalize_one(
        "06/03/2026,06/04/2026,  Example   Purchase  ,,,-10.00,  Ignored memo  \n"
    )

    assert result.errors == []
    assert result.rows[0].description == "Example Purchase"
    assert result.rows[0].category is None
    assert result.rows[0].transaction_type is None


def test_mixed_chase_rows_preserve_valid_rows_and_source_line_errors() -> None:
    document = read_csv_document(
        (
            CHASE_HEADER
            + "06/03/2026,06/04/2026,Example Purchase,,Sale,-10.00,\n"
            + "invalid,06/05/2026,Example Invalid,,Sale,-5.00,\n"
        ).encode()
    )

    result = ChaseCreditCardAdapter().normalize(
        document,
        account_label="Sample Chase Card",
    )

    assert len(result.rows) == 1
    assert result.rows[0].amount == Decimal("-10.00")
    assert len(result.errors) == 1
    assert result.errors[0].row_number == 3


def test_default_registry_detects_only_exact_chase_signature() -> None:
    registry = get_adapter_registry()
    detection = registry.detect(
        ["Memo", "Amount", "Type", "Category", "Description", "Post Date", "Transaction Date"]
    )
    changed = registry.detect(
        [
            "Memo",
            "Amount",
            "Type",
            "Category",
            "Description",
            "Post Date",
            "Transaction Date",
            "Extra",
        ]
    )

    assert isinstance(detection, MatchedAdapterDetection)
    assert detection.adapter.name == "chase_credit_card"
    assert detection.adapter.version == "1"
    assert not isinstance(changed, MatchedAdapterDetection)


def test_chase_fixture_upload_persists_transactions_and_provenance(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session

    response = upload_chase(client, SAMPLE_PATH.read_bytes())

    assert response.status_code == 201
    assert response.json() == {
        "import_batch_id": response.json()["import_batch_id"],
        "filename": "synthetic-chase-credit-card.csv",
        "adapter_name": "chase_credit_card",
        "adapter_version": "1",
        "account_label": "Sample Chase Card",
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
    assert batch.adapter_name == "chase_credit_card"
    assert batch.row_count == 4
    assert [transaction.amount for transaction in transactions] == [
        Decimal("-82.45"),
        Decimal("-18.40"),
        Decimal("7.15"),
        Decimal("250.00"),
    ]
    assert transactions[0].category == "Groceries"
    assert transactions[0].transaction_type == "Sale"


def test_chase_database_error_rolls_back_batch_and_transactions(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session

    def fail_flush(*_args: object) -> None:
        raise RuntimeError("synthetic Chase database failure")

    event.listen(session, "before_flush", fail_flush)
    with pytest.raises(RuntimeError, match="synthetic Chase database failure"):
        upload_chase(client, SAMPLE_PATH.read_bytes())
    event.remove(session, "before_flush", fail_flush)

    assert session.scalar(select(func.count()).select_from(ImportBatch)) == 0
    assert session.scalar(select(func.count()).select_from(Transaction)) == 0
