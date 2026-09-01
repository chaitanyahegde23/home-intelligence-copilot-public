from collections.abc import Iterator
from decimal import Decimal
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
from app.models import ImportBatch, ImportStatus, Transaction
from app.schemas.import_adapter import (
    AccountLabel,
    AdapterIdentity,
    AdapterNormalizationResult,
)
from app.services.csv_reader import CsvDocument
from app.services.import_adapter import AdapterRegistry, HeaderSignature, get_adapter_registry
from app.services.transaction_import import AdapterContractError, validate_adapter_result

CSV_HEADER = "transaction_date,posted_date,description,amount,account_name\n"
VALID_ROW = "2026-01-03,2026-01-04,  Example   Grocery Store  ,-82.45, Sample Checking \n"


class SyntheticTestAdapter:
    def __init__(self, *, name: str, raise_on_normalize: bool = False) -> None:
        self.identity = AdapterIdentity(name=name, version="1")
        self.header_row_numbers = (1,)
        self.header_signatures: tuple[HeaderSignature, ...] = (
            frozenset({"transaction_date", "description", "amount"}),
        )
        self.raise_on_normalize = raise_on_normalize

    def normalize(
        self,
        document: CsvDocument,
        *,
        account_label: AccountLabel | None,
    ) -> AdapterNormalizationResult:
        if self.raise_on_normalize:
            raise RuntimeError("synthetic adapter failure")
        return AdapterNormalizationResult(
            adapter=self.identity,
            account_label=account_label,
        )


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


def upload_csv(
    client: TestClient,
    content: str,
    *,
    filename: str = "synthetic-transactions.csv",
    content_type: str = "text/csv",
    account_label: str | None = None,
) -> Response:
    response = client.post(
        "/imports/transactions",
        files={"file": (filename, content.encode(), content_type)},
        data={} if account_label is None else {"account_label": account_label},
    )
    return cast(Response, response)


