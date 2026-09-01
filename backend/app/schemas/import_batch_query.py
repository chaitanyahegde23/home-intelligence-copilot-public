from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.models.import_batch import ImportStatus
from app.schemas.import_batch import ImportBatchRead
from app.schemas.transaction_query import PaginationMetadata

Limit = Annotated[int, Field(ge=1, le=100)]
Offset = Annotated[int, Field(ge=0)]


class ImportBatchQueryParams(BaseModel):
    status: ImportStatus | None = None
    limit: Limit = 50
    offset: Offset = 0


class ImportBatchListResponse(BaseModel):
    items: list[ImportBatchRead]
    pagination: PaginationMetadata


class ImportBatchDetailResponse(ImportBatchRead):
    transaction_count: int = Field(ge=0)
    duplicate_candidate_count: int = Field(ge=0)
    transactions_url: str = Field(min_length=1)
    duplicate_candidates_url: str = Field(min_length=1)
    row_errors_persisted: Literal[False] = False
