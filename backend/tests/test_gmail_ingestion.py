from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, cast

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.household import BOOTSTRAP_HOUSEHOLD_ID
from app.db.base import Base
from app.db.household_scope import SESSION_HOUSEHOLD_KEY
from app.db.session import get_db
from app.main import create_app
from app.models import Document, DocumentChunk, DocumentSource, GmailIngestion
from app.models.gmail_ingestion import GmailIngestionStatus
from app.services.document_chunker import DeterministicCharacterChunker
from app.services.document_storage import PrivateDocumentStorage
from app.services.document_text_extractor import (
    DocumentTextExtractionError,
    ExtractedDocumentText,
    ExtractedTextSpan,
    ExtractorIdentity,
)
from app.services.gmail_client import GmailAttachment, GmailClient, GmailMessage
from app.services.gmail_ingestion import SessionFactory, poll_gmail_once

SAMPLE_PDF = (
    Path(__file__).resolve().parents[2] / "sample-data" / "synthetic-household-document.pdf"
)


class SyntheticExtractor:
    identity = ExtractorIdentity(name="synthetic_gmail", version="1")

    def extract(self, stream: BinaryIO, *, max_chars: int) -> ExtractedDocumentText:
        del stream, max_chars
        return ExtractedDocumentText(
            spans=(
                ExtractedTextSpan(
                    page_number=1,
                    section_number=1,
                    text="Synthetic appliance warranty expires 2030-06-30.",
                ),
            )
        )


class FlakySyntheticExtractor(SyntheticExtractor):
    def __init__(self) -> None:
        self.calls = 0

    def extract(self, stream: BinaryIO, *, max_chars: int) -> ExtractedDocumentText:
        self.calls += 1
        if self.calls == 1:
            raise DocumentTextExtractionError("synthetic transient failure")
        return super().extract(stream, max_chars=max_chars)


class FakeGmailClient:
    def __init__(self, messages: list[GmailMessage], content: bytes) -> None:
        self.messages = {message.message_id: message for message in messages}
        self.content = content
        self.download_count = 0
        self.labels: list[tuple[str, str, str | None]] = []

    def list_message_ids(self, *, query: str, limit: int) -> tuple[str, ...]:
        assert "filename:pdf" in query
        return tuple(self.messages)[:limit]

    def get_message(self, message_id: str) -> GmailMessage:
        return self.messages[message_id]

    def download_attachment(self, message_id: str, attachment: GmailAttachment) -> bytes:
        assert message_id in self.messages
        assert attachment.filename.endswith(".pdf")
        self.download_count += 1
        return self.content

    def label_message(self, message_id: str, *, add: str, remove: str | None = None) -> None:
        self.labels.append((message_id, add, remove))


def gmail_settings(tmp_path: Path, *, allowed_senders: list[str] | None = None) -> Settings:
    return Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        document_storage_root=tmp_path / "documents",
        document_ocr_enabled=False,
        gmail_ingestion_enabled=True,
        gmail_client_id=SecretStr("synthetic-client-id"),
        gmail_client_secret=SecretStr("synthetic-client-secret"),
        gmail_refresh_token=SecretStr("synthetic-refresh-token"),
        gmail_ingestion_household_id=BOOTSTRAP_HOUSEHOLD_ID,
        gmail_allowed_senders=allowed_senders or ["parent@example.com"],
        max_document_size_bytes=1024 * 1024,
        max_document_pages=20,
        max_document_text_chars=100_000,
        document_chunk_max_chars=100,
    )


def gmail_message(
    message_id: str,
    *,
    sender: str = "parent@example.com",
    attachment_id: str = "attachment-1",
    authenticated_sender: bool = True,
    is_spam: bool = False,
) -> GmailMessage:
    return GmailMessage(
        message_id=message_id,
        sender=sender,
        subject="Synthetic household document",
        received_at=datetime(2026, 8, 29, 12, tzinfo=UTC),
        attachments=(
            GmailAttachment(
                attachment_key=attachment_id,
                api_attachment_id=attachment_id,
                filename="synthetic-household-document.pdf",
                media_type="application/pdf",
                declared_size=len(SAMPLE_PDF.read_bytes()),
                inline_data=None,
            ),
        ),
        authenticated_sender=authenticated_sender,
        is_spam=is_spam,
    )