def test_valid_upload_creates_batch_and_transactions(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    response = upload_csv(
        client,
        CSV_HEADER + VALID_ROW + "2026-01-05,,Example Employer,2500.00,Sample Checking\n",
    )

    assert response.status_code == 201
    assert response.json() == {
        "import_batch_id": response.json()["import_batch_id"],
        "filename": "synthetic-transactions.csv",
        "adapter_name": "canonical_csv",
        "adapter_version": "1",
        "account_label": None,
        "status": "completed",
        "total_rows": 2,
        "imported_rows": 2,
        "rejected_rows": 0,
        "duplicate_candidates_created": 0,
        "errors": [],
    }

    batch = session.scalar(select(ImportBatch))
    transactions = list(session.scalars(select(Transaction).order_by(Transaction.transaction_date)))

    assert batch is not None
    assert batch.status is ImportStatus.COMPLETED
    assert batch.row_count == 2
    assert len(transactions) == 2
    assert transactions[0].description == "Example Grocery Store"
    assert transactions[0].account_name == "Sample Checking"
    assert transactions[0].amount == Decimal("-82.45")
    assert transactions[1].posted_date is None


def test_account_label_is_stored_and_fills_missing_row_account(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    response = upload_csv(
        client,
        CSV_HEADER
        + "2026-01-03,,Example Purchase,-10.00,\n"
        + "2026-01-04,,Example Refund,5.00,Existing Account\n",
        account_label="  Sample Household Card  ",
    )

    assert response.status_code == 201
    assert response.json()["account_label"] == "Sample Household Card"
    batch = session.scalar(select(ImportBatch))
    transactions = list(session.scalars(select(Transaction).order_by(Transaction.transaction_date)))
    assert batch is not None
    assert batch.account_label == "Sample Household Card"
    assert [transaction.account_name for transaction in transactions] == [
        "Sample Household Card",
        "Existing Account",
    ]


def test_reordered_minimal_canonical_headers_remain_supported(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    response = upload_csv(
        client,
        "amount,description,transaction_date\n-12.30, Example Purchase ,2026-01-03\n",
        account_label="Sample Card",
    )

    assert response.status_code == 201
    assert response.json()["status"] == "completed"
    assert response.json()["adapter_name"] == "canonical_csv"
    transaction = session.scalar(select(Transaction))
    assert transaction is not None
    assert transaction.amount == Decimal("-12.30")
    assert transaction.description == "Example Purchase"
    assert transaction.account_name == "Sample Card"


@pytest.mark.parametrize(
    ("content", "detail"),
    [
        (
            "transaction_date,description,amount,unexpected\n2026-01-03,Example,-1.00,value\n",
            "CSV headers do not match a supported format",
        ),
        (
            "transaction_date,description,amount,amount\n2026-01-03,Example,-1.00,-1.00\n",
            "CSV contains duplicate column names",
        ),
    ],
)
def test_unexpected_and_duplicate_headers_fail_without_persistence(
    client_and_session: tuple[TestClient, Session],
    content: str,
    detail: str,
) -> None:
    client, session = client_and_session

    response = upload_csv(client, content)

    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert session.scalar(select(func.count()).select_from(ImportBatch)) == 0


def test_ambiguous_signature_fails_without_persistence(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    app.dependency_overrides[get_adapter_registry] = lambda: AdapterRegistry(
        (
            SyntheticTestAdapter(name="first_format"),
            SyntheticTestAdapter(name="second_format"),
        )
    )

    response = upload_csv(
        client,
        "transaction_date,description,amount\n2026-01-03,Example,-1.00\n",
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "CSV headers match more than one supported format"}
    assert session.scalar(select(func.count()).select_from(ImportBatch)) == 0
    assert session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_adapter_exception_leaves_no_database_state(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    app.dependency_overrides[get_adapter_registry] = lambda: AdapterRegistry(
        (SyntheticTestAdapter(name="raising_format", raise_on_normalize=True),)
    )

    with pytest.raises(RuntimeError, match="synthetic adapter failure"):
        upload_csv(
            client,
            "transaction_date,description,amount\n2026-01-03,Example,-1.00\n",
        )

    assert session.scalar(select(func.count()).select_from(ImportBatch)) == 0
    assert session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_missing_required_columns_are_rejected_without_persistence(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    response = upload_csv(client, "transaction_date,amount\n2026-01-03,-82.45\n")

    assert response.status_code == 422
    assert response.json() == {"detail": "CSV headers do not match a supported format"}
    assert session.scalar(select(func.count()).select_from(ImportBatch)) == 0
    assert session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_invalid_amount_is_rejected(client_and_session: tuple[TestClient, Session]) -> None:
    client, session = client_and_session
    response = upload_csv(
        client,
        CSV_HEADER + "2026-01-03,2026-01-04,Example Grocery Store,not-a-number,Checking\n",
    )

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["errors"][0]["field"] == "amount"
    assert response.json()["errors"][0]["row_number"] == 2
    assert session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_invalid_date_is_rejected(client_and_session: tuple[TestClient, Session]) -> None:
    client, _ = client_and_session
    response = upload_csv(
        client,
        CSV_HEADER + "01/03/2026,2026-01-04,Example Grocery Store,-82.45,Checking\n",
    )

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["errors"][0]["field"] == "transaction_date"
    assert response.json()["errors"][0]["message"] == ("must be a valid date in YYYY-MM-DD format")


def test_blank_description_is_rejected(client_and_session: tuple[TestClient, Session]) -> None:
    client, _ = client_and_session
    response = upload_csv(
        client,
        CSV_HEADER + "2026-01-03,2026-01-04,   ,-82.45,Checking\n",
    )

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["errors"][0]["field"] == "description"


def test_mixed_valid_and_invalid_rows_are_tracked(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    response = upload_csv(
        client,
        CSV_HEADER + VALID_ROW + "2026-02-30,,Invalid Date,10.00,Checking\n",
    )

    assert response.status_code == 201
    assert response.json()["status"] == "completed_with_errors"
    assert response.json()["total_rows"] == 2
    assert response.json()["imported_rows"] == 1
    assert response.json()["rejected_rows"] == 1
    assert response.json()["errors"][0]["row_number"] == 3

    batch = session.scalar(select(ImportBatch))
    assert batch is not None
    assert batch.status is ImportStatus.COMPLETED_WITH_ERRORS
    assert batch.imported_count == 1
    assert batch.rejected_count == 1
    assert session.scalar(select(func.count()).select_from(Transaction)) == 1


def test_empty_csv_is_rejected_without_persistence(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    response = upload_csv(client, "")

    assert response.status_code == 422
    assert response.json() == {"detail": "CSV file has no header row"}
    assert session.scalar(select(func.count()).select_from(ImportBatch)) == 0


def test_header_only_canonical_csv_creates_failed_batch(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    response = upload_csv(client, CSV_HEADER)

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["adapter_name"] == "canonical_csv"
    assert response.json()["total_rows"] == 0
    assert response.json()["errors"][0]["message"] == "CSV contains no transaction rows"
    assert session.scalar(select(func.count()).select_from(ImportBatch)) == 1


def test_unsupported_file_type_is_rejected_without_batch(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    response = upload_csv(
        client,
        CSV_HEADER + VALID_ROW,
        filename="synthetic-transactions.txt",
        content_type="text/plain",
    )

    assert response.status_code == 415
    assert session.scalar(select(func.count()).select_from(ImportBatch)) == 0


def test_amount_with_excess_precision_is_rejected(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    response = upload_csv(
        client,
        CSV_HEADER + "2026-01-03,,Precision Test,1.234,Checking\n",
    )

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["errors"][0]["field"] == "amount"
    assert session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_oversized_upload_is_rejected_without_batch(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="sqlite+pysqlite:///:memory:",
        max_upload_size_bytes=16,
    )

    response = upload_csv(client, CSV_HEADER + VALID_ROW)

    assert response.status_code == 413
    assert session.scalar(select(func.count()).select_from(ImportBatch)) == 0


def test_database_error_rolls_back_batch_and_transactions(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session

    def fail_flush(*_args: object) -> None:
        raise RuntimeError("synthetic database failure")

    event.listen(session, "before_flush", fail_flush)
    with pytest.raises(RuntimeError, match="synthetic database failure"):
        upload_csv(client, CSV_HEADER + VALID_ROW)
    event.remove(session, "before_flush", fail_flush)

    assert session.scalar(select(func.count()).select_from(ImportBatch)) == 0
    assert session.scalar(select(func.count()).select_from(Transaction)) == 0


def test_adapter_cannot_ignore_more_rows_than_the_document() -> None:
    identity = AdapterIdentity(name="synthetic_format", version="1")
    result = AdapterNormalizationResult(
        adapter=identity,
        ignored_row_count=2,
    )

    with pytest.raises(AdapterContractError, match="ignored more rows"):
        validate_adapter_result(
            result,
            expected_adapter=identity,
            total_rows=1,
        )
