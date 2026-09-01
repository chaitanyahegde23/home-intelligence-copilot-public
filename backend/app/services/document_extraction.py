from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import BinaryIO
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.models.document import Document, DocumentStatus
from app.models.document_extraction import (
    DocumentExtraction,
    DocumentExtractionStatus,
    DocumentTextSpan,
)
from app.schemas.document_extraction import DocumentExtractionRead
from app.services.document_facts import (
    ensure_document_fact_inference,
    persist_document_fact_inference,
)
from app.services.document_metadata import (
    ensure_document_metadata_inference,
    persist_document_metadata_inference,
)
from app.services.document_storage import DocumentStorageError, PrivateDocumentStorage
from app.services.document_text_extractor import (
    DocumentTextExtractionError,
    DocumentTextExtractor,
    ExtractedDocumentText,
    ExtractedTextTooLargeError,
)

READ_CHUNK_SIZE = 64 * 1024


class ExtractionFailureCode(StrEnum):
    STORAGE_UNAVAILABLE = "storage_unavailable"
    SOURCE_INTEGRITY_MISMATCH = "source_integrity_mismatch"
    EXTRACTION_FAILED = "extraction_failed"
    EXTRACTED_TEXT_TOO_LARGE = "extracted_text_too_large"
    PERSISTENCE_FAILED = "persistence_failed"


class DocumentExtractionNotFoundError(LookupError):
    pass


class DocumentExtractionInProgressError(RuntimeError):
    pass


class DocumentExtractionOperationError(RuntimeError):
    pass


class DocumentExtractionRejectedError(DocumentExtractionOperationError):
    pass


def extract_document_text(
    *,
    session: Session,
    storage: PrivateDocumentStorage,
    extractor: DocumentTextExtractor,
    document_id: UUID,
    max_chars: int,
    stale_after_seconds: int,
) -> DocumentExtractionRead:
    document = session.scalar(select(Document).where(Document.id == document_id).with_for_update())
    if document is None or document.status is not DocumentStatus.STORED:
        raise DocumentExtractionNotFoundError("stored document not found")

    identity = extractor.identity
    extraction = session.scalar(
        select(DocumentExtraction)
        .where(
            DocumentExtraction.document_id == document.id,
            DocumentExtraction.extractor_name == identity.name,
            DocumentExtraction.extractor_version == identity.version,
            DocumentExtraction.document_sha256 == document.sha256,
        )
        .options(selectinload(DocumentExtraction.spans))
    )
    if extraction is not None and extraction.status is DocumentExtractionStatus.COMPLETED:
        metadata_changed = ensure_document_metadata_inference(
            session,
            document=document,
            extraction=extraction,
        )
        facts_changed = ensure_document_fact_inference(
            session,
            document=document,
            extraction=extraction,
        )
        if metadata_changed or facts_changed:
            try:
                session.commit()
            except SQLAlchemyError as exc:
                session.rollback()
                raise DocumentExtractionOperationError(
                    "document metadata inference could not be persisted"
                ) from exc
        return DocumentExtractionRead.model_validate(extraction)
    if extraction is not None and extraction.status is DocumentExtractionStatus.PROCESSING:
        retry_after = _as_utc(extraction.started_at) + timedelta(seconds=stale_after_seconds)
        if datetime.now(UTC) < retry_after:
            raise DocumentExtractionInProgressError("document extraction is already processing")

    started_at = datetime.now(UTC)
    if extraction is None:
        extraction = DocumentExtraction(
            document_id=document.id,
            status=DocumentExtractionStatus.PROCESSING,
            extractor_name=identity.name,
            extractor_version=identity.version,
            document_sha256=document.sha256,
            started_at=started_at,
        )
        session.add(extraction)
    else:
        extraction.status = DocumentExtractionStatus.PROCESSING
        extraction.started_at = started_at
        extraction.completed_at = None
        extraction.failure_code = None
        session.execute(
            delete(DocumentTextSpan).where(DocumentTextSpan.extraction_id == extraction.id)
        )

    storage_key = document.storage_key
    expected_size = document.size_bytes
    expected_sha256 = document.sha256
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise DocumentExtractionOperationError("extraction state could not be persisted") from exc
    extraction_id = extraction.id

    try:
        with storage.open_reader(storage_key) as stream:
            _verify_original(
                stream,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
            )
            extracted = extractor.extract(stream, max_chars=max_chars)
    except ExtractedTextTooLargeError as exc:
        _record_failure(
            session,
            extraction_id,
            ExtractionFailureCode.EXTRACTED_TEXT_TOO_LARGE,
        )
        raise DocumentExtractionRejectedError(
            "extracted text exceeds the configured limit"
        ) from exc
    except SourceIntegrityError as exc:
        _record_failure(
            session,
            extraction_id,
            ExtractionFailureCode.SOURCE_INTEGRITY_MISMATCH,
        )
        raise DocumentExtractionOperationError("stored document integrity check failed") from exc
    except DocumentStorageError as exc:
        _record_failure(session, extraction_id, ExtractionFailureCode.STORAGE_UNAVAILABLE)
        raise DocumentExtractionOperationError("document storage is unavailable") from exc
    except DocumentTextExtractionError as exc:
        _record_failure(session, extraction_id, ExtractionFailureCode.EXTRACTION_FAILED)
        raise DocumentExtractionOperationError("document text extraction failed") from exc

    return _complete_extraction(
        session=session,
        extraction_id=extraction_id,
        extracted=extracted,
    )


