from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import ImportBatch, Transaction


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

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as client:
            yield client, session
        app.dependency_overrides.clear()
    engine.dispose()


def request(client: TestClient, query: str) -> Response:
    return cast(Response, client.get(f"/analytics/spending/large-transactions?{query}"))


def base_query(threshold: str = "100.00") -> str:
    return f"start_date=2026-01-01&end_date=2026-01-31&threshold={threshold}"


def add(
    session: Session,
    batch: ImportBatch,
    transaction_id: int,
    transaction_date: date,
    amount: str,
    category: str | None,
    account_name: str,
) -> None:
    session.add(
        Transaction(
            id=UUID(int=transaction_id),
            import_batch=batch,
            transaction_date=transaction_date,
            description=f"Synthetic large transaction {transaction_id}",
            merchant_name=f"Synthetic Merchant {transaction_id}",
            amount=Decimal(amount),
            account_name=account_name,
            category=category,
            source_file=batch.filename,
        )
    )


def seed(session: Session) -> ImportBatch:
    batch = ImportBatch(
        filename="synthetic-large-transactions.csv",
        adapter_name="synthetic_adapter",
        adapter_version="1",
        account_label="Household Card",
    )
    rows = [
        (1, date(2026, 1, 1), "-100.00", "Groceries", "Sample Checking"),
        (2, date(2026, 1, 3), "-250.00", "Housing", "Sample Checking"),
        (3, date(2026, 1, 2), "-100.00", "Groceries", "Sample Checking"),
        (4, date(2026, 1, 2), "-100.00", "Groceries", "Sample Savings"),
        (5, date(2026, 1, 5), "1000.00", "Income", "Sample Checking"),
        (6, date(2026, 1, 6), "0.00", None, "Sample Checking"),
        (7, date(2026, 1, 7), "-99.99", "Dining", "Sample Checking"),
    ]
    for values in rows:
        add(session, batch, *values)
    session.commit()
    return batch


def test_inclusive_threshold_sign_semantics_ordering_and_provenance(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    batch = seed(session)

    response = request(client, base_query())

    assert response.status_code == 200
    result = response.json()
    assert result["metric"] == "large_gross_spending_transactions"
    assert result["currency"] == "USD"
    assert result["total_matching"] == 4
    assert result["returned_count"] == 4
    assert result["has_more"] is False
    assert [item["id"] for item in result["items"]] == [
        str(UUID(int=2)),
        str(UUID(int=4)),
        str(UUID(int=3)),
        str(UUID(int=1)),
    ]
    assert [item["spending_magnitude"] for item in result["items"]] == [
        "250.00",
        "100.00",
        "100.00",
        "100.00",
    ]
    assert result["items"][1]["amount"] == "-100.00"
    provenance = result["items"][0]["import_provenance"]
    assert provenance == {
        "import_batch_id": str(batch.id),
        "filename": "synthetic-large-transactions.csv",
        "adapter_name": "synthetic_adapter",
        "adapter_version": "1",
        "account_label": "Household Card",
    }
    assert result["items"][0]["import_batch_id"] == str(batch.id)
    assert result["items"][0]["source_file"] == batch.filename


def test_account_and_category_filters_combine_exactly(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed(session)

    response = request(
        client,
        base_query() + "&account_name=%20Sample%20Checking%20&category=Groceries",
    )

    assert response.status_code == 200
    result = response.json()
    assert result["total_matching"] == 2
    assert [item["id"] for item in result["items"]] == [
        str(UUID(int=3)),
        str(UUID(int=1)),
    ]
    assert result["applied_filters"]["account_name"] == "Sample Checking"
    assert result["applied_filters"]["category"] == "Groceries"


def test_date_boundaries_are_inclusive(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed(session)

    response = request(
        client,
        "start_date=2026-01-01&end_date=2026-01-01&threshold=100.00",
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(UUID(int=1))]


def test_limit_bounds_results_and_reports_total(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed(session)

    response = request(client, base_query() + "&limit=2")

    assert response.status_code == 200
    result = response.json()
    assert result["total_matching"] == 4
    assert result["returned_count"] == 2
    assert result["has_more"] is True
    assert result["applied_filters"]["limit"] == 2


def test_empty_result_is_explicit(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed(session)

    response = request(client, base_query("500.00"))

    assert response.status_code == 200
    assert response.json()["total_matching"] == 0
    assert response.json()["returned_count"] == 0
    assert response.json()["has_more"] is False
    assert response.json()["items"] == []


@pytest.mark.parametrize(
    "invalid_query",
    [
        "start_date=2026-01-01&end_date=2026-01-31",
        base_query("0.00"),
        base_query("-1.00"),
        base_query("100.001"),
        base_query() + "&limit=0",
        base_query() + "&limit=101",
        base_query() + "&account_name=%20%20",
        base_query() + "&merchant_name=Synthetic",
        "start_date=2026-01-31&end_date=2026-01-01&threshold=100.00",
    ],
)
def test_invalid_queries_return_422(
    client_and_session: tuple[TestClient, Session], invalid_query: str
) -> None:
    client, _ = client_and_session

    assert request(client, invalid_query).status_code == 422
