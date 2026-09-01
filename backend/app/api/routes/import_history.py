from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.import_batch import ImportBatchRead
from app.schemas.import_batch_query import (
    ImportBatchDetailResponse,
    ImportBatchListResponse,
    ImportBatchQueryParams,
)
from app.schemas.transaction_query import PaginationMetadata
from app.services.import_batch_management import delete_import_batch
from app.services.import_batch_query import get_import_batch_detail, query_import_batches

router = APIRouter(prefix="/imports", tags=["imports"])


@router.get("", response_model=ImportBatchListResponse)
def list_import_batches(
    params: Annotated[ImportBatchQueryParams, Query()],
    session: Annotated[Session, Depends(get_db)],
) -> ImportBatchListResponse:
    result = query_import_batches(
        session,
        status=params.status,
        offset=params.offset,
        limit=params.limit,
    )
    return ImportBatchListResponse(
        items=[ImportBatchRead.model_validate(item) for item in result.items],
        pagination=PaginationMetadata(
            total=result.total,
            offset=result.offset,
            limit=result.limit,
            returned=len(result.items),
            has_more=result.has_more,
        ),
    )


@router.get("/{batch_id}", response_model=ImportBatchDetailResponse)
def retrieve_import_batch(
    batch_id: UUID,
    session: Annotated[Session, Depends(get_db)],
) -> ImportBatchDetailResponse:
    result = get_import_batch_detail(session, batch_id=batch_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import batch not found",
        )

    batch = ImportBatchRead.model_validate(result.batch)
    return ImportBatchDetailResponse(
        **batch.model_dump(),
        transaction_count=result.transaction_count,
        duplicate_candidate_count=result.duplicate_candidate_count,
        transactions_url=f"/transactions?import_batch_id={batch.id}",
        duplicate_candidates_url=f"/duplicate-candidates?import_batch_id={batch.id}",
        row_errors_persisted=False,
    )


@router.delete("/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_import_batch(
    batch_id: UUID,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    if not delete_import_batch(session, batch_id=batch_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import batch not found",
        )
