from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app.core.config import Settings
from app.db.household_scope import SESSION_HOUSEHOLD_KEY
from app.models.document import DocumentSource
from app.models.gmail_ingestion import GmailIngestion, GmailIngestionStatus
from app.services.document_chunker import DeterministicCharacterChunker
from app.services.document_extraction import (
    DocumentExtractionOperationError,
    DocumentExtractionRejectedError,
    extract_document_text,
)
from app.services.document_ingestion import (
    DocumentIngestionError,
    DocumentPersistenceError,
    DuplicateDocumentError,
    store_pdf_document,
)
from app.services.document_retrieval import (
    DocumentRetrievalPersistenceError,
    build_document_chunks,
)
from app.services.document_storage import PrivateDocumentStorage
from app.services.document_text_extractor import DocumentTextExtractor
from app.services.gmail_client import (
    GmailApiError,
    GmailAttachment,
    GmailClientProtocol,
    GmailMessage,
)

SessionFactory = Callable[[], Session]


@dataclass(frozen=True)
class GmailPollSummary:
    messages_found: int
    attachments_imported: int
    attachments_duplicate: int
    attachments_rejected: int
    attachments_failed: int
    attachments_skipped: int


@dataclass(frozen=True)
class AttachmentOutcome:
    status: GmailIngestionStatus
    newly_processed: bool
    terminal: bool = True


async def poll_gmail_once(
    *,
    settings: Settings,
    client: GmailClientProtocol,
    session_factory: SessionFactory,
    storage: PrivateDocumentStorage,
    extractor: DocumentTextExtractor,
    chunker: DeterministicCharacterChunker,
) -> GmailPollSummary:
    household_id = _required_household_id(settings)
    message_ids = client.list_message_ids(
        query=settings.gmail_search_query,
        limit=settings.gmail_max_messages_per_poll,
    )
    totals = {status: 0 for status in GmailIngestionStatus}
    skipped = 0
    for message_id in message_ids:
        message = client.get_message(message_id)
        if not message.attachments:
            continue
        message_outcomes: list[AttachmentOutcome] = []
        for attachment in message.attachments:
            result = await _process_attachment(
                settings=settings,
                client=client,
                session_factory=session_factory,
                storage=storage,
                extractor=extractor,
                chunker=chunker,
                household_id=household_id,
                message=message,
                attachment=attachment,
            )
            if result is None or not result.newly_processed:
                skipped += 1
            else:
                totals[result.status] += 1
            if result is not None:
                message_outcomes.append(result)
        if message_outcomes and all(outcome.terminal for outcome in message_outcomes):
            failed = any(
                outcome.status in {GmailIngestionStatus.REJECTED, GmailIngestionStatus.FAILED}
                for outcome in message_outcomes
            )
            client.label_message(
                message.message_id,
                add=settings.gmail_failed_label if failed else settings.gmail_processed_label,
                remove=settings.gmail_processed_label if failed else settings.gmail_failed_label,
            )
    return GmailPollSummary(
        messages_found=len(message_ids),
        attachments_imported=totals[GmailIngestionStatus.IMPORTED],
        attachments_duplicate=totals[GmailIngestionStatus.DUPLICATE],
        attachments_rejected=totals[GmailIngestionStatus.REJECTED],
        attachments_failed=totals[GmailIngestionStatus.FAILED],
        attachments_skipped=skipped,
    )


async def _process_attachment(
    *,
    settings: Settings,
    client: GmailClientProtocol,
    session_factory: SessionFactory,
    storage: PrivateDocumentStorage,
    extractor: DocumentTextExtractor,
    chunker: DeterministicCharacterChunker,
    household_id: UUID,
    message: GmailMessage,
    attachment: GmailAttachment,
) -> AttachmentOutcome | None:
    with session_factory() as session:
        session.info[SESSION_HOUSEHOLD_KEY] = household_id
        ingestion = _reserve_ingestion(
            session,
            settings=settings,
            message=message,
            attachment=attachment,
        )
        if ingestion is None:
            return None
        if ingestion.status is not GmailIngestionStatus.PROCESSING:
            return AttachmentOutcome(status=ingestion.status, newly_processed=False)

        if message.sender not in settings.gmail_allowed_senders:
            return AttachmentOutcome(
                _finish(
                    session,
                    ingestion,
                    GmailIngestionStatus.REJECTED,
                    failure_code="sender_not_allowed",
                ),
                True,
            )
        if message.is_spam or (
            settings.gmail_require_authenticated_sender and not message.authenticated_sender
        ):
            return AttachmentOutcome(
                _finish(
                    session,
                    ingestion,
                    GmailIngestionStatus.REJECTED,
                    failure_code="sender_authentication_failed",
                ),
                True,
            )
        if attachment.declared_size > settings.max_document_size_bytes:
            return AttachmentOutcome(
                _finish(
                    session,
                    ingestion,
                    GmailIngestionStatus.REJECTED,
                    failure_code="attachment_too_large",
                ),
                True,
            )
        if ingestion.document_id is not None:
            return _process_stored_document(
                session=session,
                settings=settings,
                storage=storage,
                extractor=extractor,
                chunker=chunker,
                ingestion=ingestion,
                document_id=ingestion.document_id,
            )
        try:
            content = client.download_attachment(message.message_id, attachment)
        except GmailApiError:
            return AttachmentOutcome(
                _finish(
                    session,
                    ingestion,
                    GmailIngestionStatus.FAILED,
                    failure_code="attachment_download_failed",
                ),
                True,
                ingestion.attempt_count >= settings.gmail_max_attempts,
            )
        if len(content) > settings.max_document_size_bytes:
            return AttachmentOutcome(
                _finish(
                    session,
                    ingestion,
                    GmailIngestionStatus.REJECTED,
                    failure_code="attachment_too_large",
                ),
                True,
            )

        upload = UploadFile(
            file=BytesIO(content),
            filename=attachment.filename,
            headers=Headers({"content-type": "application/pdf"}),
        )
        try:
            document = await store_pdf_document(
                upload=upload,
                session=session,
                storage=storage,
                max_size_bytes=settings.max_document_size_bytes,
                max_pages=settings.max_document_pages,
                source=DocumentSource.GMAIL_ATTACHMENT,
            )
        except DuplicateDocumentError as exc:
            return AttachmentOutcome(
                _finish(
                    session,
                    ingestion,
                    GmailIngestionStatus.DUPLICATE,
                    document_id=exc.existing_document_id,
                ),
                True,
            )
        except DocumentIngestionError:
            return AttachmentOutcome(
                _finish(
                    session,
                    ingestion,
                    GmailIngestionStatus.REJECTED,
                    failure_code="document_rejected",
                ),
                True,
            )
        except DocumentPersistenceError:
            return AttachmentOutcome(
                _finish(
                    session,
                    ingestion,
                    GmailIngestionStatus.FAILED,
                    failure_code="document_storage_failed",
                ),
                True,
                ingestion.attempt_count >= settings.gmail_max_attempts,
            )

        ingestion.document_id = document.id
        try:
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            return AttachmentOutcome(
                _finish(
                    session,
                    ingestion,
                    GmailIngestionStatus.FAILED,
                    document_id=document.id,
                    failure_code="ingestion_link_failed",
                ),
                True,
                ingestion.attempt_count >= settings.gmail_max_attempts,
            )
        return _process_stored_document(
            session=session,
            settings=settings,
            storage=storage,
            extractor=extractor,
            chunker=chunker,
            ingestion=ingestion,
            document_id=document.id,
        )


