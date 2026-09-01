from datetime import date
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.document_fact import DocumentFactType
from app.schemas.document import (
    DocumentExpirationResponse,
    DocumentFactRead,
    DocumentFactUpdate,
    DocumentMetadataUpdate,
    DocumentRead,
    DuplicateDocumentDetail,
)
from app.schemas.document_extraction import DocumentExtractionRead
from app.schemas.document_query import DocumentListResponse, DocumentQueryParams
from app.schemas.document_reminder import (
    DocumentExpirationReminderRead,
    DocumentExpirationReminderUpdate,
    DocumentReminderActionResponse,
    DocumentReminderListResponse,
    DocumentReminderSnooze,
)
from app.schemas.transaction_query import PaginationMetadata
from app.services.document_extraction import (
    DocumentExtractionInProgressError,
    DocumentExtractionNotFoundError,
    DocumentExtractionOperationError,
    DocumentExtractionRejectedError,
    extract_document_text,
    get_latest_document_extraction,
)
from app.services.document_facts import (
    DocumentFactNotFoundError,
    DocumentFactPersistenceError,
    list_document_facts,
    query_document_expirations,
    set_user_document_fact,
)
from app.services.document_ingestion import (
    DocumentDeletionError,
    DocumentMetadataPersistenceError,
    DocumentNotFoundError,
    DocumentPersistenceError,
    DocumentTooLargeError,
    DuplicateDocumentError,
    InvalidPdfError,
    UnsupportedDocumentError,
    delete_document,
    get_stored_document,
    read_stored_document,
    store_pdf_document,
    update_document_metadata,
)
from app.services.document_query import query_documents
from app.services.document_reminders import (
    DocumentReminderNotFoundError,
    DocumentReminderPersistenceError,
    DocumentReminderUnavailableError,
    acknowledge_document_reminder,
    configure_document_reminder,
    household_today,
    list_due_document_reminders,
    snooze_document_reminder,
)
from app.services.document_storage import PrivateDocumentStorage, get_document_storage
from app.services.document_text_extractor import (
    DocumentTextExtractor,
    get_document_text_extractor,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: Annotated[UploadFile, File()],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[PrivateDocumentStorage, Depends(get_document_storage)],
) -> DocumentRead:
    try:
        return await store_pdf_document(
            upload=file,
            session=session,
            storage=storage,
            max_size_bytes=settings.max_document_size_bytes,
            max_pages=settings.max_document_pages,
        )
    except UnsupportedDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc
    except DocumentTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except InvalidPdfError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except DuplicateDocumentError as exc:
        detail = DuplicateDocumentDetail(existing_document_id=exc.existing_document_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail.model_dump(mode="json"),
        ) from exc
    except DocumentPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="document storage is temporarily unavailable",
        ) from exc


@router.get("", response_model=DocumentListResponse)
def list_documents(
    params: Annotated[DocumentQueryParams, Query()],
    session: Annotated[Session, Depends(get_db)],
) -> DocumentListResponse:
    result = query_documents(
        session,
        offset=params.offset,
        limit=params.limit,
        document_type=params.document_type,
        name=params.name,
        collection_name=params.collection_name,
    )
    return DocumentListResponse(
        items=result.items,
        pagination=PaginationMetadata(
            total=result.total,
            offset=result.offset,
            limit=result.limit,
            returned=len(result.items),
            has_more=result.has_more,
        ),
    )


@router.get("/expirations", response_model=DocumentExpirationResponse)
def list_document_expirations(
    session: Annotated[Session, Depends(get_db)],
    as_of: Annotated[date, Query()],
    within_days: Annotated[int, Query(ge=0, le=3650)] = 90,
) -> DocumentExpirationResponse:
    return query_document_expirations(
        session,
        as_of=as_of,
        within_days=within_days,
    )


@router.get("/expiration-reminders", response_model=DocumentReminderListResponse)
def list_expiration_reminders(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    as_of: Annotated[date | None, Query()] = None,
) -> DocumentReminderListResponse:
    return list_due_document_reminders(
        session,
        as_of=as_of or household_today(settings.household_timezone),
        household_timezone=settings.household_timezone,
    )


@router.put(
    "/{document_id}/expiration-reminder",
    response_model=DocumentExpirationReminderRead,
)
def change_expiration_reminder(
    document_id: UUID,
    payload: DocumentExpirationReminderUpdate,
    session: Annotated[Session, Depends(get_db)],
) -> DocumentExpirationReminderRead:
    try:
        return DocumentExpirationReminderRead.model_validate(
            configure_document_reminder(
                session,
                document_id=document_id,
                enabled=payload.enabled,
                lead_time_days=payload.lead_time_days,
            )
        )
    except DocumentReminderNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="document not found"
        ) from exc
    except DocumentReminderPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="document reminder is temporarily unavailable",
        ) from exc


