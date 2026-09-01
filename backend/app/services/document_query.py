from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Document, DocumentChunk, DocumentExtraction, DocumentMetadataInference
from app.models.document import DocumentStatus
from app.models.document_extraction import DocumentExtractionStatus
from app.schemas.document import DocumentFactRead, DocumentMetadataInferenceRead
from app.schemas.document_query import DocumentLibraryItem
from app.schemas.document_reminder import DocumentExpirationReminderRead


@dataclass(frozen=True)
class DocumentQueryResult:
    items: list[DocumentLibraryItem]
    total: int
    offset: int
    limit: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


def query_documents(
    session: Session,
    *,
    offset: int,
    limit: int,
    document_type: str | None = None,
    name: str | None = None,
    collection_name: str | None = None,
) -> DocumentQueryResult:
    filters = []
    if document_type is not None:
        filters.append(Document.document_type == document_type)
    if name is not None:
        normalized_name = f"%{name.strip().lower()}%"
        filters.append(
            or_(
                func.lower(Document.title).like(normalized_name),
                func.lower(Document.original_filename).like(normalized_name),
            )
        )
    if collection_name is not None:
        filters.append(Document.collection_name == collection_name)
    total = session.scalar(select(func.count()).select_from(Document).where(*filters)) or 0
    documents = list(
        session.scalars(
            select(Document)
            .options(
                selectinload(Document.facts),
                selectinload(Document.expiration_reminder),
            )
            .where(*filters)
            .order_by(Document.created_at.desc(), Document.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    if not documents:
        return DocumentQueryResult(items=[], total=total, offset=offset, limit=limit)

    document_ids = [document.id for document in documents]
    latest_by_document: dict[UUID, DocumentExtraction] = {}
    for extraction in session.scalars(
        select(DocumentExtraction)
        .where(DocumentExtraction.document_id.in_(document_ids))
        .order_by(
            DocumentExtraction.document_id,
            DocumentExtraction.created_at.desc(),
            DocumentExtraction.id.desc(),
        )
    ):
        latest_by_document.setdefault(extraction.document_id, extraction)

    extraction_ids = [extraction.id for extraction in latest_by_document.values()]
    latest_inference_by_document: dict[UUID, DocumentMetadataInference] = {}
    for inference in session.scalars(
        select(DocumentMetadataInference)
        .where(DocumentMetadataInference.document_id.in_(document_ids))
        .order_by(
            DocumentMetadataInference.document_id,
            DocumentMetadataInference.created_at.desc(),
            DocumentMetadataInference.id.desc(),
        )
    ):
        latest_inference_by_document.setdefault(inference.document_id, inference)
    chunk_counts: dict[UUID, int] = {}
    if extraction_ids:
        chunk_counts = {
            extraction_id: count
            for extraction_id, count in session.execute(
                select(DocumentChunk.extraction_id, func.count(DocumentChunk.id))
                .where(DocumentChunk.extraction_id.in_(extraction_ids))
                .group_by(DocumentChunk.extraction_id)
            )
        }

    items = [
        _library_item(
            document,
            latest_by_document.get(document.id),
            latest_inference_by_document.get(document.id),
            chunk_counts,
        )
        for document in documents
    ]
    return DocumentQueryResult(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


def _library_item(
    document: Document,
    extraction: DocumentExtraction | None,
    metadata_inference: DocumentMetadataInference | None,
    chunk_counts: dict[UUID, int],
) -> DocumentLibraryItem:
    chunk_count = chunk_counts.get(extraction.id, 0) if extraction is not None else 0
    extraction_status = extraction.status if extraction is not None else None
    return DocumentLibraryItem(
        id=document.id,
        status=document.status,
        original_filename=document.original_filename,
        media_type=document.media_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        source=document.source,
        title=document.title,
        title_source=document.title_source,
        document_type=document.document_type,
        document_type_source=document.document_type_source,
        notes=document.notes,
        collection_name=document.collection_name,
        tags=document.tags,
        metadata_inference=(
            DocumentMetadataInferenceRead.model_validate(metadata_inference)
            if metadata_inference is not None
            else None
        ),
        facts=[DocumentFactRead.model_validate(fact) for fact in document.facts],
        expiration_reminder=(
            DocumentExpirationReminderRead.model_validate(document.expiration_reminder)
            if document.expiration_reminder is not None
            else None
        ),
        created_at=document.created_at,
        updated_at=document.updated_at,
        latest_extraction_status=extraction_status,
        latest_extraction_updated_at=extraction.updated_at if extraction is not None else None,
        chunk_count=chunk_count,
        is_searchable=(
            document.status is DocumentStatus.STORED
            and extraction_status is DocumentExtractionStatus.COMPLETED
            and chunk_count > 0
        ),
    )
