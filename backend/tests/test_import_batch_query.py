from collections.abc import Iterator
from datetime import UTC, datetime
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
from app.models import ImportBatch
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


def get_imports(client: TestClient, query: str = "") -> Response:
    return cast(Response, client.get(f"/imports{query}"))


def seed_import_batches(session: Session) -> None:
    session.add_all(
        [
            ImportBatch(
                id=UUID(int=1),
                filename="synthetic-oldest.csv",
                status=ImportStatus.COMPLETED,
                row_count=3,
                imported_count=3,
                rejected_count=0,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            ImportBatch(
                id=UUID(int=2),
                filename="synthetic-failed.csv",
                status=ImportStatus.FAILED,
                row_count=2,
                imported_count=0,
                rejected_count=2,
                created_at=datetime(2026, 1, 2, tzinfo=UTC),
                updated_at=datetime(2026, 1, 2, tzinfo=UTC),
            ),
            ImportBatch(
                id=UUID(int=3),
                filename="synthetic-tied-lower.csv",
                status=ImportStatus.COMPLETED_WITH_ERRORS,
                row_count=4,
                imported_count=3,
                rejected_count=1,
                created_at=datetime(2026, 1, 3, tzinfo=UTC),
                updated_at=datetime(2026, 1, 3, tzinfo=UTC),
            ),
            ImportBatch(
                id=UUID(int=4),
                filename="synthetic-tied-higher.csv",
                status=ImportStatus.COMPLETED,
                row_count=5,
                imported_count=5,
                rejected_count=0,
                created_at=datetime(2026, 1, 3, tzinfo=UTC),
                updated_at=datetime(2026, 1, 3, tzinfo=UTC),
            ),
        ]
    )
    session.commit()


def filenames(response: Response) -> list[str]:
    return [item["filename"] for item in response.json()["items"]]


def test_empty_import_history(client_and_session: tuple[TestClient, Session]) -> None:
    client, _ = client_and_session

    response = get_imports(client)

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
    }


def test_history_is_newest_first_with_uuid_tie_breaker(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_import_batches(session)

    response = get_imports(client)

    assert response.status_code == 200
    assert filenames(response) == [
        "synthetic-tied-higher.csv",
        "synthetic-tied-lower.csv",
        "synthetic-failed.csv",
        "synthetic-oldest.csv",
    ]


def test_history_returns_counts_status_and_timestamps(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_import_batches(session)

    response = get_imports(client)
    item = response.json()["items"][0]

    assert item["filename"] == "synthetic-tied-higher.csv"
    assert item["adapter_name"] == "canonical_csv"
    assert item["adapter_version"] == "1"
    assert item["account_label"] is None
    assert item["status"] == "completed"
    assert item["row_count"] == 5
    assert item["imported_count"] == 5
    assert item["rejected_count"] == 0
    assert datetime.fromisoformat(item["created_at"])
    assert datetime.fromisoformat(item["updated_at"])
    assert "transactions" not in item


def test_history_pagination_metadata_and_boundaries(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_import_batches(session)

    middle = get_imports(client, "?limit=2&offset=1")
    end = get_imports(client, "?limit=2&offset=4")

    assert filenames(middle) == ["synthetic-tied-lower.csv", "synthetic-failed.csv"]
    assert middle.json()["pagination"] == {
        "total": 4,
        "offset": 1,
        "limit": 2,
        "returned": 2,
        "has_more": True,
    }
    assert end.json()["items"] == []
    assert end.json()["pagination"] == {
        "total": 4,
        "offset": 4,
        "limit": 2,
        "returned": 0,
        "has_more": False,
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("completed", ["synthetic-tied-higher.csv", "synthetic-oldest.csv"]),
        ("completed_with_errors", ["synthetic-tied-lower.csv"]),
        ("failed", ["synthetic-failed.csv"]),
        ("pending", []),
        ("processing", []),
    ],
)
def test_status_filter(
    client_and_session: tuple[TestClient, Session],
    status: str,
    expected: list[str],
) -> None:
    client, session = client_and_session
    seed_import_batches(session)

    response = get_imports(client, f"?status={status}")

    assert response.status_code == 200
    assert filenames(response) == expected
    assert response.json()["pagination"]["total"] == len(expected)


@pytest.mark.parametrize(
    "query",
    [
        "?status=unknown",
        "?limit=0",
        "?limit=101",
        "?offset=-1",
    ],
)
def test_invalid_query_parameters_return_422(
    client_and_session: tuple[TestClient, Session],
    query: str,
) -> None:
    client, _ = client_and_session

    response = get_imports(client, query)

    assert response.status_code == 422


def test_maximum_limit_is_accepted(client_and_session: tuple[TestClient, Session]) -> None:
    client, session = client_and_session
    seed_import_batches(session)

    response = get_imports(client, "?limit=100")

    assert response.status_code == 200
    assert response.json()["pagination"]["limit"] == 100
