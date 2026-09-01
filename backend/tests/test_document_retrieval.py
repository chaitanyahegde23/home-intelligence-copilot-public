from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    Document,
    DocumentChunk,
    DocumentExtraction,
    DocumentExtractionStatus,
    DocumentStatus,
    DocumentTextSpan,
)
from app.schemas.document_retrieval import RetrievalScope
from app.services.document_chunker import DeterministicCharacterChunker
from app.services.document_retrieval import (
    UnsupportedRetrievalScopeError,
    search_document_chunks,
)
from app.services.document_storage import PrivateDocumentStorage, get_document_storage

SAMPLE_PDF = (
    Path(__file__).resolve().parents[2] / "sample-data" / "synthetic-household-document.pdf"
)
EVALUATION_FIXTURE = (
    Path(__file__).resolve().parents[2] / "sample-data" / "synthetic-retrieval-evaluation.json"
)


@dataclass
class RetrievalTestContext:
    client: TestClient
    session: Session
    storage: PrivateDocumentStorage
    settings: Settings


@pytest.fixture
def retrieval_context(tmp_path: Path) -> Iterator[RetrievalTestContext]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    storage = PrivateDocumentStorage(tmp_path / "documents")
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        document_storage_root=storage.root,
        max_document_size_bytes=1024 * 1024,
        max_document_pages=20,
        max_document_text_chars=100_000,
        document_chunk_max_chars=80,
    )

    with Session(engine, expire_on_commit=False) as session:

        def override_get_db() -> Iterator[Session]:
            yield session

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_document_storage] = lambda: storage

        with TestClient(app) as client:
            yield RetrievalTestContext(client, session, storage, settings)

        app.dependency_overrides.clear()

    engine.dispose()


def upload_extract_and_chunk(context: RetrievalTestContext) -> tuple[str, dict[str, object]]:
    upload = context.client.post(
        "/documents",
        files={
            "file": (
                "synthetic-retrieval-source.pdf",
                SAMPLE_PDF.read_bytes(),
                "application/pdf",
            )
        },
    )
    assert upload.status_code == 201
    document_id = upload.json()["id"]
    assert context.client.put(f"/documents/{document_id}/extraction").status_code == 200
    response = context.client.put(f"/documents/{document_id}/chunks")
    assert response.status_code == 200
    return cast(str, document_id), cast(dict[str, object], response.json())


def seed_extracted_document(
    session: Session,
    *,
    reference: str,
    filename: str,
    text: str,
) -> Document:
    now = datetime.now(UTC)
    document = Document(
        status=DocumentStatus.STORED,
        original_filename=filename,
        size_bytes=len(text.encode()),
        sha256=hashlib.sha256(reference.encode()).hexdigest(),
        storage_key=f"objects/synthetic/{reference}",
    )
    session.add(document)
    session.flush()
    extraction = DocumentExtraction(
        document_id=document.id,
        status=DocumentExtractionStatus.COMPLETED,
        extractor_name="synthetic_eval",
        extractor_version="1",
        document_sha256=document.sha256,
        started_at=now,
        completed_at=now,
    )
    session.add(extraction)
    session.flush()
    session.add(
        DocumentTextSpan(
            extraction_id=extraction.id,
            page_number=1,
            section_number=1,
            start_offset=0,
            end_offset=len(text),
            text=text,
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        )
    )
    session.commit()
    return document


def test_chunker_preserves_exact_nonempty_boundaries() -> None:
    text = "  Alpha beta gamma\nlongsyntheticword  delta epsilon  "
    chunks = DeterministicCharacterChunker().chunk(text, max_chars=12)

    assert chunks
    assert all(0 < len(chunk.text) <= 12 for chunk in chunks)
    assert all(chunk.text == text[chunk.start_offset : chunk.end_offset] for chunk in chunks)
    assert all(not chunk.text[0].isspace() and not chunk.text[-1].isspace() for chunk in chunks)
    assert [chunk.start_offset for chunk in chunks] == sorted(
        chunk.start_offset for chunk in chunks
    )
    assert "".join(chunk.text for chunk in chunks).replace(" ", "").replace("\n", "") == (
        text.replace(" ", "").replace("\n", "")
    )


