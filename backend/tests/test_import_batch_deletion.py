from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    Category,
    DuplicateCandidate,
    ImportBatch,
    Transaction,
    TransactionCategoryAssignment,
)
from app.models.categorization import CategoryAssignmentSource
from app.models.import_batch import ImportStatus
from app.services.import_batch_management import delete_import_batch


@pytest.fixture
def client_and_session() -> Iterator[tuple[TestClient, Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:

        def override_get_db() -> Iterator[Session]:
            yield session

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as client:
            yield client, session
        app.dependency_overrides.clear()
    engine.dispose()


def seed_dependent_records(session: Session) -> tuple[ImportBatch, ImportBatch, Category]:
    removed_batch = ImportBatch(
        id=UUID(int=101),
        filename="synthetic-remove.csv",
        status=ImportStatus.COMPLETED,
        row_count=1,
        imported_count=1,
    )
    retained_batch = ImportBatch(
        id=UUID(int=102),
        filename="synthetic-retain.csv",
        status=ImportStatus.COMPLETED,
        row_count=1,
        imported_count=1,
    )
    removed_transaction = Transaction(
        id=UUID(int=201),
        import_batch=removed_batch,
        transaction_date=date(2026, 7, 1),
        description="Synthetic removed transaction",
        amount=Decimal("-10.00"),
        source_file=removed_batch.filename,
    )
    retained_transaction = Transaction(
        id=UUID(int=202),
        import_batch=retained_batch,
        transaction_date=date(2026, 7, 2),
        description="Synthetic retained transaction",
        amount=Decimal("-20.00"),
        source_file=retained_batch.filename,
    )
    category = Category(name="Synthetic category")
    session.add_all(
        [
            removed_batch,
            retained_batch,
            removed_transaction,
            retained_transaction,
            category,
        ]
    )
    session.flush()
    session.add_all(
        [
            DuplicateCandidate(
                first_transaction=removed_transaction,
                second_transaction=retained_transaction,
                fingerprint="a" * 64,
                reason="exact_match_v1",
            ),
            TransactionCategoryAssignment(
                transaction=removed_transaction,
                category=category,
                source=CategoryAssignmentSource.IMPORTED,
            ),
        ]
    )
    session.commit()
    return removed_batch, retained_batch, category


def delete_batch(client: TestClient, batch_id: UUID) -> Response:
    return cast(Response, client.delete(f"/imports/{batch_id}"))


def test_delete_import_batch_cascades_dependents_and_preserves_unrelated_records(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    removed_batch, retained_batch, category = seed_dependent_records(session)

    response = delete_batch(client, removed_batch.id)

    assert response.status_code == 204
    assert response.content == b""
    assert session.get(ImportBatch, removed_batch.id) is None
    assert session.get(ImportBatch, retained_batch.id) is not None
    assert session.scalar(select(func.count()).select_from(Transaction)) == 1
    assert session.scalar(select(func.count()).select_from(DuplicateCandidate)) == 0
    assert session.scalar(select(func.count()).select_from(TransactionCategoryAssignment)) == 0
    assert session.get(Category, category.id) is not None


def test_delete_empty_failed_batch_and_unknown_batch(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    failed = ImportBatch(
        filename="synthetic-failed.csv",
        status=ImportStatus.FAILED,
        row_count=1,
        rejected_count=1,
    )
    session.add(failed)
    session.commit()

    assert delete_batch(client, failed.id).status_code == 204
    missing = delete_batch(client, UUID(int=999))
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Import batch not found"}


def test_delete_import_batch_rolls_back_when_commit_fails(
    client_and_session: tuple[TestClient, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, session = client_and_session
    batch = ImportBatch(filename="synthetic-rollback.csv")
    session.add(batch)
    session.commit()

    def fail_commit() -> None:
        raise RuntimeError("synthetic delete failure")

    monkeypatch.setattr(session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="synthetic delete failure"):
        delete_import_batch(session, batch_id=batch.id)

    assert session.get(ImportBatch, batch.id) is not None
