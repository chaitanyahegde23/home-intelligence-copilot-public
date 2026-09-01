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
from app.models.import_batch import ImportStatus


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


def get_summary(client: TestClient, query: str) -> Response:
    return cast(Response, client.get(f"/analytics/spending/summary?{query}"))


def add_transaction(
    session: Session,
    *,
    batch: ImportBatch,
    transaction_id: int,
    transaction_date: date,
    description: str,
    amount: str,
    account_name: str | None = None,
    category: str | None = None,
    transaction_type: str | None = None,
) -> None:
    session.add(
        Transaction(
            id=UUID(int=transaction_id),
            import_batch=batch,
            transaction_date=transaction_date,
            description=description,
            amount=Decimal(amount),
            account_name=account_name,
            category=category,
            transaction_type=transaction_type,
            source_file=batch.filename,
        )
    )


def seed_semantics_example(session: Session) -> None:
    batch = ImportBatch(
        filename="synthetic-analytics.csv",
        status=ImportStatus.COMPLETED,
        row_count=6,
        imported_count=6,
    )
    add_transaction(
        session,
        batch=batch,
        transaction_id=1,
        transaction_date=date(2026, 1, 1),
        description="Example Grocery Store",
        amount="-82.45",
        account_name="Sample Checking",
        category="Groceries",
    )
    add_transaction(
        session,
        batch=batch,
        transaction_id=2,
        transaction_date=date(2026, 1, 2),
        description="Example Employer",
        amount="2500.00",
        account_name="Sample Checking",
        category="Income",
    )
    add_transaction(
        session,
        batch=batch,
        transaction_id=3,
        transaction_date=date(2026, 1, 3),
        description="Example Grocery Refund",
        amount="20.00",
        account_name="Sample Checking",
        category="Groceries",
    )
    add_transaction(
        session,
        batch=batch,
        transaction_id=4,
        transaction_date=date(2026, 1, 4),
        description="Example Rent",
        amount="-1200.00",
        account_name="Sample Checking",
        category="Housing",
    )
    add_transaction(
        session,
        batch=batch,
        transaction_id=5,
        transaction_date=date(2026, 1, 5),
        description="Example Account Transfer",
        amount="-500.00",
        account_name="Sample Savings",
        transaction_type="transfer",
    )
    add_transaction(
        session,
        batch=batch,
        transaction_id=6,
        transaction_date=date(2026, 1, 5),
        description="Example Zero Authorization",
        amount="0.00",
        account_name="Sample Checking",
    )
    session.commit()