def test_chunk_build_is_provenanced_bounded_and_idempotent(
    retrieval_context: RetrievalTestContext,
) -> None:
    document_id, first = upload_extract_and_chunk(retrieval_context)

    assert first["document_id"] == document_id
    assert first["chunker_name"] == "deterministic_chars"
    assert first["chunker_version"] == "1"
    assert cast(int, first["chunk_count"]) > 1
    first_chunks = cast(list[dict[str, object]], first["chunks"])
    extraction = retrieval_context.session.get(
        DocumentExtraction,
        UUID(cast(str, first["extraction_id"])),
    )
    assert extraction is not None
    span = extraction.spans[0]
    for index, chunk in enumerate(first_chunks, start=1):
        assert chunk["chunk_index"] == index
        assert chunk["page_number"] == span.page_number
        assert chunk["section_number"] == span.section_number
        start = cast(int, chunk["start_offset"])
        end = cast(int, chunk["end_offset"])
        text = cast(str, chunk["text"])
        assert 0 < len(text) <= retrieval_context.settings.document_chunk_max_chars
        assert text == span.text[start:end]
        assert chunk["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()

    repeated = retrieval_context.client.put(f"/documents/{document_id}/chunks")
    assert repeated.status_code == 200
    assert [chunk["id"] for chunk in repeated.json()["chunks"]] == [
        chunk["id"] for chunk in first_chunks
    ]


def test_changed_chunk_limit_rebuilds_current_chunk_set(
    retrieval_context: RetrievalTestContext,
) -> None:
    document_id, first = upload_extract_and_chunk(retrieval_context)
    first_ids = {chunk["id"] for chunk in cast(list[dict[str, object]], first["chunks"])}

    retrieval_context.settings.document_chunk_max_chars = 35
    rebuilt = retrieval_context.client.put(f"/documents/{document_id}/chunks")

    assert rebuilt.status_code == 200
    assert rebuilt.json()["chunk_count"] > cast(int, first["chunk_count"])
    assert first_ids.isdisjoint(chunk["id"] for chunk in rebuilt.json()["chunks"])
    stored = list(retrieval_context.session.scalars(select(DocumentChunk)))
    assert len(stored) == rebuilt.json()["chunk_count"]


def test_build_requires_a_completed_extraction(
    retrieval_context: RetrievalTestContext,
) -> None:
    upload = retrieval_context.client.post(
        "/documents",
        files={
            "file": (
                "synthetic-no-extraction.pdf",
                SAMPLE_PDF.read_bytes(),
                "application/pdf",
            )
        },
    )
    assert upload.status_code == 201

    response = retrieval_context.client.put(f"/documents/{upload.json()['id']}/chunks")

    assert response.status_code == 404
    assert response.json()["detail"] == "completed document extraction not found"


def test_synthetic_retrieval_evaluation_cases_rank_expected_sources(
    retrieval_context: RetrievalTestContext,
) -> None:
    fixture = json.loads(EVALUATION_FIXTURE.read_text(encoding="utf-8"))
    documents_by_reference: dict[str, Document] = {}
    for item in fixture["documents"]:
        document = seed_extracted_document(
            retrieval_context.session,
            reference=item["reference"],
            filename=item["filename"],
            text=item["text"],
        )
        documents_by_reference[item["reference"]] = document
        response = retrieval_context.client.put(f"/documents/{document.id}/chunks")
        assert response.status_code == 200

    for case in fixture["cases"]:
        response = retrieval_context.client.get(
            "/documents/search",
            params={"q": case["query"], "limit": 5},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["scope"] == "local_single_household"
        assert body["search_config"] == "simple"
        assert body["result_count"] >= 1
        top = body["results"][0]
        expected_document = documents_by_reference[case["expected_reference"]]
        assert top["document_id"] == str(expected_document.id)
        assert top["original_filename"] == expected_document.original_filename
        assert top["document_sha256"] == expected_document.sha256
        assert top["page_number"] == 1
        assert top["section_number"] == 1
        assert top["start_offset"] >= 0
        assert top["end_offset"] > top["start_offset"]
        assert top["relevance_score"] != "0.000000"
        expected_source_text = " ".join(
            result["text"]
            for result in body["results"]
            if result["document_id"] == str(expected_document.id)
        )
        assert case["expected_phrase"] in expected_source_text

    for query in fixture["no_result_queries"]:
        response = retrieval_context.client.get("/documents/search", params={"q": query})
        assert response.status_code == 200
        assert response.json()["result_count"] == 0
        assert response.json()["results"] == []


@pytest.mark.parametrize("query", ["the and what", "--__--", " "])
def test_search_rejects_queries_without_searchable_terms(
    retrieval_context: RetrievalTestContext,
    query: str,
) -> None:
    response = retrieval_context.client.get("/documents/search", params={"q": query})

    assert response.status_code == 422


def test_search_validates_limit(retrieval_context: RetrievalTestContext) -> None:
    assert (
        retrieval_context.client.get(
            "/documents/search", params={"q": "warranty", "limit": 0}
        ).status_code
        == 422
    )
    assert (
        retrieval_context.client.get(
            "/documents/search", params={"q": "warranty", "limit": 51}
        ).status_code
        == 422
    )


def test_retrieval_rejects_any_nonlocal_scope(
    retrieval_context: RetrievalTestContext,
) -> None:
    with pytest.raises(UnsupportedRetrievalScopeError):
        search_document_chunks(
            session=retrieval_context.session,
            query="synthetic warranty",
            limit=10,
            scope=cast(RetrievalScope, "another_household"),
            chunker=DeterministicCharacterChunker(),
        )


def test_postgresql_lexical_index_is_declared() -> None:
    index = next(
        item
        for item in DocumentChunk.__table__.indexes  # type: ignore[attr-defined]
        if item.name == "ix_document_chunks_lexical_text"
    )

    assert index.dialect_options["postgresql"]["using"] == "gin"
    assert "to_tsvector" in str(index.expressions[0])


def test_document_delete_cascades_chunks(retrieval_context: RetrievalTestContext) -> None:
    document_id, _ = upload_extract_and_chunk(retrieval_context)

    response = retrieval_context.client.delete(f"/documents/{document_id}")

    assert response.status_code == 204
    retrieval_context.session.expire_all()
    assert retrieval_context.session.scalar(select(DocumentChunk)) is None
