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


def get_breakdown(client: TestClient, query: str) -> Response:
    return cast(Response, client.get(f"/analytics/spending/by-category?{query}"))


def add_transaction(
    session: Session,
    *,
    batch: ImportBatch,
    transaction_id: int,
    transaction_date: date,
    amount: str,
    category: str | None,
    account_name: str | None = None,
) -> None:
    session.add(
        Transaction(
            id=UUID(int=transaction_id),
            import_batch=batch,
            transaction_date=transaction_date,
            description=f"Synthetic transaction {transaction_id}",
            amount=Decimal(amount),
            account_name=account_name,
            category=category,
            source_file=batch.filename,
        )
    )


def seed_category_example(session: Session) -> None:
    batch = ImportBatch(
        filename="synthetic-category-analytics.csv",
        status=ImportStatus.COMPLETED,
        row_count=6,
        imported_count=6,
    )
    values = [
        (1, date(2026, 1, 1), "-82.45", "Groceries", "Sample Checking"),
        (2, date(2026, 1, 2), "2500.00", "Income", "Sample Checking"),
        (3, date(2026, 1, 3), "20.00", "Groceries", "Sample Checking"),
        (4, date(2026, 1, 4), "-1200.00", "Housing", "Sample Checking"),
        (5, date(2026, 1, 5), "-500.00", None, "Sample Savings"),
        (6, date(2026, 1, 5), "0.00", None, "Sample Checking"),
    ]
    for transaction_id, transaction_date, amount, category, account_name in values:
        add_transaction(
            session,
            batch=batch,
            transaction_id=transaction_id,
            transaction_date=transaction_date,
            amount=amount,
            category=category,
            account_name=account_name,
        )
    session.commit()