@router.post(
    "/{document_id}/expiration-reminder/acknowledge",
    response_model=DocumentReminderActionResponse,
)
def acknowledge_expiration_reminder(
    document_id: UUID,
    session: Annotated[Session, Depends(get_db)],
) -> DocumentReminderActionResponse:
    try:
        return acknowledge_document_reminder(session, document_id=document_id)
    except DocumentReminderUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DocumentReminderPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="document reminder is temporarily unavailable",
        ) from exc


@router.post(
    "/{document_id}/expiration-reminder/snooze",
    response_model=DocumentReminderActionResponse,
)
def snooze_expiration_reminder(
    document_id: UUID,
    payload: DocumentReminderSnooze,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    as_of: Annotated[date | None, Query()] = None,
) -> DocumentReminderActionResponse:
    try:
        return snooze_document_reminder(
            session,
            document_id=document_id,
            until=payload.until,
            as_of=as_of or household_today(settings.household_timezone),
        )
    except DocumentReminderUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DocumentReminderPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="document reminder is temporarily unavailable",
        ) from exc


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: UUID,
    session: Annotated[Session, Depends(get_db)],
) -> DocumentRead:
    try:
        return get_stored_document(session, document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="document not found",
        ) from exc


@router.patch("/{document_id}", response_model=DocumentRead)
def change_document_metadata(
    document_id: UUID,
    payload: DocumentMetadataUpdate,
    session: Annotated[Session, Depends(get_db)],
) -> DocumentRead:
    try:
        return update_document_metadata(
            session,
            document_id=document_id,
            title=payload.title,
            document_type=payload.document_type,
            notes=payload.notes,
            collection_name=payload.collection_name,
            tags=payload.tags,
            fields_set=set(payload.model_fields_set),
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="document not found"
        ) from exc


@router.patch("/{document_id}/facts/{fact_type}", response_model=DocumentFactRead)
def change_document_fact(
    document_id: UUID,
    fact_type: DocumentFactType,
    payload: DocumentFactUpdate,
    session: Annotated[Session, Depends(get_db)],
) -> DocumentFactRead:
    date_types = {DocumentFactType.EXPIRATION_DATE, DocumentFactType.DOCUMENT_DATE}
    if not payload.is_cleared:
        if fact_type in date_types and payload.value_date is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="this document fact requires a date value",
            )
        if fact_type not in date_types and payload.value_text is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="this document fact requires a text value",
            )
    try:
        stored = set_user_document_fact(
            session,
            document_id=document_id,
            fact_type=fact_type,
            value_text=payload.value_text,
            value_date=payload.value_date,
            is_cleared=payload.is_cleared,
        )
        return DocumentFactRead.model_validate(stored)
    except DocumentFactNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="stored document not found",
        ) from exc


@router.get("/{document_id}/facts", response_model=list[DocumentFactRead])
def get_document_facts(
    document_id: UUID,
    session: Annotated[Session, Depends(get_db)],
) -> list[DocumentFactRead]:
    try:
        return [
            DocumentFactRead.model_validate(fact)
            for fact in list_document_facts(session, document_id=document_id)
        ]
    except DocumentFactNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="stored document not found",
        ) from exc
    except DocumentFactPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="document fact is temporarily unavailable",
        ) from exc
    except DocumentMetadataPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="document metadata is temporarily unavailable",
        ) from exc


@router.get("/{document_id}/content")
def get_document_content(
    document_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    storage: Annotated[PrivateDocumentStorage, Depends(get_document_storage)],
) -> Response:
    try:
        document, content = read_stored_document(session, storage, document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="document not found"
        ) from exc
    except DocumentPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="document storage is temporarily unavailable",
        ) from exc
    encoded_filename = quote(document.original_filename, safe="")
    return Response(
        content=content,
        media_type=document.media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put("/{document_id}/extraction", response_model=DocumentExtractionRead)
def extract_document(
    document_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[PrivateDocumentStorage, Depends(get_document_storage)],
    extractor: Annotated[DocumentTextExtractor, Depends(get_document_text_extractor)],
) -> DocumentExtractionRead:
    try:
        return extract_document_text(
            session=session,
            storage=storage,
            extractor=extractor,
            document_id=document_id,
            max_chars=settings.max_document_text_chars,
            stale_after_seconds=settings.document_extraction_stale_seconds,
        )
    except DocumentExtractionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="stored document not found",
        ) from exc
    except DocumentExtractionInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="document extraction is already processing",
        ) from exc
    except DocumentExtractionRejectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="document text exceeds the configured extraction limit",
        ) from exc
    except DocumentExtractionOperationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="document extraction is temporarily unavailable",
        ) from exc


@router.get("/{document_id}/extraction", response_model=DocumentExtractionRead)
def get_document_extraction(
    document_id: UUID,
    session: Annotated[Session, Depends(get_db)],
) -> DocumentExtractionRead:
    try:
        return get_latest_document_extraction(session, document_id)
    except DocumentExtractionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="document extraction not found",
        ) from exc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_document(
    document_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    storage: Annotated[PrivateDocumentStorage, Depends(get_document_storage)],
) -> Response:
    try:
        delete_document(session=session, storage=storage, document_id=document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="document not found",
        ) from exc
    except DocumentDeletionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="document deletion is temporarily unavailable",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
