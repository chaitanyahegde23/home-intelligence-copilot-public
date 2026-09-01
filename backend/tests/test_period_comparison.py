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
    return cast(Response, client.get(f"/analytics/spending/compare?{query}"))


def query(
    current: tuple[str, str] = ("2026-02-01", "2026-02-28"),
    comparison: tuple[str, str] = ("2026-01-01", "2026-01-31"),
) -> str:
    return (
        f"current_start_date={current[0]}&current_end_date={current[1]}"
        f"&comparison_start_date={comparison[0]}&comparison_end_date={comparison[1]}"
    )


def add(
    session: Session,
    batch: ImportBatch,
    transaction_id: int,
    transaction_date: date,
    amount: str,
    category: str | None,
    account: str = "Sample Checking",
) -> None:
    session.add(
        Transaction(
            id=UUID(int=transaction_id),
            import_batch=batch,
            transaction_date=transaction_date,
            description=f"Synthetic transaction {transaction_id}",
            amount=Decimal(amount),
            category=category,
            account_name=account,
            source_file=batch.filename,
        )
    )


def seed(session: Session) -> None:
    batch = ImportBatch(filename="synthetic-comparison.csv")
    rows = [
        (1, date(2026, 1, 1), "-10.00", "Groceries", "Sample Checking"),
        (2, date(2026, 1, 31), "-20.00", "Housing", "Sample Checking"),
        (3, date(2026, 2, 1), "-15.00", "Groceries", "Sample Checking"),
        (4, date(2026, 2, 28), "-30.00", "Dining", "Sample Checking"),
        (5, date(2026, 2, 28), "-5.00", None, "Sample Savings"),
        (6, date(2026, 2, 15), "100.00", "Refund", "Sample Checking"),
        (7, date(2026, 3, 1), "-30.00", "Groceries", "Sample Checking"),
    ]
    for values in rows:
        add(session, batch, *values)
    session.commit()


def test_exact_totals_percentage_and_reconciling_category_deltas(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed(session)

    response = request(client, query())

    assert response.status_code == 200
    result = response.json()
    assert result["metric"] == "gross_spending_period_comparison"
    assert result["current_period"]["total_spending"] == "50.00"
    assert result["current_period"]["transaction_count"] == 3
    assert result["comparison_period"]["total_spending"] == "30.00"
    assert result["absolute_change"] == "20.00"
    assert result["percentage_change"] == "66.67"
    assert [item["category"] for item in result["category_deltas"]] == [
        "Dining",
        "Housing",
        "Groceries",
        None,
    ]
    assert sum(
        (Decimal(item["absolute_change"]) for item in result["category_deltas"]),
        Decimal("0.00"),
    ) == Decimal("20.00")


@pytest.mark.parametrize(
    ("current", "comparison", "change", "percentage"),
    [
        (("2026-02-01", "2026-02-28"), ("2026-01-01", "2026-01-31"), "20.00", "66.67"),
        (("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-28"), "-20.00", "-40.00"),
        (("2026-03-01", "2026-03-31"), ("2026-01-01", "2026-01-31"), "0.00", "0.00"),
    ],
)
def test_higher_lower_and_equal_periods(
    client_and_session: tuple[TestClient, Session],
    current: tuple[str, str],
    comparison: tuple[str, str],
    change: str,
    percentage: str,
) -> None:
    client, session = client_and_session
    seed(session)

    result = request(client, query(current, comparison)).json()

    assert result["absolute_change"] == change
    assert result["percentage_change"] == percentage


def test_empty_baseline_returns_null_percentage(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed(session)

    result = request(client, query(comparison=("2025-01-01", "2025-01-31"))).json()

    assert result["comparison_period"]["total_spending"] == "0.00"
    assert result["absolute_change"] == "50.00"
    assert result["percentage_change"] is None


def test_account_filter_and_inclusive_boundaries(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed(session)

    filtered = request(client, query() + "&account_name=%20Sample%20Checking%20").json()
    boundary = request(
        client,
        query(("2026-02-28", "2026-02-28"), ("2026-01-31", "2026-01-31")),
    ).json()

    assert filtered["applied_filters"]["account_name"] == "Sample Checking"
    assert filtered["current_period"]["total_spending"] == "45.00"
    assert filtered["absolute_change"] == "15.00"
    assert boundary["current_period"]["total_spending"] == "35.00"
    assert boundary["comparison_period"]["total_spending"] == "20.00"


def test_decimal_precision_and_round_half_up(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    batch = ImportBatch(filename="synthetic-precision.csv")
    for transaction_id in range(100, 200):
        add(session, batch, transaction_id, date(2026, 6, 1), "-0.01", "Synthetic")
    add(session, batch, 200, date(2026, 5, 1), "-0.30", "Synthetic")
    session.commit()

    result = request(
        client,
        query(("2026-06-01", "2026-06-01"), ("2026-05-01", "2026-05-01")),
    ).json()

    assert result["current_period"]["total_spending"] == "1.00"
    assert result["absolute_change"] == "0.70"
    assert result["percentage_change"] == "233.33"


@pytest.mark.parametrize(
    "invalid_query",
    [
        query(("2026-02-02", "2026-02-01")),
        query(comparison=("2026-01-02", "2026-01-01")),
        "current_start_date=2026-02-01&current_end_date=2026-02-28",
        query() + "&account_name=%20%20",
        query() + "&category=Groceries",
    ],
)
def test_invalid_queries_return_422(
    client_and_session: tuple[TestClient, Session], invalid_query: str
) -> None:
    client, _ = client_and_session

    assert request(client, invalid_query).status_code == 422