def test_summary_matches_versioned_gross_spending_semantics(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_semantics_example(session)

    response = get_summary(client, "start_date=2026-01-01&end_date=2026-01-05")

    assert response.status_code == 200
    assert response.json() == {
        "semantics_version": "1.0",
        "metric": "gross_spending",
        "currency": "USD",
        "applied_filters": {
            "start_date": "2026-01-01",
            "end_date": "2026-01-05",
            "account_name": None,
            "category": None,
        },
        "total_spending": "1782.45",
        "transaction_count": 3,
    }


def test_empty_valid_range_returns_exact_zero(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_semantics_example(session)

    response = get_summary(client, "start_date=2025-01-01&end_date=2025-01-31")

    assert response.status_code == 200
    assert response.json()["total_spending"] == "0.00"
    assert response.json()["transaction_count"] == 0


def test_date_boundaries_are_inclusive(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_semantics_example(session)

    first_day = get_summary(client, "start_date=2026-01-01&end_date=2026-01-01")
    last_day = get_summary(client, "start_date=2026-01-05&end_date=2026-01-05")

    assert first_day.json()["total_spending"] == "82.45"
    assert first_day.json()["transaction_count"] == 1
    assert last_day.json()["total_spending"] == "500.00"
    assert last_day.json()["transaction_count"] == 1


def test_income_refunds_and_zero_are_excluded(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_semantics_example(session)

    response = get_summary(client, "start_date=2026-01-02&end_date=2026-01-03")

    assert response.status_code == 200
    assert response.json()["total_spending"] == "0.00"
    assert response.json()["transaction_count"] == 0


@pytest.mark.parametrize(
    ("filter_query", "expected_total", "expected_count"),
    [
        ("account_name=Sample%20Checking", "1282.45", 2),
        ("account_name=Sample%20Savings", "500.00", 1),
        ("category=Groceries", "82.45", 1),
        ("category=Housing", "1200.00", 1),
        ("category=groceries", "0.00", 0),
        ("category=Uncategorized", "0.00", 0),
    ],
)
def test_exact_account_and_category_filters(
    client_and_session: tuple[TestClient, Session],
    filter_query: str,
    expected_total: str,
    expected_count: int,
) -> None:
    client, session = client_and_session
    seed_semantics_example(session)

    response = get_summary(
        client,
        f"start_date=2026-01-01&end_date=2026-01-05&{filter_query}",
    )

    assert response.status_code == 200
    assert response.json()["total_spending"] == expected_total
    assert response.json()["transaction_count"] == expected_count


def test_filters_combine_with_logical_and_and_are_echoed(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_semantics_example(session)

    response = get_summary(
        client,
        "start_date=2026-01-01&end_date=2026-01-05"
        "&account_name=%20Sample%20Checking%20&category=Housing",
    )

    assert response.status_code == 200
    assert response.json()["total_spending"] == "1200.00"
    assert response.json()["transaction_count"] == 1
    assert response.json()["applied_filters"]["account_name"] == "Sample Checking"
    assert response.json()["applied_filters"]["category"] == "Housing"


def test_decimal_aggregation_is_exact(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    batch = ImportBatch(filename="synthetic-cents.csv", status=ImportStatus.COMPLETED)
    for index in range(1, 101):
        add_transaction(
            session,
            batch=batch,
            transaction_id=1000 + index,
            transaction_date=date(2026, 2, 1),
            description=f"Synthetic cent {index}",
            amount="-0.01",
        )
    session.commit()

    response = get_summary(client, "start_date=2026-02-01&end_date=2026-02-01")

    assert response.status_code == 200
    assert response.json()["total_spending"] == "1.00"
    assert response.json()["transaction_count"] == 100


def test_possible_transfer_and_duplicate_are_included(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_semantics_example(session)
    batch = ImportBatch(filename="synthetic-duplicate.csv", status=ImportStatus.COMPLETED)
    add_transaction(
        session,
        batch=batch,
        transaction_id=200,
        transaction_date=date(2026, 1, 5),
        description="Duplicate-looking grocery",
        amount="-82.45",
        account_name="Sample Checking",
        category="Groceries",
    )
    session.commit()

    response = get_summary(client, "start_date=2026-01-05&end_date=2026-01-05")

    assert response.status_code == 200
    assert response.json()["total_spending"] == "582.45"
    assert response.json()["transaction_count"] == 2


def test_valid_transaction_from_partial_batch_is_included(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    batch = ImportBatch(
        filename="synthetic-partial.csv",
        status=ImportStatus.COMPLETED_WITH_ERRORS,
        row_count=2,
        imported_count=1,
        rejected_count=1,
    )
    add_transaction(
        session,
        batch=batch,
        transaction_id=300,
        transaction_date=date(2026, 3, 1),
        description="Synthetic accepted row",
        amount="-10.00",
    )
    session.commit()

    response = get_summary(client, "start_date=2026-03-01&end_date=2026-03-01")

    assert response.status_code == 200
    assert response.json()["total_spending"] == "10.00"
    assert response.json()["transaction_count"] == 1


@pytest.mark.parametrize(
    "query",
    [
        "start_date=2026-01-05&end_date=2026-01-01",
        "start_date=2026-01-01",
        "end_date=2026-01-31",
        "start_date=2026-01-01&end_date=2026-01-31&category=%20%20%20",
        "start_date=2026-01-01&end_date=2026-01-31&merchant_name=Example",
    ],
)
def test_invalid_or_unsupported_query_parameters_return_422(
    client_and_session: tuple[TestClient, Session],
    query: str,
) -> None:
    client, _ = client_and_session

    response = get_summary(client, query)

    assert response.status_code == 422
