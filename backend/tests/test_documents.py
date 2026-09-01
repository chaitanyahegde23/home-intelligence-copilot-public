from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    RectangleObject,
    TextStringObject,
)
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.household_scope import SESSION_HOUSEHOLD_KEY
from app.db.session import get_db
from app.main import app
from app.models import Document, DocumentDeletionAudit, DocumentStatus, Household
from app.services.document_ingestion import DocumentNotFoundError, read_stored_document
from app.services.document_storage import (
    DocumentStorageError,
    PrivateDocumentStorage,
    UnsafeStorageKeyError,
    get_document_storage,
)

SAMPLE_PDF = (
    Path(__file__).resolve().parents[2] / "sample-data" / "synthetic-household-document.pdf"
)


@dataclass
class DocumentTestContext:
    client: TestClient
    session: Session
    storage: PrivateDocumentStorage
    settings: Settings


@pytest.fixture
def document_context(tmp_path: Path) -> Iterator[DocumentTestContext]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    storage = PrivateDocumentStorage(tmp_path / "documents")
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        document_storage_root=storage.root,
        max_document_size_bytes=1024 * 1024,
        max_document_pages=20,
    )

    with Session(engine, expire_on_commit=False) as session:

        def override_get_db() -> Iterator[Session]:
            yield session

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_document_storage] = lambda: storage

        with TestClient(app) as client:
            yield DocumentTestContext(client, session, storage, settings)

        app.dependency_overrides.clear()

    engine.dispose()


def upload_pdf(
    client: TestClient,
    content: bytes | None = None,
    *,
    filename: str = "synthetic-household-document.pdf",
    content_type: str = "application/pdf",
) -> Response:
    response = client.post(
        "/documents",
        files={
            "file": (
                filename,
                SAMPLE_PDF.read_bytes() if content is None else content,
                content_type,
            )
        },
    )
    return cast(Response, response)


