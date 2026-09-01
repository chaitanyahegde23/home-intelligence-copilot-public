from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.document_retrieval import (
    DocumentChunkBuildResponse,
    DocumentSearchResponse,
    RetrievalScope,
)
from app.services.document_chunker import DeterministicCharacterChunker
from app.services.document_retrieval import (
    DocumentRetrievalNotFoundError,
    DocumentRetrievalPersistenceError,
    DocumentRetrievalValidationError,
    build_document_chunks,
    get_document_chunker,
    search_document_chunks,
)

router = APIRouter(prefix="/documents", tags=["document retrieval"])


@router.get("/search", response_model=DocumentSearchResponse)
def search_documents(
    query: Annotated[str, Query(alias="q", min_length=1, max_length=200)],
    session: Annotated[Session, Depends(get_db)],
    chunker: Annotated[DeterministicCharacterChunker, Depends(get_document_chunker)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> DocumentSearchResponse:
    try:
        return search_document_chunks(
            session=session,
            query=query,
            limit=limit,
            scope=RetrievalScope.LOCAL_SINGLE_HOUSEHOLD,
            chunker=chunker,
        )
    except DocumentRetrievalValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.put("/{document_id}/chunks", response_model=DocumentChunkBuildResponse)
def create_document_chunks(
    document_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    chunker: Annotated[DeterministicCharacterChunker, Depends(get_document_chunker)],
) -> DocumentChunkBuildResponse:
    try:
        return build_document_chunks(
            session=session,
            document_id=document_id,
            chunker=chunker,
            max_chars=settings.document_chunk_max_chars,
        )
    except DocumentRetrievalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="completed document extraction not found",
        ) from exc
    except DocumentRetrievalPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="document chunks are temporarily unavailable",
        ) from exc