def get_latest_document_extraction(
    session: Session,
    document_id: UUID,
) -> DocumentExtractionRead:
    extraction = session.scalar(
        select(DocumentExtraction)
        .join(Document)
        .where(
            Document.id == document_id,
            Document.status == DocumentStatus.STORED,
        )
        .options(selectinload(DocumentExtraction.spans))
        .execution_options(populate_existing=True)
        .order_by(DocumentExtraction.created_at.desc(), DocumentExtraction.id.desc())
        .limit(1)
    )
    if extraction is None:
        raise DocumentExtractionNotFoundError("document extraction not found")
    return DocumentExtractionRead.model_validate(extraction)


class SourceIntegrityError(RuntimeError):
    pass


def _verify_original(
    stream: BinaryIO,
    *,
    expected_size: int,
    expected_sha256: str,
) -> None:
    stream.seek(0)
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(READ_CHUNK_SIZE):
        size += len(chunk)
        digest.update(chunk)
    if size != expected_size or digest.hexdigest() != expected_sha256:
        raise SourceIntegrityError("stored original does not match its provenance")
    stream.seek(0)


def _complete_extraction(
    *,
    session: Session,
    extraction_id: UUID,
    extracted: ExtractedDocumentText,
) -> DocumentExtractionRead:
    extraction = session.get(DocumentExtraction, extraction_id)
    if extraction is None:
        raise DocumentExtractionOperationError("extraction state disappeared")
    session.execute(delete(DocumentTextSpan).where(DocumentTextSpan.extraction_id == extraction_id))
    for span in extracted.spans:
        text_sha256 = hashlib.sha256(span.text.encode("utf-8")).hexdigest()
        session.add(
            DocumentTextSpan(
                extraction_id=extraction_id,
                page_number=span.page_number,
                section_number=span.section_number,
                start_offset=0,
                end_offset=len(span.text),
                text=span.text,
                text_sha256=text_sha256,
            )
        )
    document = session.get(Document, extraction.document_id)
    if document is None:
        raise DocumentExtractionOperationError("document state disappeared")
    persist_document_metadata_inference(
        session,
        document=document,
        extraction=extraction,
        extracted=extracted,
    )
    persist_document_fact_inference(
        session,
        document=document,
        extraction=extraction,
        extracted=extracted,
    )
    extraction.status = DocumentExtractionStatus.COMPLETED
    extraction.completed_at = datetime.now(UTC)
    extraction.failure_code = None
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        _record_failure(session, extraction_id, ExtractionFailureCode.PERSISTENCE_FAILED)
        raise DocumentExtractionOperationError("extracted text could not be persisted") from exc
    return _load_extraction(session, extraction_id)


def _record_failure(
    session: Session,
    extraction_id: UUID,
    failure_code: ExtractionFailureCode,
) -> None:
    session.rollback()
    extraction = session.get(DocumentExtraction, extraction_id)
    if extraction is None:
        raise DocumentExtractionOperationError("extraction failure state disappeared")
    session.execute(delete(DocumentTextSpan).where(DocumentTextSpan.extraction_id == extraction_id))
    extraction.status = DocumentExtractionStatus.FAILED
    extraction.completed_at = datetime.now(UTC)
    extraction.failure_code = failure_code.value
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise DocumentExtractionOperationError("extraction failure could not be persisted") from exc


def _load_extraction(session: Session, extraction_id: UUID) -> DocumentExtractionRead:
    extraction = session.scalar(
        select(DocumentExtraction)
        .where(DocumentExtraction.id == extraction_id)
        .options(selectinload(DocumentExtraction.spans))
        .execution_options(populate_existing=True)
    )
    if extraction is None:
        raise DocumentExtractionOperationError("extraction state disappeared")
    return DocumentExtractionRead.model_validate(extraction)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
