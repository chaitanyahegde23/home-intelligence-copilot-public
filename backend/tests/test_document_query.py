from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.household import BOOTSTRAP_HOUSEHOLD_ID
from app.db.base import Base
from app.db.household_scope import SESSION_HOUSEHOLD_KEY
from app.db.session import get_db
from app.main import app
from app.models import (
    Document,
    DocumentChunk,
    DocumentExtraction,
    DocumentExtractionStatus,
    DocumentStatus,
    DocumentTextSpan,
    Household,
)


@pytest.fixture
def session_and_client() -> Iterator[tuple[Session, TestClient]]:
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
            yield session, client
        app.dependency_overrides.clear()
    engine.dispose()


def _document(
    session: Session,
    *,
    identifier: UUID,
    filename: str,
    created_at: datetime,
    status: DocumentStatus = DocumentStatus.STORED,
) -> Document:
    document = Document(
        id=identifier,
        status=status,
        original_filename=filename,
        size_bytes=100,
        sha256=f"{identifier.int:064x}"[-64:],
        storage_key=f"objects/synthetic/{identifier}",
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(document)
    session.commit()
    return document


def _extraction(
    session: Session,
    document: Document,
    *,
    status: DocumentExtractionStatus,
    created_at: datetime,
    with_chunk: bool = False,
) -> DocumentExtraction:
    completed = status is not DocumentExtractionStatus.PROCESSING
    extraction = DocumentExtraction(
        document=document,
        status=status,
        extractor_name="synthetic_query",
        extractor_version=str(created_at.timestamp()),
        document_sha256=document.sha256,
        started_at=created_at,
        completed_at=created_at if completed else None,
        failure_code="synthetic_failure" if status is DocumentExtractionStatus.FAILED else None,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(extraction)
    session.flush()
    if with_chunk:
        text = "Synthetic searchable warranty text."
        span = DocumentTextSpan(
            extraction=extraction,
            page_number=1,
            section_number=1,
            start_offset=0,
            end_offset=len(text),
            text=text,
            text_sha256="a" * 64,
        )
        session.add(span)
        session.flush()
        session.add(
            DocumentChunk(
                document=document,
                extraction=extraction,
                text_span=span,
                chunker_name="deterministic_chars",
                chunker_version="1",
                chunk_index=1,
                page_number=1,
                section_number=1,
                start_offset=0,
                end_offset=len(text),
                text=text,
                text_sha256="b" * 64,
            )
        )
    session.commit()
    return extraction


def test_document_library_empty_and_validates_pagination(
    session_and_client: tuple[Session, TestClient],
) -> None:
    _, client = session_and_client

    response = client.get("/documents")

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
    assert client.get("/documents", params={"limit": 0}).status_code == 422
    assert client.get("/documents", params={"limit": 101}).status_code == 422
    assert client.get("/documents", params={"offset": -1}).status_code == 422


def test_document_library_is_stably_paginated_newest_first(
    session_and_client: tuple[Session, TestClient],
) -> None:
    session, client = session_and_client
    now = datetime.now(UTC)
    identifiers = [UUID(int=101), UUID(int=102), UUID(int=103)]
    _document(
        session,
        identifier=identifiers[0],
        filename="oldest-synthetic.pdf",
        created_at=now - timedelta(days=1),
    )
    _document(
        session,
        identifier=identifiers[1],
        filename="newer-synthetic.pdf",
        created_at=now,
    )
    _document(
        session,
        identifier=identifiers[2],
        filename="newest-tie-synthetic.pdf",
        created_at=now,
    )

    first = client.get("/documents", params={"limit": 2})
    second = client.get("/documents", params={"limit": 2, "offset": 2})

    assert [item["id"] for item in first.json()["items"]] == [
        str(identifiers[2]),
        str(identifiers[1]),
    ]
    assert first.json()["pagination"] == {
        "total": 3,
        "offset": 0,
        "limit": 2,
        "returned": 2,
        "has_more": True,
    }
    assert [item["id"] for item in second.json()["items"]] == [str(identifiers[0])]
    assert second.json()["pagination"]["has_more"] is False


def test_document_library_reports_latest_lifecycle_and_search_readiness(
    session_and_client: tuple[Session, TestClient],
) -> None:
    session, client = session_and_client
    now = datetime.now(UTC)
    searchable = _document(
        session,
        identifier=UUID(int=201),
        filename="searchable-synthetic.pdf",
        created_at=now,
    )
    latest_failed = _document(
        session,
        identifier=UUID(int=202),
        filename="failed-synthetic.pdf",
        created_at=now - timedelta(minutes=1),
    )
    pending = _document(
        session,
        identifier=UUID(int=203),
        filename="pending-synthetic.pdf",
        created_at=now - timedelta(minutes=2),
        status=DocumentStatus.PENDING,
    )
    _extraction(
        session,
        searchable,
        status=DocumentExtractionStatus.COMPLETED,
        created_at=now,
        with_chunk=True,
    )
    _extraction(
        session,
        latest_failed,
        status=DocumentExtractionStatus.COMPLETED,
        created_at=now - timedelta(hours=1),
        with_chunk=True,
    )
    failed = _extraction(
        session,
        latest_failed,
        status=DocumentExtractionStatus.FAILED,
        created_at=now,
    )

    response = client.get("/documents")

    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert items[str(searchable.id)]["latest_extraction_status"] == "completed"
    assert items[str(searchable.id)]["chunk_count"] == 1
    assert items[str(searchable.id)]["is_searchable"] is True
    assert items[str(latest_failed.id)]["latest_extraction_status"] == "failed"
    assert items[str(latest_failed.id)]["latest_extraction_updated_at"] == (
        failed.updated_at.isoformat().replace("+00:00", "Z")
    )
    assert items[str(latest_failed.id)]["chunk_count"] == 0
    assert items[str(latest_failed.id)]["is_searchable"] is False
    assert items[str(pending.id)]["latest_extraction_status"] is None
    assert items[str(pending.id)]["latest_extraction_updated_at"] is None


def test_document_library_is_household_scoped_and_redacted(
    session_and_client: tuple[Session, TestClient],
) -> None:
    session, client = session_and_client
    now = datetime.now(UTC)
    visible = _document(
        session,
        identifier=UUID(int=301),
        filename="visible-synthetic.pdf",
        created_at=now,
    )
    other_household_id = uuid4()
    session.add(Household(id=other_household_id, display_name="Other synthetic household"))
    session.commit()
    session.info[SESSION_HOUSEHOLD_KEY] = other_household_id
    _document(
        session,
        identifier=UUID(int=302),
        filename="hidden-synthetic.pdf",
        created_at=now + timedelta(minutes=1),
    )
    session.info[SESSION_HOUSEHOLD_KEY] = BOOTSTRAP_HOUSEHOLD_ID

    response = client.get("/documents")

    assert response.status_code == 200
    assert response.json()["pagination"]["total"] == 1
    item = response.json()["items"][0]
    assert item["id"] == str(visible.id)
    assert set(item) == {
        "id",
        "status",
        "original_filename",
        "media_type",
        "size_bytes",
        "sha256",
        "source",
        "title",
        "title_source",
        "document_type",
        "document_type_source",
        "notes",
        "collection_name",
        "tags",
        "metadata_inference",
        "facts",
        "expiration_reminder",
        "created_at",
        "updated_at",
        "latest_extraction_status",
        "latest_extraction_updated_at",
        "chunk_count",
        "is_searchable",
    }
    rendered = response.text
    assert "storage_key" not in rendered
    assert "storage_backend" not in rendered
    assert "hidden-synthetic.pdf" not in rendered
    assert "Synthetic searchable warranty text" not in rendered


def test_document_library_filters_by_type_and_display_name(
    session_and_client: tuple[Session, TestClient],
) -> None:
    session, client = session_and_client
    now = datetime.now(UTC)
    warranty = _document(
        session,
        identifier=UUID(int=401),
        filename="original-synthetic.pdf",
        created_at=now,
    )
    warranty.title = "Kitchen appliance warranty"
    warranty.document_type = "warranty"
    warranty.collection_name = "Home records"
    warranty.tags = ["appliance"]
    tax = _document(
        session,
        identifier=UUID(int=402),
        filename="synthetic-tax-return.pdf",
        created_at=now - timedelta(minutes=1),
    )
    tax.document_type = "tax"
    session.commit()

    by_type = client.get("/documents", params={"document_type": "warranty"})
    by_title = client.get("/documents", params={"name": "APPLIANCE"})
    by_filename = client.get("/documents", params={"name": "original-synthetic"})
    by_collection = client.get("/documents", params={"collection_name": "Home records"})

    assert [item["id"] for item in by_type.json()["items"]] == [str(warranty.id)]
    assert by_type.json()["pagination"]["total"] == 1
    assert [item["id"] for item in by_title.json()["items"]] == [str(warranty.id)]
    assert by_title.json()["items"][0]["title"] == "Kitchen appliance warranty"
    assert [item["id"] for item in by_filename.json()["items"]] == [str(warranty.id)]
    assert [item["id"] for item in by_collection.json()["items"]] == [str(warranty.id)]
    assert by_collection.json()["items"][0]["tags"] == ["appliance"]
    assert str(tax.id) not in by_title.text
    assert client.get("/documents", params={"name": "   "}).status_code == 422
