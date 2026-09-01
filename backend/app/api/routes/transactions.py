from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.transaction_query import (
    PaginationMetadata,
    TransactionFilterSummary,
    TransactionListItem,
    TransactionListResponse,
    TransactionQueryParams,
)
from app.services.transaction_query import TransactionFilters, query_transactions

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=TransactionListResponse)
def list_transactions(
    params: Annotated[TransactionQueryParams, Query()],
    session: Annotated[Session, Depends(get_db)],
) -> TransactionListResponse:
    result = query_transactions(
        session,
        filters=TransactionFilters(
            start_date=params.start_date,
            end_date=params.end_date,
            account_name=params.account_name,
            category=params.category,
            merchant_name=params.merchant_name,
            import_batch_id=params.import_batch_id,
        ),
        offset=params.offset,
        limit=params.limit,
    )
    return TransactionListResponse(
        items=[TransactionListItem.model_validate(item) for item in result.items],
        pagination=PaginationMetadata(
            total=result.total,
            offset=result.offset,
            limit=result.limit,
            returned=len(result.items),
            has_more=result.has_more,
        ),
        summary=TransactionFilterSummary(
            transaction_count=result.total,
            gross_amount=result.gross_amount,
            spending_amount=result.spending_amount,
            income_amount=result.income_amount,
            net_amount=result.net_amount,
        ),
    )