def make_pdf(*, pages: int = 1, encrypted: bool = False, javascript: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    if encrypted:
        writer.encrypt("synthetic-password")
    if javascript:
        writer.add_js("app.alert('synthetic');")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def make_pdf_with_uri(uri: str) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_uri(0, uri, RectangleObject((0, 0, 40, 20)))
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def make_pdf_with_launch_action() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_annotation(
        0,
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Link"),
                NameObject("/Rect"): ArrayObject([NumberObject(0)] * 4),
                NameObject("/A"): DictionaryObject(
                    {
                        NameObject("/S"): NameObject("/Launch"),
                        NameObject("/F"): TextStringObject("synthetic.txt"),
                    }
                ),
            }
        ),
    )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_upload_stores_verified_metadata_and_private_object(
    document_context: DocumentTestContext,
) -> None:
    payload = SAMPLE_PDF.read_bytes()
    response = upload_pdf(document_context.client, payload)

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "id": body["id"],
        "status": "stored",
        "original_filename": "synthetic-household-document.pdf",
        "media_type": "application/pdf",
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "storage_backend": "private_filesystem_v1",
        "source": "user_upload",
        "title": None,
        "title_source": None,
        "document_type": None,
        "document_type_source": None,
        "notes": None,
        "collection_name": None,
        "tags": [],
        "created_at": body["created_at"],
        "updated_at": body["updated_at"],
    }

    document = document_context.session.scalar(select(Document))
    assert document is not None
    assert document.status is DocumentStatus.STORED
    assert document_context.storage.exists(document.storage_key)
    assert document.storage_key.startswith("objects/")
    assert document.original_filename not in document.storage_key

    detail = document_context.client.get(f"/documents/{document.id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    for key in body.keys() - {"created_at", "updated_at"}:
        assert detail_body[key] == body[key]
    assert detail_body["created_at"]
    assert detail_body["updated_at"]


def test_document_metadata_can_be_updated_normalized_and_cleared(
    document_context: DocumentTestContext,
) -> None:
    uploaded = upload_pdf(document_context.client)
    document_id = uploaded.json()["id"]

    updated = document_context.client.patch(
        f"/documents/{document_id}",
        json={
            "title": "  Home   warranty  ",
            "document_type": "warranty",
            "notes": "  Synthetic coverage   record  ",
            "collection_name": "  Family   warranties  ",
            "tags": [" Appliance ", "URGENT", "appliance"],
        },
    )

    assert updated.status_code == 200
    assert updated.json()["title"] == "Home warranty"
    assert updated.json()["title_source"] == "user"
    assert updated.json()["document_type"] == "warranty"
    assert updated.json()["document_type_source"] == "user"
    assert updated.json()["notes"] == "Synthetic coverage record"
    assert updated.json()["collection_name"] == "Family warranties"
    assert updated.json()["tags"] == ["appliance", "urgent"]

    cleared = document_context.client.patch(f"/documents/{document_id}", json={"notes": None})
    assert cleared.status_code == 200
    assert cleared.json()["notes"] is None
    assert document_context.client.patch(f"/documents/{document_id}", json={}).status_code == 422
    assert (
        document_context.client.patch(
            f"/documents/{document_id}", json={"document_type": "Tax Return"}
        ).status_code
        == 422
    )


def test_original_document_delivery_uses_safe_private_headers(
    document_context: DocumentTestContext,
) -> None:
    payload = SAMPLE_PDF.read_bytes()
    uploaded = upload_pdf(
        document_context.client,
        payload,
        filename="synthetic household warranty.pdf",
    )

    response = document_context.client.get(f"/documents/{uploaded.json()['id']}/content")

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == (
        "inline; filename*=UTF-8''synthetic%20household%20warranty.pdf"
    )
    assert "storage_key" not in response.headers


def test_original_document_delivery_denies_cross_household_idor(
    document_context: DocumentTestContext,
) -> None:
    uploaded = upload_pdf(document_context.client)
    document_id = uploaded.json()["id"]
    other_household_id = uuid4()
    document_context.session.add(
        Household(id=other_household_id, display_name="Other synthetic household")
    )
    document_context.session.commit()
    document_context.session.info[SESSION_HOUSEHOLD_KEY] = other_household_id

    with pytest.raises(DocumentNotFoundError):
        read_stored_document(
            document_context.session,
            document_context.storage,
            UUID(document_id),
        )


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("synthetic.txt", "application/pdf"),
        ("synthetic.pdf", "text/plain"),
        ("../synthetic.pdf", "application/pdf"),
        (r"..\synthetic.pdf", "application/pdf"),
        ("   ", "application/pdf"),
    ],
)
def test_upload_rejects_unsupported_or_unsafe_metadata(
    document_context: DocumentTestContext,
    filename: str,
    content_type: str,
) -> None:
    response = upload_pdf(
        document_context.client,
        filename=filename,
        content_type=content_type,
    )

    assert response.status_code == 415
    assert document_context.session.scalar(select(Document)) is None
    assert not list((document_context.storage.root / "staging").iterdir())


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not a PDF",
        b"prefix" + make_pdf(),
        make_pdf() + b"synthetic trailing payload",
        make_pdf(encrypted=True),
        make_pdf(javascript=True),
    ],
)
def test_upload_rejects_empty_malformed_encrypted_or_active_pdf(
    document_context: DocumentTestContext,
    content: bytes,
) -> None:
    response = upload_pdf(document_context.client, content)

    assert response.status_code == 422
    assert document_context.session.scalar(select(Document)) is None
    assert not list((document_context.storage.root / "staging").iterdir())


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.test/synthetic-letter",
        "http://example.test/synthetic-letter",
        "mailto:synthetic.person@example.test",
    ],
)
def test_upload_accepts_safe_external_links(
    document_context: DocumentTestContext,
    uri: str,
) -> None:
    response = upload_pdf(document_context.client, make_pdf_with_uri(uri))

    assert response.status_code == 201
    assert document_context.session.scalar(select(Document)) is not None