def test_category_breakdown_matches_versioned_spending_semantics(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_category_example(session)

    response = get_breakdown(
        client,
        "start_date=2026-01-01&end_date=2026-01-05",
    )

    assert response.status_code == 200
    assert response.json() == {
        "semantics_version": "1.0",
        "metric": "gross_spending_by_category",
        "currency": "USD",
        "applied_filters": {
            "start_date": "2026-01-01",
            "end_date": "2026-01-05",
            "account_name": None,
        },
        "total_spending": "1782.45",
        "transaction_count": 3,
        "groups": [
            {
                "category": "Housing",
                "bucket": "category",
                "total_spending": "1200.00",
                "transaction_count": 1,
                "percentage": "67.32",
            },
            {
                "category": None,
                "bucket": "uncategorized",
                "total_spending": "500.00",
                "transaction_count": 1,
                "percentage": "28.05",
            },
            {
                "category": "Groceries",
                "bucket": "category",
                "total_spending": "82.45",
                "transaction_count": 1,
                "percentage": "4.63",
            },
        ],
    }


def test_empty_breakdown_has_zero_totals_and_no_groups(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_category_example(session)

    response = get_breakdown(
        client,
        "start_date=2025-01-01&end_date=2025-01-31",
    )

    assert response.status_code == 200
    assert response.json()["total_spending"] == "0.00"
    assert response.json()["transaction_count"] == 0
    assert response.json()["groups"] == []


def test_null_and_real_uncategorized_categories_remain_distinct(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    batch = ImportBatch(filename="synthetic-buckets.csv", status=ImportStatus.COMPLETED)
    add_transaction(
        session,
        batch=batch,
        transaction_id=10,
        transaction_date=date(2026, 2, 1),
        amount="-20.00",
        category="Uncategorized",
    )
    add_transaction(
        session,
        batch=batch,
        transaction_id=11,
        transaction_date=date(2026, 2, 1),
        amount="-10.00",
        category=None,
    )
    session.commit()

    response = get_breakdown(
        client,
        "start_date=2026-02-01&end_date=2026-02-01",
    )

    assert response.status_code == 200
    assert [(group["category"], group["bucket"]) for group in response.json()["groups"]] == [
        ("Uncategorized", "category"),
        (None, "uncategorized"),
    ]


def test_equal_totals_use_stable_category_order_with_null_last(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    batch = ImportBatch(filename="synthetic-ties.csv", status=ImportStatus.COMPLETED)
    for transaction_id, category in enumerate(
        ["Groceries", None, "Dining"],
        start=20,
    ):
        add_transaction(
            session,
            batch=batch,
            transaction_id=transaction_id,
            transaction_date=date(2026, 3, 1),
            amount="-10.00",
            category=category,
        )
    session.commit()

    response = get_breakdown(
        client,
        "start_date=2026-03-01&end_date=2026-03-01",
    )

    assert response.status_code == 200
    assert [group["category"] for group in response.json()["groups"]] == [
        "Dining",
        "Groceries",
        None,
    ]


def test_percentages_use_decimal_and_round_half_up(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    batch = ImportBatch(
        filename="synthetic-percentage.csv",
        status=ImportStatus.COMPLETED,
    )
    add_transaction(
        session,
        batch=batch,
        transaction_id=30,
        transaction_date=date(2026, 4, 1),
        amount="-0.31",
        category="Large",
    )
    add_transaction(
        session,
        batch=batch,
        transaction_id=31,
        transaction_date=date(2026, 4, 1),
        amount="-0.01",
        category="Small",
    )
    session.commit()

    response = get_breakdown(
        client,
        "start_date=2026-04-01&end_date=2026-04-01",
    )

    assert response.status_code == 200
    assert response.json()["total_spending"] == "0.32"
    assert [group["percentage"] for group in response.json()["groups"]] == ["96.88", "3.13"]


def test_account_filter_is_exact_trimmed_and_echoed(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_category_example(session)

    response = get_breakdown(
        client,
        "start_date=2026-01-01&end_date=2026-01-05&account_name=%20Sample%20Checking%20",
    )

    assert response.status_code == 200
    assert response.json()["total_spending"] == "1282.45"
    assert response.json()["transaction_count"] == 2
    assert response.json()["applied_filters"]["account_name"] == "Sample Checking"
    assert [group["category"] for group in response.json()["groups"]] == [
        "Housing",
        "Groceries",
    ]


def test_group_totals_and_counts_reconcile_to_summary(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_category_example(session)
    query = "start_date=2026-01-01&end_date=2026-01-05&account_name=Sample%20Checking"

    breakdown = get_breakdown(client, query)
    summary = client.get(f"/analytics/spending/summary?{query}")

    assert breakdown.status_code == 200
    assert summary.status_code == 200
    result = breakdown.json()
    assert result["total_spending"] == summary.json()["total_spending"]
    assert result["transaction_count"] == summary.json()["transaction_count"]
    assert sum(
        (Decimal(group["total_spending"]) for group in result["groups"]),
        Decimal("0.00"),
    ) == Decimal(result["total_spending"])
    assert (
        sum(group["transaction_count"] for group in result["groups"])
        == (result["transaction_count"])
    )


def test_date_boundaries_are_inclusive_and_non_spending_is_excluded(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_category_example(session)

    first_day = get_breakdown(
        client,
        "start_date=2026-01-01&end_date=2026-01-01",
    )
    last_day = get_breakdown(
        client,
        "start_date=2026-01-05&end_date=2026-01-05",
    )

    assert first_day.json()["total_spending"] == "82.45"
    assert last_day.json()["total_spending"] == "500.00"
    assert last_day.json()["transaction_count"] == 1


@pytest.mark.parametrize(
    "query",
    [
        "start_date=2026-01-05&end_date=2026-01-01",
        "start_date=2026-01-01",
        "end_date=2026-01-31",
        "start_date=2026-01-01&end_date=2026-01-31&account_name=%20%20",
        "start_date=2026-01-01&end_date=2026-01-31&category=Groceries",
        "start_date=2026-01-01&end_date=2026-01-31&merchant_name=Example",
    ],
)
def test_invalid_or_unsupported_query_parameters_return_422(
    client_and_session: tuple[TestClient, Session],
    query: str,
) -> None:
    client, _ = client_and_session

    response = get_breakdown(client, query)

    assert response.status_code == 422
