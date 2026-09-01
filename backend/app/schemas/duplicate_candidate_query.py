from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models import DuplicateStatus
from app.schemas.duplicate_candidate import DuplicateCandidateRead
from app.schemas.import_batch import ImportBatchRead
from app.schemas.transaction import TransactionRead
from app.schemas.transaction_query import PaginationMetadata

Limit = Annotated[int, Field(ge=1, le=100)]
Offset = Annotated[int, Field(ge=0)]


class DuplicateCandidateQueryParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: DuplicateStatus | None = None
    import_batch_id: UUID | None = None
    limit: Limit = 50
    offset: Offset = 0


class DuplicateTransactionEvidence(BaseModel):
    transaction: TransactionRead
    import_batch: ImportBatchRead


class DuplicateCandidateDetail(DuplicateCandidateRead):
    first: DuplicateTransactionEvidence
    second: DuplicateTransactionEvidence


class DuplicateCandidateListResponse(BaseModel):
    items: list[DuplicateCandidateDetail]
    pagination: PaginationMetadata