@pytest.mark.parametrize(
    ("content", "expected_detail"),
    [
        (
            make_pdf_with_uri("javascript:alert('synthetic')"),
            "PDF document contains an unsafe or malformed external link",
        ),
        (
            make_pdf_with_uri("file:///synthetic.txt"),
            "PDF document contains an unsafe or malformed external link",
        ),
        (
            make_pdf_with_uri("https:///missing-host"),
            "PDF document contains an unsafe or malformed external link",
        ),
        (
            make_pdf_with_uri("https://example.test/unsafe path"),
            "PDF document contains an unsafe or malformed external link",
        ),
        (
            make_pdf_with_launch_action(),
            "PDF document contains an unsupported link action",
        ),
    ],
)
def test_upload_rejects_unsafe_or_executable_link_actions(
    document_context: DocumentTestContext,
    content: bytes,
    expected_detail: str,
) -> None:
    response = upload_pdf(document_context.client, content)

    assert response.status_code == 422
    assert response.json()["detail"] == expected_detail
    assert document_context.session.scalar(select(Document)) is None


def test_upload_enforces_configured_byte_and_page_limits(
    document_context: DocumentTestContext,
) -> None:
    document_context.settings.max_document_size_bytes = 10
    too_large = upload_pdf(document_context.client)

    assert too_large.status_code == 413
    assert "10-byte" in too_large.json()["detail"]
    assert document_context.session.scalar(select(Document)) is None
    assert not list((document_context.storage.root / "staging").iterdir())

    document_context.settings.max_document_size_bytes = 1024 * 1024
    document_context.settings.max_document_pages = 1
    too_many_pages = upload_pdf(document_context.client, make_pdf(pages=2))

    assert too_many_pages.status_code == 422
    assert "1-page" in too_many_pages.json()["detail"]
    assert document_context.session.scalar(select(Document)) is None
    assert not list((document_context.storage.root / "staging").iterdir())