def test_gmail_attachment_reuses_document_pipeline_and_is_idempotent(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, class_=Session, expire_on_commit=False)
    settings = gmail_settings(tmp_path)
    client = FakeGmailClient([gmail_message("message-1")], SAMPLE_PDF.read_bytes())

    first = asyncio.run(
        poll_gmail_once(
            settings=settings,
            client=client,
            session_factory=cast(SessionFactory, factory),
            storage=PrivateDocumentStorage(settings.document_storage_root),
            extractor=SyntheticExtractor(),
            chunker=DeterministicCharacterChunker(),
        )
    )
    second = asyncio.run(
        poll_gmail_once(
            settings=settings,
            client=client,
            session_factory=cast(SessionFactory, factory),
            storage=PrivateDocumentStorage(settings.document_storage_root),
            extractor=SyntheticExtractor(),
            chunker=DeterministicCharacterChunker(),
        )
    )
    client.messages["message-2"] = gmail_message("message-2", attachment_id="attachment-2")
    third = asyncio.run(
        poll_gmail_once(
            settings=settings,
            client=client,
            session_factory=cast(SessionFactory, factory),
            storage=PrivateDocumentStorage(settings.document_storage_root),
            extractor=SyntheticExtractor(),
            chunker=DeterministicCharacterChunker(),
        )
    )

    assert first.attachments_imported == 1
    assert second.attachments_skipped == 1
    assert third.attachments_duplicate == 1
    assert third.attachments_skipped == 1
    assert client.download_count == 2
    with factory() as session:
        session.info[SESSION_HOUSEHOLD_KEY] = BOOTSTRAP_HOUSEHOLD_ID
        document = session.scalar(select(Document))
        ingestions = list(session.scalars(select(GmailIngestion)))
        assert document is not None
        assert document.source is DocumentSource.GMAIL_ATTACHMENT
        assert {ingestion.status for ingestion in ingestions} == {
            GmailIngestionStatus.IMPORTED,
            GmailIngestionStatus.DUPLICATE,
        }
        assert all(ingestion.document_id == document.id for ingestion in ingestions)
        assert session.scalar(select(DocumentChunk)) is not None
    assert client.labels[-1] == ("message-2", "HIC/Imported", "HIC/Failed")
    engine.dispose()


@pytest.mark.parametrize(
    ("message", "failure_code"),
    [
        (gmail_message("unapproved", sender="unexpected@example.net"), "sender_not_allowed"),
        (
            gmail_message("unauthenticated", authenticated_sender=False),
            "sender_authentication_failed",
        ),
        (gmail_message("spam", is_spam=True), "sender_authentication_failed"),
    ],
)
def test_gmail_sender_guards_reject_without_downloading(
    tmp_path: Path,
    message: GmailMessage,
    failure_code: str,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, class_=Session, expire_on_commit=False)
    settings = gmail_settings(tmp_path)
    client = FakeGmailClient([message], SAMPLE_PDF.read_bytes())

    result = asyncio.run(
        poll_gmail_once(
            settings=settings,
            client=client,
            session_factory=cast(SessionFactory, factory),
            storage=PrivateDocumentStorage(settings.document_storage_root),
            extractor=SyntheticExtractor(),
            chunker=DeterministicCharacterChunker(),
        )
    )

    assert result.attachments_rejected == 1
    assert client.download_count == 0
    with factory() as session:
        session.info[SESSION_HOUSEHOLD_KEY] = BOOTSTRAP_HOUSEHOLD_ID
        ingestion = session.scalar(select(GmailIngestion))
        assert ingestion is not None
        assert ingestion.failure_code == failure_code
        assert session.scalar(select(Document)) is None
    assert client.labels == [(message.message_id, "HIC/Failed", "HIC/Imported")]
    engine.dispose()


def test_gmail_processing_failure_retries_existing_document_without_redownload(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, class_=Session, expire_on_commit=False)
    settings = gmail_settings(tmp_path)
    client = FakeGmailClient([gmail_message("message-retry")], SAMPLE_PDF.read_bytes())
    extractor = FlakySyntheticExtractor()
    storage = PrivateDocumentStorage(settings.document_storage_root)

    first = asyncio.run(
        poll_gmail_once(
            settings=settings,
            client=client,
            session_factory=cast(SessionFactory, factory),
            storage=storage,
            extractor=extractor,
            chunker=DeterministicCharacterChunker(),
        )
    )
    second = asyncio.run(
        poll_gmail_once(
            settings=settings,
            client=client,
            session_factory=cast(SessionFactory, factory),
            storage=storage,
            extractor=extractor,
            chunker=DeterministicCharacterChunker(),
        )
    )

    assert first.attachments_failed == 1
    assert first.attachments_imported == 0
    assert second.attachments_imported == 1
    assert client.download_count == 1
    assert client.labels == [("message-retry", "HIC/Imported", "HIC/Failed")]
    with factory() as session:
        session.info[SESSION_HOUSEHOLD_KEY] = BOOTSTRAP_HOUSEHOLD_ID
        ingestion = session.scalar(select(GmailIngestion))
        assert ingestion is not None
        assert ingestion.attempt_count == 2
        assert ingestion.status is GmailIngestionStatus.IMPORTED
    engine.dispose()