def _process_stored_document(
    *,
    session: Session,
    settings: Settings,
    storage: PrivateDocumentStorage,
    extractor: DocumentTextExtractor,
    chunker: DeterministicCharacterChunker,
    ingestion: GmailIngestion,
    document_id: UUID,
) -> AttachmentOutcome:
    try:
        extract_document_text(
            session=session,
            storage=storage,
            extractor=extractor,
            document_id=document_id,
            max_chars=settings.max_document_text_chars,
            stale_after_seconds=settings.document_extraction_stale_seconds,
        )
        build_document_chunks(
            session=session,
            document_id=document_id,
            chunker=chunker,
            max_chars=settings.document_chunk_max_chars,
        )
    except DocumentExtractionRejectedError:
        return AttachmentOutcome(
            _finish(
                session,
                ingestion,
                GmailIngestionStatus.REJECTED,
                document_id=document_id,
                failure_code="extracted_text_too_large",
            ),
            True,
        )
    except (DocumentExtractionOperationError, DocumentRetrievalPersistenceError):
        return AttachmentOutcome(
            _finish(
                session,
                ingestion,
                GmailIngestionStatus.FAILED,
                document_id=document_id,
                failure_code="document_processing_failed",
            ),
            True,
            ingestion.attempt_count >= settings.gmail_max_attempts,
        )
    return AttachmentOutcome(
        _finish(
            session,
            ingestion,
            GmailIngestionStatus.IMPORTED,
            document_id=document_id,
        ),
        True,
    )


def _reserve_ingestion(
    session: Session,
    *,
    settings: Settings,
    message: GmailMessage,
    attachment: GmailAttachment,
) -> GmailIngestion | None:
    existing = session.scalar(
        select(GmailIngestion).where(
            GmailIngestion.gmail_message_id == message.message_id,
            GmailIngestion.gmail_attachment_id == attachment.attachment_key,
        )
    )
    now = datetime.now(UTC)
    if existing is not None:
        terminal = {
            GmailIngestionStatus.IMPORTED,
            GmailIngestionStatus.DUPLICATE,
            GmailIngestionStatus.REJECTED,
        }
        if existing.status in terminal:
            return existing
        if existing.attempt_count >= settings.gmail_max_attempts:
            return existing
        if existing.status is GmailIngestionStatus.PROCESSING and now - _as_utc(
            existing.updated_at
        ) < timedelta(seconds=settings.gmail_ingestion_stale_seconds):
            return None
        existing.status = GmailIngestionStatus.PROCESSING
        existing.attempt_count += 1
        existing.failure_code = None
        try:
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            return None
        return existing

    ingestion = GmailIngestion(
        gmail_message_id=message.message_id,
        gmail_attachment_id=attachment.attachment_key,
        sender=message.sender[:320],
        subject=message.subject,
        received_at=message.received_at,
        original_filename=attachment.filename[:255],
        status=GmailIngestionStatus.PROCESSING,
    )
    session.add(ingestion)
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        return None
    return ingestion


def _finish(
    session: Session,
    ingestion: GmailIngestion,
    status: GmailIngestionStatus,
    *,
    document_id: UUID | None = None,
    failure_code: str | None = None,
) -> GmailIngestionStatus:
    ingestion = session.get(GmailIngestion, ingestion.id) or ingestion
    ingestion.status = status
    ingestion.document_id = document_id or ingestion.document_id
    ingestion.failure_code = failure_code
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        return GmailIngestionStatus.FAILED
    return status


def _required_household_id(settings: Settings) -> UUID:
    if settings.gmail_ingestion_household_id is None:
        raise RuntimeError("Gmail ingestion household is not configured")
    return settings.gmail_ingestion_household_id


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