def test_duplicate_upload_is_rejected_without_a_second_object(
    document_context: DocumentTestContext,
) -> None:
    first = upload_pdf(document_context.client)
    second = upload_pdf(
        document_context.client,
        filename="same-synthetic-content.pdf",
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json() == {
        "detail": {
            "code": "duplicate_document",
            "existing_document_id": first.json()["id"],
        }
    }
    assert len(list(document_context.session.scalars(select(Document)))) == 1
    stored_objects = document_context.storage.root / "objects"
    assert len([path for path in stored_objects.rglob("*") if path.is_file()]) == 1
    assert not list((document_context.storage.root / "staging").iterdir())


class FailingPromotionStorage(PrivateDocumentStorage):
    def promote(self, staging_key: str, final_key: str) -> None:
        raise DocumentStorageError("synthetic promotion failure")


def test_storage_failure_rolls_back_metadata_and_staged_bytes(
    document_context: DocumentTestContext,
) -> None:
    storage = FailingPromotionStorage(document_context.storage.root)
    app.dependency_overrides[get_document_storage] = lambda: storage

    response = upload_pdf(document_context.client)

    assert response.status_code == 503
    assert document_context.session.scalar(select(Document)) is None
    assert not list((storage.root / "staging").iterdir())
    assert not list((storage.root / "objects").rglob("*.*"))


class FailingCommitSession(Session):
    def commit(self) -> None:
        raise SQLAlchemyError("synthetic commit failure")


def test_commit_failure_removes_promoted_object_and_rolls_back_row(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    storage = PrivateDocumentStorage(tmp_path / "documents")

    with FailingCommitSession(engine, expire_on_commit=False) as session:

        def override_get_db() -> Iterator[Session]:
            yield session

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_settings] = lambda: Settings(
            database_url="sqlite+pysqlite:///:memory:",
            document_storage_root=storage.root,
        )
        app.dependency_overrides[get_document_storage] = lambda: storage
        with TestClient(app) as client:
            response = upload_pdf(client)
        app.dependency_overrides.clear()

        assert response.status_code == 503
        assert session.scalar(select(Document)) is None
        assert not list((storage.root / "staging").iterdir())
        assert not list((storage.root / "objects").rglob("*.*"))

    engine.dispose()


def test_delete_is_deny_first_audited_and_idempotent(
    document_context: DocumentTestContext,
) -> None:
    uploaded = upload_pdf(document_context.client)
    document_id = UUID(uploaded.json()["id"])
    document = document_context.session.get(Document, document_id)
    assert document is not None
    storage_key = document.storage_key

    deleted = document_context.client.delete(f"/documents/{document_id}")
    repeated = document_context.client.delete(f"/documents/{document_id}")

    assert deleted.status_code == 204
    assert repeated.status_code == 204
    assert document_context.session.get(Document, document_id) is None
    audit = document_context.session.scalar(select(DocumentDeletionAudit))
    assert audit is not None
    assert audit.document_id == document_id
    assert audit.created_at is not None
    assert not document_context.storage.exists(storage_key)
    assert document_context.client.get(f"/documents/{document_id}").status_code == 404


class ToggleDeleteStorage(PrivateDocumentStorage):
    fail_object_delete = False

    def delete(self, key: str) -> None:
        if self.fail_object_delete and key.startswith("objects/"):
            raise DocumentStorageError("synthetic deletion failure")
        super().delete(key)


def test_failed_delete_remains_denied_and_can_be_retried(
    document_context: DocumentTestContext,
) -> None:
    storage = ToggleDeleteStorage(document_context.storage.root)
    app.dependency_overrides[get_document_storage] = lambda: storage
    uploaded = upload_pdf(document_context.client)
    document_id = UUID(uploaded.json()["id"])

    storage.fail_object_delete = True
    failed = document_context.client.delete(f"/documents/{document_id}")

    assert failed.status_code == 503
    document_context.session.expire_all()
    document = document_context.session.get(Document, document_id)
    assert document is not None
    assert document.status is DocumentStatus.DELETING
    assert storage.exists(document.storage_key)
    assert document_context.client.get(f"/documents/{document_id}").status_code == 404
    assert document_context.session.scalar(select(DocumentDeletionAudit)) is None

    storage.fail_object_delete = False
    retried = document_context.client.delete(f"/documents/{document_id}")

    assert retried.status_code == 204
    assert document_context.session.get(Document, document_id) is None
    assert document_context.session.scalar(select(DocumentDeletionAudit)) is not None


@pytest.mark.parametrize(
    "storage_key",
    ["../outside", "/absolute/object", r"objects\unsafe", "objects/../outside"],
)
def test_storage_adapter_rejects_path_traversal(
    document_context: DocumentTestContext,
    storage_key: str,
) -> None:
    with pytest.raises(UnsafeStorageKeyError):
        document_context.storage.exists(storage_key)


def test_upload_does_not_log_filename_or_raw_content(
    document_context: DocumentTestContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    marker = "SYNTHETIC-PRIVATE-MARKER"
    response = upload_pdf(
        document_context.client,
        filename="sensitive-synthetic-name.pdf",
    )

    assert response.status_code == 201
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "sensitive-synthetic-name.pdf" not in messages
    assert marker not in messages


def test_missing_document_returns_not_found(
    document_context: DocumentTestContext,
) -> None:
    missing_id = "00000000-0000-0000-0000-000000000001"

    assert document_context.client.get(f"/documents/{missing_id}").status_code == 404
    assert document_context.client.delete(f"/documents/{missing_id}").status_code == 404


def test_storage_writer_rejects_non_staging_keys(
    document_context: DocumentTestContext,
) -> None:
    with (
        pytest.raises(UnsafeStorageKeyError),
        document_context.storage.open_staging_writer("objects/not-staging") as stream,
    ):
        stream.write(b"not written")