def test_gmail_client_refreshes_parses_downloads_and_labels() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                200, json={"access_token": "synthetic-access", "expires_in": 3600}
            )
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "message-1"}]})
        if request.url.path.endswith("/messages/message-1") and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "internalDate": "1788014400000",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "Parent <parent@example.com>"},
                            {"name": "Subject", "value": "  Synthetic   PDF  "},
                            {
                                "name": "Authentication-Results",
                                "value": "mx.google.com; dmarc=pass header.from=example.com",
                            },
                        ],
                        "parts": [
                            {
                                "partId": "1",
                                "filename": "fixture.pdf",
                                "mimeType": "application/pdf",
                                "body": {"attachmentId": "attachment-1", "size": 3},
                            }
                        ],
                    },
                },
            )
        if request.url.path.endswith("/attachments/attachment-1"):
            return httpx.Response(200, json={"data": "cGRm"})
        if request.url.path.endswith("/labels"):
            return httpx.Response(
                200,
                json={
                    "labels": [
                        {"id": "imported-id", "name": "HIC/Imported"},
                        {"id": "failed-id", "name": "HIC/Failed"},
                    ]
                },
            )
        if request.url.path.endswith("/modify"):
            return httpx.Response(200, json={"id": "message-1"})
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = GmailClient(
            client_id="synthetic-client",
            client_secret="synthetic-secret",
            refresh_token="synthetic-refresh",
            http_client=http_client,
        )
        assert client.list_message_ids(query="filename:pdf", limit=5) == ("message-1",)
        message = client.get_message("message-1")
        assert message.sender == "parent@example.com"
        assert message.subject == "Synthetic PDF"
        assert message.authenticated_sender is True
        assert message.is_spam is False
        assert message.attachments[0].filename == "fixture.pdf"
        assert client.download_attachment("message-1", message.attachments[0]) == b"pdf"
        client.label_message("message-1", add="HIC/Imported", remove="HIC/Failed")

    modify = next(request for request in requests if request.url.path.endswith("/modify"))
    assert json.loads(modify.content) == {
        "addLabelIds": ["imported-id"],
        "removeLabelIds": ["failed-id"],
    }
    assert all(
        request.headers.get("authorization") == "Bearer synthetic-access"
        for request in requests
        if request.url.host == "gmail.googleapis.com"
    )


def test_gmail_configuration_fails_closed() -> None:
    with pytest.raises(ValidationError, match="Gmail ingestion requires"):
        Settings(gmail_ingestion_enabled=True)
    with pytest.raises(ValidationError, match="complete email addresses"):
        Settings(gmail_allowed_senders=["not-an-email"])


def test_gmail_ingestion_history_is_protected_and_redacts_provider_ids(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, class_=Session, expire_on_commit=False)
    settings = gmail_settings(tmp_path)
    with factory() as session:
        session.info[SESSION_HOUSEHOLD_KEY] = BOOTSTRAP_HOUSEHOLD_ID
        session.add(
            GmailIngestion(
                gmail_message_id="provider-message-id",
                gmail_attachment_id="provider-attachment-id",
                sender="parent@example.com",
                subject="Synthetic record",
                received_at=datetime(2026, 8, 29, 12, tzinfo=UTC),
                original_filename="synthetic.pdf",
                status=GmailIngestionStatus.REJECTED,
                failure_code="document_rejected",
            )
        )
        session.commit()

    application = create_app(settings)

    def override_get_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_get_db
    with TestClient(application) as client:
        response = client.get("/gmail-ingestions")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["allowed_sender_count"] == 1
    assert body["items"][0]["failure_code"] == "document_rejected"
    assert "gmail_message_id" not in body["items"][0]
    assert "gmail_attachment_id" not in body["items"][0]
    engine.dispose()
