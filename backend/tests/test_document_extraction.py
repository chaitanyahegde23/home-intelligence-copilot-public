from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import BinaryIO, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from pypdf import PdfReader, PdfWriter
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.household import BOOTSTRAP_HOUSEHOLD_ID
from app.db.base import Base
from app.db.household_scope import SESSION_HOUSEHOLD_KEY
from app.db.session import get_db
from app.main import app
from app.models import (
    Document,
    DocumentExpirationReminder,
    DocumentExtraction,
    DocumentExtractionStatus,
    DocumentFact,
    DocumentMetadataInference,
    DocumentTextSpan,
    Household,
)
from app.services.document_storage import PrivateDocumentStorage, get_document_storage
from app.services.document_text_extractor import (
    DocumentTextExtractionError,
    DocumentTextExtractor,
    ExtractedDocumentText,
    ExtractorIdentity,
    PypdfOcrTextExtractor,
    PypdfTextExtractor,
    _normalize_extracted_text,
    get_document_text_extractor,
)
from app.services.document_text_extractor import (
    ExtractedTextSpan as ExtractedTextValue,
)

SAMPLE_PDF = (
    Path(__file__).resolve().parents[2] / "sample-data" / "synthetic-household-document.pdf"
)


@dataclass
class ExtractionTestContext:
    client: TestClient
    session: Session
    storage: PrivateDocumentStorage
    settings: Settings


@pytest.fixture
def extraction_context(tmp_path: Path) -> Iterator[ExtractionTestContext]:
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
        document_extraction_stale_seconds=300,
    )

    with Session(engine, expire_on_commit=False) as session:

        def override_get_db() -> Iterator[Session]:
            yield session

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_document_storage] = lambda: storage
        app.dependency_overrides[get_document_text_extractor] = PypdfTextExtractor

        with TestClient(app) as client:
            yield ExtractionTestContext(client, session, storage, settings)

        app.dependency_overrides.clear()

    engine.dispose()


def upload_pdf(
    client: TestClient,
    content: bytes | None = None,
    *,
    filename: str = "synthetic-extraction-fixture.pdf",
) -> Response:
    response = client.post(
        "/documents",
        files={
            "file": (
                filename,
                SAMPLE_PDF.read_bytes() if content is None else content,
                "application/pdf",
            )
        },
    )
    return cast(Response, response)


def extract_pdf(client: TestClient, document_id: str) -> Response:
    return cast(Response, client.put(f"/documents/{document_id}/extraction"))


def two_page_fixture() -> bytes:
    reader = PdfReader(BytesIO(SAMPLE_PDF.read_bytes()), strict=True)
    writer = PdfWriter()
    writer.add_page(reader.pages[0])
    writer.add_page(reader.pages[0])
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def image_only_fixture() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class SyntheticOcrProcessor:
    def process(
        self,
        source: Path,
        destination: Path,
        *,
        language: str,
        timeout_seconds: int,
    ) -> None:
        destination.write_bytes(SAMPLE_PDF.read_bytes())


class FailingSyntheticOcrProcessor:
    def process(
        self,
        source: Path,
        destination: Path,
        *,
        language: str,
        timeout_seconds: int,
    ) -> None:
        raise DocumentTextExtractionError("synthetic private OCR engine detail")


def stored_path(context: ExtractionTestContext, document: Document) -> Path:
    return context.storage.root.joinpath(*PurePosixPath(document.storage_key).parts)


