from collections.abc import Iterator
from datetime import UTC, date, datetime
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


def get_import(client: TestClient, batch_id: UUID | str) -> Response:
    return cast(Response, client.get(f"/imports/{batch_id}"))


def get_transactions(client: TestClient, batch_id: UUID) -> Response:
    return cast(Response, client.get(f"/transactions?import_batch_id={batch_id}"))


def seed_batches(session: Session) -> tuple[ImportBatch, ImportBatch, ImportBatch]:
    completed = ImportBatch(
        id=UUID(int=101),
        filename="synthetic-completed.csv",
        status=ImportStatus.COMPLETED,
        row_count=2,
        imported_count=2,
        rejected_count=0,
        created_at=datetime(2026, 2, 1, tzinfo=UTC),
        updated_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    failed = ImportBatch(
        id=UUID(int=102),
        filename="synthetic-failed.csv",
        status=ImportStatus.FAILED,
        row_count=1,
        imported_count=0,
        rejected_count=1,
        created_at=datetime(2026, 2, 2, tzinfo=UTC),
        updated_at=datetime(2026, 2, 2, tzinfo=UTC),
    )
    partial = ImportBatch(
        id=UUID(int=103),
        filename="synthetic-partial.csv",
        status=ImportStatus.COMPLETED_WITH_ERRORS,
        row_count=2,
        imported_count=1,
        rejected_count=1,
        created_at=datetime(2026, 2, 3, tzinfo=UTC),
        updated_at=datetime(2026, 2, 3, tzinfo=UTC),
    )
    session.add_all(
        [
            completed,
            failed,
            partial,
            Transaction(
                id=UUID(int=201),
                import_batch=completed,
                transaction_date=date(2026, 2, 1),
                description="Synthetic groceries",
                amount=Decimal("-20.00"),
                source_file=completed.filename,
            ),
            Transaction(
                id=UUID(int=202),
                import_batch=completed,
                transaction_date=date(2026, 2, 2),
                description="Synthetic utilities",
                amount=Decimal("-45.00"),
                source_file=completed.filename,
            ),
            Transaction(
                id=UUID(int=203),
                import_batch=partial,
                transaction_date=date(2026, 2, 3),
                description="Synthetic accepted row",
                amount=Decimal("-10.00"),
                source_file=partial.filename,
            ),
        ]
    )
    session.commit()
    return completed, failed, partial


def test_completed_import_batch_detail_returns_metadata_and_transaction_count(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    completed, _, _ = seed_batches(session)

    response = get_import(client, completed.id)

    assert response.status_code == 200
    assert response.json() == {
        "filename": "synthetic-completed.csv",
        "adapter_name": "canonical_csv",
        "adapter_version": "1",
        "account_label": None,
        "status": "completed",
        "row_count": 2,
        "imported_count": 2,
        "rejected_count": 0,
        "id": str(completed.id),
        "created_at": "2026-02-01T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
        "transaction_count": 2,
        "duplicate_candidate_count": 0,
        "transactions_url": f"/transactions?import_batch_id={completed.id}",
        "duplicate_candidates_url": (f"/duplicate-candidates?import_batch_id={completed.id}"),
        "row_errors_persisted": False,
    }


def test_failed_import_batch_detail_has_no_transactions(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    _, failed, _ = seed_batches(session)

    response = get_import(client, failed.id)

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["rejected_count"] == 1
    assert response.json()["transaction_count"] == 0


def test_partial_import_explicitly_reports_row_errors_are_not_persisted(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    _, _, partial = seed_batches(session)

    response = get_import(client, partial.id)

    assert response.status_code == 200
    assert response.json()["status"] == "completed_with_errors"
    assert response.json()["rejected_count"] == 1
    assert response.json()["row_errors_persisted"] is False
    assert "row_errors" not in response.json()


def test_unknown_import_batch_returns_404(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, _ = client_and_session

    response = get_import(client, UUID(int=999))

    assert response.status_code == 404
    assert response.json() == {"detail": "Import batch not found"}


def test_malformed_import_batch_uuid_returns_422(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, _ = client_and_session

    response = get_import(client, "not-a-uuid")

    assert response.status_code == 422


def test_transactions_url_preserves_import_provenance(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    completed, _, _ = seed_batches(session)

    detail = get_import(client, completed.id)
    transactions = get_transactions(client, completed.id)

    assert detail.status_code == 200
    assert detail.json()["transactions_url"] == (f"/transactions?import_batch_id={completed.id}")
    assert transactions.status_code == 200
    assert transactions.json()["pagination"]["total"] == 2
    assert {item["import_batch_id"] for item in transactions.json()["items"]} == {str(completed.id)}


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
