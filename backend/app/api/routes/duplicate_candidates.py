from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import DuplicateCandidate
from app.schemas.duplicate_candidate import DuplicateCandidateRead, DuplicateCandidateReview
from app.schemas.duplicate_candidate_query import (
    DuplicateCandidateDetail,
    DuplicateCandidateListResponse,
    DuplicateCandidateQueryParams,
    DuplicateTransactionEvidence,
)
from app.schemas.import_batch import ImportBatchRead
from app.schemas.transaction import TransactionRead
from app.schemas.transaction_query import PaginationMetadata
from app.services.duplicate_candidate_query import (
    DuplicateCandidateFilters,
    get_duplicate_candidate,
    query_duplicate_candidates,
    review_duplicate_candidate,
)

router = APIRouter(prefix="/duplicate-candidates", tags=["duplicate candidates"])


@router.get("", response_model=DuplicateCandidateListResponse)
def list_duplicate_candidates(
    params: Annotated[DuplicateCandidateQueryParams, Query()],
    session: Annotated[Session, Depends(get_db)],
) -> DuplicateCandidateListResponse:
    result = query_duplicate_candidates(
        session,
        filters=DuplicateCandidateFilters(
            status=params.status,
            import_batch_id=params.import_batch_id,
        ),
        offset=params.offset,
        limit=params.limit,
    )
    return DuplicateCandidateListResponse(
        items=[candidate_detail(candidate) for candidate in result.items],
        pagination=PaginationMetadata(
            total=result.total,
            offset=result.offset,
            limit=result.limit,
            returned=len(result.items),
            has_more=result.has_more,
        ),
    )


@router.get("/{candidate_id}", response_model=DuplicateCandidateDetail)
def retrieve_duplicate_candidate(
    candidate_id: UUID,
    session: Annotated[Session, Depends(get_db)],
) -> DuplicateCandidateDetail:
    candidate = get_duplicate_candidate(session, candidate_id=candidate_id)
    if candidate is None:
        raise candidate_not_found()
    return candidate_detail(candidate)


@router.patch("/{candidate_id}", response_model=DuplicateCandidateDetail)
def update_duplicate_candidate_review(
    candidate_id: UUID,
    review: DuplicateCandidateReview,
    session: Annotated[Session, Depends(get_db)],
) -> DuplicateCandidateDetail:
    candidate = review_duplicate_candidate(
        session,
        candidate_id=candidate_id,
        status=review.status,
        resolution_note=review.resolution_note,
    )
    if candidate is None:
        raise candidate_not_found()
    return candidate_detail(candidate)


def candidate_detail(candidate: DuplicateCandidate) -> DuplicateCandidateDetail:
    candidate_data = DuplicateCandidateRead.model_validate(candidate)
    return DuplicateCandidateDetail(
        **candidate_data.model_dump(),
        first=DuplicateTransactionEvidence(
            transaction=TransactionRead.model_validate(candidate.first_transaction),
            import_batch=ImportBatchRead.model_validate(candidate.first_transaction.import_batch),
        ),
        second=DuplicateTransactionEvidence(
            transaction=TransactionRead.model_validate(candidate.second_transaction),
            import_batch=ImportBatchRead.model_validate(candidate.second_transaction.import_batch),
        ),
    )


def candidate_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Duplicate candidate not found",
    )