def test_extracts_reviewable_text_with_page_section_provenance(
    extraction_context: ExtractionTestContext,
) -> None:
    upload = upload_pdf(extraction_context.client, two_page_fixture())
    assert upload.status_code == 201
    document_id = upload.json()["id"]
    document = extraction_context.session.get(Document, UUID(document_id))
    assert document is not None
    original_path = stored_path(extraction_context, document)
    original_bytes = original_path.read_bytes()
    original_digest = hashlib.sha256(original_bytes).hexdigest()

    response = extract_pdf(extraction_context.client, document_id)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["extractor_name"] == "pypdf_native"
    assert body["extractor_version"] == "2"
    assert body["document_sha256"] == upload.json()["sha256"]
    assert body["failure_code"] is None
    assert body["completed_at"] is not None
    assert [span["page_number"] for span in body["spans"]] == [1, 2]
    for span in body["spans"]:
        assert span["section_number"] == 1
        assert span["start_offset"] == 0
        assert span["end_offset"] == len(span["text"])
        assert span["text_sha256"] == hashlib.sha256(span["text"].encode()).hexdigest()
        assert "Synthetic Home Warranty Summary" in span["text"]
        assert "HIC-SYNTH-001" in span["text"]

    assert original_path.read_bytes() == original_bytes
    assert hashlib.sha256(original_path.read_bytes()).hexdigest() == original_digest

    stored_spans = list(
        extraction_context.session.scalars(
            select(DocumentTextSpan).order_by(DocumentTextSpan.page_number)
        )
    )
    assert [(span.page_number, span.section_number) for span in stored_spans] == [
        (1, 1),
        (2, 1),
    ]
    extraction_context.session.expire_all()
    inferred_document = extraction_context.session.get(Document, UUID(document_id))
    inference = extraction_context.session.scalar(select(DocumentMetadataInference))
    assert inferred_document is not None
    assert inferred_document.title == "Synthetic Home Warranty Summary"
    assert inferred_document.title_source == "automatic"
    assert inferred_document.document_type == "warranty"
    assert inferred_document.document_type_source == "automatic"
    assert inference is not None
    assert inference.suggested_document_type == "warranty"
    assert inference.document_type_confidence is not None
    assert inference.evidence_codes
    library_item = extraction_context.client.get("/documents").json()["items"][0]
    assert library_item["title_source"] == "automatic"
    assert library_item["document_type_source"] == "automatic"
    assert library_item["metadata_inference"]["classifier_name"] == ("household_document_rules")
    assert library_item["metadata_inference"]["suggested_document_type"] == "warranty"


