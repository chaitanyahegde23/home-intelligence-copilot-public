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


def get_transactions(client: TestClient, query: str = "") -> Response:
    return cast(Response, client.get(f"/transactions{query}"))


def seed_transactions(session: Session) -> tuple[ImportBatch, ImportBatch]:
    first_batch = ImportBatch(filename="synthetic-first.csv")
    second_batch = ImportBatch(filename="synthetic-second.csv")
    session.add_all(
        [
            Transaction(
                id=UUID(int=1),
                import_batch=first_batch,
                transaction_date=date(2026, 1, 1),
                description="Opening groceries",
                merchant_name="Example Market",
                amount=Decimal("-10.00"),
                account_name="Sample Checking",
                category="Groceries",
                source_file="synthetic-first.csv",
            ),
            Transaction(
                id=UUID(int=2),
                import_batch=first_batch,
                transaction_date=date(2026, 1, 3),
                description="Example coffee",
                merchant_name="Example Cafe",
                amount=Decimal("-5.25"),
                account_name="Sample Card",
                category="Dining",
                source_file="synthetic-first.csv",
            ),
            Transaction(
                id=UUID(int=3),
                import_batch=first_batch,
                transaction_date=date(2026, 1, 3),
                description="Example hardware",
                merchant_name="Example Hardware",
                amount=Decimal("-25.00"),
                account_name="Sample Card",
                category="Home",
                source_file="synthetic-first.csv",
            ),
            Transaction(
                id=UUID(int=4),
                import_batch=second_batch,
                transaction_date=date(2026, 1, 5),
                description="Example salary",
                merchant_name="Example Employer",
                amount=Decimal("1000.00"),
                account_name="Sample Checking",
                category="Income",
                source_file="synthetic-second.csv",
            ),
            Transaction(
                id=UUID(int=5),
                import_batch=second_batch,
                transaction_date=date(2026, 1, 10),
                description="Later groceries",
                merchant_name="Example Market",
                amount=Decimal("-30.00"),
                account_name="Sample Checking",
                category="Groceries",
                source_file="synthetic-second.csv",
            ),
        ]
    )
    session.commit()
    return first_batch, second_batch


def descriptions(response: Response) -> list[str]:
    return [item["description"] for item in response.json()["items"]]


def test_empty_transaction_list(client_and_session: tuple[TestClient, Session]) -> None:
    client, _ = client_and_session

    response = get_transactions(client)

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "pagination": {
            "total": 0,
            "offset": 0,
            "limit": 50,
            "returned": 0,
            "has_more": False,
        },
        "summary": {
            "currency": "USD",
            "transaction_count": 0,
            "gross_amount": "0.00",
            "spending_amount": "0.00",
            "income_amount": "0.00",
            "net_amount": "0.00",
        },
    }


def test_default_order_is_newest_date_then_uuid(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_transactions(session)

    response = get_transactions(client)

    assert response.status_code == 200
    assert descriptions(response) == [
        "Later groceries",
        "Example salary",
        "Example hardware",
        "Example coffee",
        "Opening groceries",
    ]


def test_pagination_metadata_and_boundaries(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_transactions(session)

    middle = get_transactions(client, "?limit=2&offset=1")
    end = get_transactions(client, "?limit=2&offset=5")

    assert descriptions(middle) == ["Example salary", "Example hardware"]
    assert middle.json()["pagination"] == {
        "total": 5,
        "offset": 1,
        "limit": 2,
        "returned": 2,
        "has_more": True,
    }
    assert end.json()["items"] == []
    assert end.json()["pagination"]["has_more"] is False
    assert end.json()["pagination"]["total"] == 5
    assert middle.json()["summary"] == {
        "currency": "USD",
        "transaction_count": 5,
        "gross_amount": "1070.25",
        "spending_amount": "70.25",
        "income_amount": "1000.00",
        "net_amount": "929.75",
    }


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("?start_date=2026-01-05", ["Later groceries", "Example salary"]),
        ("?end_date=2026-01-01", ["Opening groceries"]),
        ("?account_name=Sample%20Card", ["Example hardware", "Example coffee"]),
        ("?category=Groceries", ["Later groceries", "Opening groceries"]),
        ("?merchant_name=Example%20Market", ["Later groceries", "Opening groceries"]),
    ],
)
def test_individual_filters(
    client_and_session: tuple[TestClient, Session],
    query: str,
    expected: list[str],
) -> None:
    client, session = client_and_session
    seed_transactions(session)

    response = get_transactions(client, query)

    assert response.status_code == 200
    assert descriptions(response) == expected


def test_date_filters_are_inclusive_and_can_be_combined(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_transactions(session)

    response = get_transactions(
        client,
        "?start_date=2026-01-03&end_date=2026-01-03&account_name=Sample%20Card&category=Home",
    )

    assert response.status_code == 200
    assert descriptions(response) == ["Example hardware"]


def test_import_batch_filter(client_and_session: tuple[TestClient, Session]) -> None:
    client, session = client_and_session
    _, second_batch = seed_transactions(session)

    response = get_transactions(client, f"?import_batch_id={second_batch.id}")

    assert response.status_code == 200
    assert descriptions(response) == ["Later groceries", "Example salary"]


def test_summary_uses_all_matching_rows_and_reconciles_filtered_decimals(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_transactions(session)

    response = get_transactions(client, "?category=Groceries&limit=1")

    assert response.status_code == 200
    assert response.json()["pagination"]["returned"] == 1
    assert response.json()["summary"] == {
        "currency": "USD",
        "transaction_count": 2,
        "gross_amount": "40.00",
        "spending_amount": "40.00",
        "income_amount": "0.00",
        "net_amount": "-40.00",
    }


def test_transaction_list_exposes_current_category_assignment_provenance(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_transactions(session)
    category = client.post("/categories", json={"name": "Household supplies"})
    assert category.status_code == 201

    assignment = client.put(
        f"/transactions/{UUID(int=1)}/category-assignment",
        json={"category_id": category.json()["id"], "note": "Synthetic review"},
    )
    response = get_transactions(client, "?merchant_name=Example%20Market")

    assert assignment.status_code == 200
    item = next(item for item in response.json()["items"] if item["id"] == str(UUID(int=1)))
    assert item["category"] == "Household supplies"
    assert item["category_assignment"]["source"] == "manual"
    assert item["category_assignment"]["note"] == "Synthetic review"


@pytest.mark.parametrize(
    "query",
    [
        "?start_date=2026-01-10&end_date=2026-01-01",
        "?import_batch_id=not-a-uuid",
        "?limit=0",
        "?limit=101",
        "?offset=-1",
        "?category=%20%20%20",
    ],
)
def test_invalid_query_parameters_return_422(
    client_and_session: tuple[TestClient, Session],
    query: str,
) -> None:
    client, _ = client_and_session

    response = get_transactions(client, query)

    assert response.status_code == 422


def test_maximum_limit_and_decimal_safe_response(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_transactions(session)

    response = get_transactions(client, "?limit=100")

    assert response.status_code == 200
    assert response.json()["pagination"]["limit"] == 100
    amount = response.json()["items"][0]["amount"]
    assert isinstance(amount, str)
    assert Decimal(amount) == Decimal("-30.00")