def test_ocr_extraction_persists_searchable_spans_and_provenance(
    extraction_context: ExtractionTestContext,
) -> None:
    extractor = PypdfOcrTextExtractor(ocr_processor=SyntheticOcrProcessor())
    app.dependency_overrides[get_document_text_extractor] = lambda: extractor
    upload = upload_pdf(
        extraction_context.client,
        image_only_fixture(),
        filename="synthetic-scanned-warranty.pdf",
    )
    document = extraction_context.session.get(Document, UUID(upload.json()["id"]))
    assert document is not None
    original_path = stored_path(extraction_context, document)
    original_bytes = original_path.read_bytes()

    response = extract_pdf(extraction_context.client, upload.json()["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["extractor_name"] == "pypdf_native_ocr"
    assert body["extractor_version"] == "1"
    assert body["document_sha256"] == upload.json()["sha256"]
    assert [span["page_number"] for span in body["spans"]] == [1]
    assert "Synthetic Home Warranty Summary" in body["spans"][0]["text"]
    assert original_path.read_bytes() == original_bytes
    extraction_context.session.expire_all()
    document = extraction_context.session.get(Document, UUID(upload.json()["id"]))
    assert document is not None
    assert document.document_type == "warranty"


def test_ocr_failure_returns_safe_api_error_and_records_failed_state(
    extraction_context: ExtractionTestContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    extractor = PypdfOcrTextExtractor(ocr_processor=FailingSyntheticOcrProcessor())
    app.dependency_overrides[get_document_text_extractor] = lambda: extractor
    upload = upload_pdf(extraction_context.client, image_only_fixture())

    response = extract_pdf(extraction_context.client, upload.json()["id"])
    state = extraction_context.client.get(f"/documents/{upload.json()['id']}/extraction")

    assert response.status_code == 503
    assert response.json()["detail"] == "document extraction is temporarily unavailable"
    assert state.json()["status"] == "failed"
    assert state.json()["failure_code"] == "extraction_failed"
    assert "synthetic private OCR engine detail" not in "\n".join(
        record.getMessage() for record in caplog.records
    )


def test_manual_metadata_is_never_overwritten_by_automatic_inference(
    extraction_context: ExtractionTestContext,
) -> None:
    document_id = upload_pdf(
        extraction_context.client,
        filename="synthetic-warranty.pdf",
    ).json()["id"]
    updated = extraction_context.client.patch(
        f"/documents/{document_id}",
        json={"title": "My appliance record", "document_type": "home"},
    )
    assert updated.status_code == 200

    assert extract_pdf(extraction_context.client, document_id).status_code == 200

    extraction_context.session.expire_all()
    document = extraction_context.session.get(Document, UUID(document_id))
    inference = extraction_context.session.scalar(select(DocumentMetadataInference))
    assert document is not None
    assert document.title == "My appliance record"
    assert document.title_source == "user"
    assert document.document_type == "home"
    assert document.document_type_source == "user"
    assert inference is not None
    assert inference.suggested_document_type == "warranty"
    extraction_context.session.rollback()

    cleared = extraction_context.client.patch(
        f"/documents/{document_id}", json={"title": None, "document_type": None}
    )
    assert cleared.status_code == 200
    app.dependency_overrides[get_document_text_extractor] = VersionThreeExtractor
    assert extract_pdf(extraction_context.client, document_id).status_code == 200
    extraction_context.session.expire_all()
    cleared_document = extraction_context.session.get(Document, UUID(document_id))
    assert cleared_document is not None
    assert cleared_document.title is None
    assert cleared_document.title_source == "user"
    assert cleared_document.document_type is None
    assert cleared_document.document_type_source == "user"


class CountingExtractor:
    identity = ExtractorIdentity(name="counting_native", version="1")

    def __init__(self) -> None:
        self.calls = 0
        self._delegate = PypdfTextExtractor()

    def extract(self, stream: BinaryIO, *, max_chars: int) -> ExtractedDocumentText:
        self.calls += 1
        return self._delegate.extract(stream, max_chars=max_chars)


def test_completed_extraction_is_idempotent(
    extraction_context: ExtractionTestContext,
) -> None:
    extractor = CountingExtractor()
    app.dependency_overrides[get_document_text_extractor] = lambda: extractor
    document_id = upload_pdf(extraction_context.client).json()["id"]

    first = extract_pdf(extraction_context.client, document_id)
    inference = extraction_context.session.scalar(select(DocumentMetadataInference))
    assert inference is not None
    extraction_context.session.delete(inference)
    document = extraction_context.session.get(Document, UUID(document_id))
    assert document is not None
    document.title = None
    document.title_source = None
    document.document_type = None
    document.document_type_source = None
    extraction_context.session.commit()
    repeated = extract_pdf(extraction_context.client, document_id)

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json()["id"] == first.json()["id"]
    assert repeated.json()["spans"] == first.json()["spans"]
    assert extractor.calls == 1
    assert len(list(extraction_context.session.scalars(select(DocumentExtraction)))) == 1
    assert extraction_context.session.scalar(select(DocumentMetadataInference)) is not None


class VersionThreeExtractor(PypdfTextExtractor):
    identity = ExtractorIdentity(name="pypdf_native", version="3")


class FactExtractorV1:
    identity = ExtractorIdentity(name="synthetic_facts", version="1")

    def extract(self, stream: BinaryIO, *, max_chars: int) -> ExtractedDocumentText:
        return ExtractedDocumentText(
            spans=(
                ExtractedTextValue(
                    page_number=1,
                    section_number=1,
                    text=(
                        "Synthetic Home Warranty\nIssuer: Example Home Services\n"
                        "Reference: HIC-FACT-001\nIssue Date: 2026-01-15\n"
                        "Warranty expires: 2028-06-30"
                    ),
                ),
            )
        )


class FactExtractorV2(FactExtractorV1):
    identity = ExtractorIdentity(name="synthetic_facts", version="2")

    def extract(self, stream: BinaryIO, *, max_chars: int) -> ExtractedDocumentText:
        return ExtractedDocumentText(
            spans=(
                ExtractedTextValue(
                    page_number=1,
                    section_number=1,
                    text=(
                        "Synthetic Home Warranty\nIssuer: Changed Automatic Issuer\n"
                        "Reference: HIC-FACT-002\nIssue Date: 2026-02-15\n"
                        "Warranty expires: 2029-06-30"
                    ),
                ),
            )
        )


def test_structured_facts_persist_and_user_overrides_survive_new_extraction(
    extraction_context: ExtractionTestContext,
) -> None:
    app.dependency_overrides[get_document_text_extractor] = FactExtractorV1
    document_id = upload_pdf(extraction_context.client).json()["id"]
    assert extract_pdf(extraction_context.client, document_id).status_code == 200

    facts = extraction_context.client.get(f"/documents/{document_id}/facts")
    assert facts.status_code == 200
    by_type = {fact["fact_type"]: fact for fact in facts.json()}
    assert by_type["expiration_date"]["value_date"] == "2028-06-30"
    assert by_type["expiration_date"]["source_page_number"] == 1
    assert by_type["expiration_date"]["source"] == "automatic"
    assert by_type["issuer"]["value_text"] == "Example Home Services"
    library_fact_types = {
        fact["fact_type"]
        for fact in extraction_context.client.get("/documents").json()["items"][0]["facts"]
    }
    assert "expiration_date" in library_fact_types

    corrected = extraction_context.client.patch(
        f"/documents/{document_id}/facts/expiration_date",
        json={"value_date": "2030-07-01"},
    )
    cleared = extraction_context.client.patch(
        f"/documents/{document_id}/facts/issuer",
        json={"is_cleared": True},
    )
    assert corrected.status_code == 200
    assert corrected.json()["source"] == "user"
    assert cleared.status_code == 200
    assert cleared.json()["is_cleared"] is True

    app.dependency_overrides[get_document_text_extractor] = FactExtractorV2
    assert extract_pdf(extraction_context.client, document_id).status_code == 200
    refreshed = {
        fact["fact_type"]: fact
        for fact in extraction_context.client.get(f"/documents/{document_id}/facts").json()
    }
    assert refreshed["expiration_date"]["value_date"] == "2030-07-01"
    assert refreshed["issuer"]["is_cleared"] is True
    assert refreshed["reference_number"]["value_text"] == "HIC-FACT-002"

    expirations = extraction_context.client.get(
        "/documents/expirations",
        params={"as_of": "2030-06-15", "within_days": 30},
    )
    assert expirations.status_code == 200
    assert expirations.json()["items"][0]["days_until_expiration"] == 16
    assert expirations.json()["items"][0]["status"] == "upcoming"
    expires_today = extraction_context.client.get(
        "/documents/expirations",
        params={"as_of": "2030-07-01", "within_days": 0},
    )
    assert expires_today.json()["items"][0]["status"] == "expires_today"
    expired = extraction_context.client.get(
        "/documents/expirations",
        params={"as_of": "2030-07-02", "within_days": 0},
    )
    assert expired.json()["items"][0]["days_until_expiration"] == -1
    assert expired.json()["items"][0]["status"] == "expired"

    disabled = extraction_context.client.put(
        f"/documents/{document_id}/expiration-reminder",
        json={"enabled": False, "lead_time_days": 30},
    )
    assert disabled.status_code == 200
    assert (
        extraction_context.client.get(
            "/documents/expiration-reminders", params={"as_of": "2030-06-15"}
        ).json()["items"]
        == []
    )
    configured = extraction_context.client.put(
        f"/documents/{document_id}/expiration-reminder",
        json={"enabled": True, "lead_time_days": 30},
    )
    assert configured.status_code == 200
    assert configured.json()["channel"] == "in_app"
    assert (
        extraction_context.client.put(
            f"/documents/{document_id}/expiration-reminder",
            json={"enabled": True, "lead_time_days": 30},
        ).status_code
        == 200
    )
    assert len(list(extraction_context.session.scalars(select(DocumentExpirationReminder)))) == 1
    assert (
        extraction_context.client.put(
            f"/documents/{document_id}/expiration-reminder",
            json={"enabled": True, "lead_time_days": 3651},
        ).status_code
        == 422
    )
    reminders = extraction_context.client.get(
        "/documents/expiration-reminders", params={"as_of": "2030-06-15"}
    )
    assert reminders.status_code == 200
    assert reminders.json()["household_timezone"] == "America/Los_Angeles"
    assert [item["document_id"] for item in reminders.json()["items"]] == [document_id]

    snoozed = extraction_context.client.post(
        f"/documents/{document_id}/expiration-reminder/snooze",
        params={"as_of": "2030-06-15"},
        json={"until": "2030-06-22"},
    )
    assert snoozed.status_code == 200
    assert (
        extraction_context.client.post(
            f"/documents/{document_id}/expiration-reminder/snooze",
            params={"as_of": "2030-06-15"},
            json={"until": "2030-06-15"},
        ).status_code
        == 409
    )
    assert (
        extraction_context.client.get(
            "/documents/expiration-reminders", params={"as_of": "2030-06-20"}
        ).json()["items"]
        == []
    )
    assert (
        len(
            extraction_context.client.get(
                "/documents/expiration-reminders", params={"as_of": "2030-06-23"}
            ).json()["items"]
        )
        == 1
    )

    acknowledged = extraction_context.client.post(
        f"/documents/{document_id}/expiration-reminder/acknowledge"
    )
    assert acknowledged.status_code == 200
    assert (
        extraction_context.client.get(
            "/documents/expiration-reminders", params={"as_of": "2030-06-23"}
        ).json()["items"]
        == []
    )

    assert (
        extraction_context.client.patch(
            f"/documents/{document_id}/facts/expiration_date",
            json={"value_date": "2031-07-01"},
        ).status_code
        == 200
    )
    renewed = extraction_context.client.get(
        "/documents/expiration-reminders", params={"as_of": "2031-06-15"}
    )
    assert len(renewed.json()["items"]) == 1


def test_structured_fact_endpoint_validates_value_type(
    extraction_context: ExtractionTestContext,
) -> None:
    document_id = upload_pdf(extraction_context.client).json()["id"]

    wrong_date = extraction_context.client.patch(
        f"/documents/{document_id}/facts/expiration_date",
        json={"value_text": "not a date"},
    )
    wrong_text = extraction_context.client.patch(
        f"/documents/{document_id}/facts/issuer",
        json={"value_date": "2028-01-01"},
    )

    assert wrong_date.status_code == 422
    assert wrong_text.status_code == 422


def test_new_extractor_version_creates_a_separate_derivative(
    extraction_context: ExtractionTestContext,
) -> None:
    document_id = upload_pdf(extraction_context.client).json()["id"]
    version_one = extract_pdf(extraction_context.client, document_id)
    assert version_one.status_code == 200

    app.dependency_overrides[get_document_text_extractor] = VersionThreeExtractor
    version_three = extract_pdf(extraction_context.client, document_id)
    latest = extraction_context.client.get(f"/documents/{document_id}/extraction")

    assert version_three.status_code == 200
    assert version_three.json()["id"] != version_one.json()["id"]
    assert version_three.json()["extractor_version"] == "3"
    assert version_three.json()["document_sha256"] == version_one.json()["document_sha256"]
    assert latest.status_code == 200
    assert latest.json()["id"] == version_three.json()["id"]
    assert len(list(extraction_context.session.scalars(select(DocumentExtraction)))) == 2


class FailOnceExtractor:
    identity = ExtractorIdentity(name="retry_native", version="1")

    def __init__(self) -> None:
        self.calls = 0
        self._delegate = PypdfTextExtractor()

    def extract(self, stream: BinaryIO, *, max_chars: int) -> ExtractedDocumentText:
        self.calls += 1
        if self.calls == 1:
            raise DocumentTextExtractionError("synthetic private extraction detail")
        return self._delegate.extract(stream, max_chars=max_chars)


def test_failed_extraction_is_visible_and_retry_reuses_run(
    extraction_context: ExtractionTestContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    extractor = FailOnceExtractor()
    app.dependency_overrides[get_document_text_extractor] = lambda: extractor
    document_id = upload_pdf(extraction_context.client).json()["id"]

    failed = extract_pdf(extraction_context.client, document_id)
    failure_state = extraction_context.client.get(f"/documents/{document_id}/extraction")

    assert failed.status_code == 503
    assert failed.json()["detail"] == "document extraction is temporarily unavailable"
    assert failure_state.status_code == 200
    assert failure_state.json()["status"] == "failed"
    assert failure_state.json()["failure_code"] == "extraction_failed"
    assert failure_state.json()["completed_at"] is not None
    assert failure_state.json()["spans"] == []
    assert "synthetic private extraction detail" not in "\n".join(
        record.getMessage() for record in caplog.records
    )

    retried = extract_pdf(extraction_context.client, document_id)

    assert retried.status_code == 200
    assert retried.json()["id"] == failure_state.json()["id"]
    assert retried.json()["status"] == "completed"
    assert retried.json()["failure_code"] is None
    assert retried.json()["spans"]
    assert extractor.calls == 2


def test_extracted_text_limit_fails_closed_and_can_be_retried(
    extraction_context: ExtractionTestContext,
) -> None:
    extraction_context.settings.max_document_text_chars = 10
    document_id = upload_pdf(extraction_context.client).json()["id"]

    limited = extract_pdf(extraction_context.client, document_id)
    failed = extraction_context.client.get(f"/documents/{document_id}/extraction")

    assert limited.status_code == 422
    assert failed.json()["status"] == "failed"
    assert failed.json()["failure_code"] == "extracted_text_too_large"
    assert failed.json()["spans"] == []

    extraction_context.settings.max_document_text_chars = 100_000
    retried = extract_pdf(extraction_context.client, document_id)
    assert retried.status_code == 200
    assert retried.json()["id"] == failed.json()["id"]

    assert retried.json()["spans"]


def test_integrity_mismatch_is_recorded_without_exposing_content(
    extraction_context: ExtractionTestContext,
) -> None:
    uploaded = upload_pdf(extraction_context.client)
    document_id = UUID(uploaded.json()["id"])
    document = extraction_context.session.get(Document, document_id)
    assert document is not None
    stored_path(extraction_context, document).write_bytes(b"tampered synthetic bytes")

    response = extract_pdf(extraction_context.client, str(document_id))
    state = extraction_context.client.get(f"/documents/{document_id}/extraction")

    assert response.status_code == 503
    assert state.status_code == 200
    assert state.json()["status"] == "failed"
    assert state.json()["failure_code"] == "source_integrity_mismatch"
    assert state.json()["spans"] == []


def test_malformed_stored_pdf_records_extractor_failure(
    extraction_context: ExtractionTestContext,
) -> None:
    uploaded = upload_pdf(extraction_context.client)
    document_id = UUID(uploaded.json()["id"])
    document = extraction_context.session.get(Document, document_id)
    assert document is not None
    malformed = b"%PDF-1.7\nsynthetic malformed body\n%%EOF\n"
    stored_path(extraction_context, document).write_bytes(malformed)
    document.size_bytes = len(malformed)
    document.sha256 = hashlib.sha256(malformed).hexdigest()
    extraction_context.session.commit()

    response = extract_pdf(extraction_context.client, str(document_id))
    state = extraction_context.client.get(f"/documents/{document_id}/extraction")

    assert response.status_code == 503
    assert state.json()["status"] == "failed"
    assert state.json()["failure_code"] == "extraction_failed"
    assert state.json()["spans"] == []


def test_recent_processing_run_returns_conflict_and_visible_state(
    extraction_context: ExtractionTestContext,
) -> None:
    uploaded = upload_pdf(extraction_context.client)
    document_id = UUID(uploaded.json()["id"])
    extraction_context.session.add(
        DocumentExtraction(
            document_id=document_id,
            status=DocumentExtractionStatus.PROCESSING,
            extractor_name="pypdf_native",
            extractor_version="2",
            document_sha256=uploaded.json()["sha256"],
            started_at=datetime.now(UTC),
        )
    )
    extraction_context.session.commit()

    response = extract_pdf(extraction_context.client, str(document_id))
    state = extraction_context.client.get(f"/documents/{document_id}/extraction")

    assert response.status_code == 409
    assert state.status_code == 200
    assert state.json()["status"] == "processing"
    assert state.json()["completed_at"] is None
    assert state.json()["failure_code"] is None


def test_stale_processing_run_is_retried(
    extraction_context: ExtractionTestContext,
) -> None:
    extraction_context.settings.document_extraction_stale_seconds = 0
    uploaded = upload_pdf(extraction_context.client)
    document_id = UUID(uploaded.json()["id"])
    extraction = DocumentExtraction(
        document_id=document_id,
        status=DocumentExtractionStatus.PROCESSING,
        extractor_name="pypdf_native",
        extractor_version="2",
        document_sha256=uploaded.json()["sha256"],
        started_at=datetime.now(UTC),
    )
    extraction_context.session.add(extraction)
    extraction_context.session.commit()

    response = extract_pdf(extraction_context.client, str(document_id))

    assert response.status_code == 200
    assert response.json()["id"] == str(extraction.id)
    assert response.json()["status"] == "completed"


def test_document_delete_cascades_extraction_and_spans(
    extraction_context: ExtractionTestContext,
) -> None:
    document_id = upload_pdf(extraction_context.client).json()["id"]
    assert extract_pdf(extraction_context.client, document_id).status_code == 200
    assert (
        extraction_context.client.put(
            f"/documents/{document_id}/expiration-reminder",
            json={"enabled": True, "lead_time_days": 90},
        ).status_code
        == 200
    )

    deleted = extraction_context.client.delete(f"/documents/{document_id}")

    assert deleted.status_code == 204
    extraction_context.session.expire_all()
    assert extraction_context.session.scalar(select(DocumentExtraction)) is None
    assert extraction_context.session.scalar(select(DocumentTextSpan)) is None
    assert extraction_context.session.scalar(select(DocumentMetadataInference)) is None
    assert extraction_context.session.scalar(select(DocumentFact)) is None
    assert extraction_context.session.scalar(select(DocumentExpirationReminder)) is None
    assert extraction_context.client.get(f"/documents/{document_id}/extraction").status_code == 404


def test_metadata_inference_is_household_scoped(
    extraction_context: ExtractionTestContext,
) -> None:
    document_id = upload_pdf(extraction_context.client).json()["id"]
    assert extract_pdf(extraction_context.client, document_id).status_code == 200
    assert extraction_context.session.scalar(select(DocumentMetadataInference)) is not None
    assert extraction_context.session.scalar(select(DocumentFact)) is not None
    assert (
        extraction_context.client.put(
            f"/documents/{document_id}/expiration-reminder",
            json={"enabled": True, "lead_time_days": 90},
        ).status_code
        == 200
    )
    assert extraction_context.session.scalar(select(DocumentExpirationReminder)) is not None

    other_household_id = uuid4()
    extraction_context.session.add(
        Household(id=other_household_id, display_name="Other synthetic household")
    )
    extraction_context.session.commit()
    extraction_context.session.info[SESSION_HOUSEHOLD_KEY] = other_household_id
    try:
        assert extraction_context.session.scalar(select(DocumentMetadataInference)) is None
        assert extraction_context.session.scalar(select(DocumentFact)) is None
        assert extraction_context.session.scalar(select(DocumentExpirationReminder)) is None
    finally:
        extraction_context.session.rollback()
        extraction_context.session.info[SESSION_HOUSEHOLD_KEY] = BOOTSTRAP_HOUSEHOLD_ID


def test_missing_document_or_extraction_returns_not_found(
    extraction_context: ExtractionTestContext,
) -> None:
    missing_id = "00000000-0000-0000-0000-000000000001"
    document_id = upload_pdf(extraction_context.client).json()["id"]

    assert extract_pdf(extraction_context.client, missing_id).status_code == 404
    assert extraction_context.client.get(f"/documents/{missing_id}/extraction").status_code == 404
    assert extraction_context.client.get(f"/documents/{document_id}/extraction").status_code == 404


def test_extractor_contract_rejects_malformed_pdf() -> None:
    extractor: DocumentTextExtractor = PypdfTextExtractor()

    with pytest.raises(DocumentTextExtractionError):
        extractor.extract(BytesIO(b"not a PDF"), max_chars=1000)


def test_extractor_reads_safe_embedded_title_metadata() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": "Synthetic Tax Record"})
    output = BytesIO()
    writer.write(output)

    extracted = PypdfTextExtractor().extract(BytesIO(output.getvalue()), max_chars=1000)

    assert extracted.embedded_title == "Synthetic Tax Record"


def test_extracted_text_normalization_removes_database_unsafe_controls() -> None:
    normalized = _normalize_extracted_text("Synthetic\x00 record\r\nLine\tvalue\x7f\x85")

    assert normalized == "Synthetic record\nLine\tvalue"
