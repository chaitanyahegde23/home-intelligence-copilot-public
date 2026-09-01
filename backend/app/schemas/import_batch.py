from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.import_batch import (
    CANONICAL_ADAPTER_NAME,
    CANONICAL_ADAPTER_VERSION,
    ImportStatus,
)
from app.schemas.import_adapter import AccountLabel, AdapterName, AdapterVersion
from app.schemas.transaction import TransactionRead

RequiredFilename = Annotated[str, Field(min_length=1, max_length=512)]
NonNegativeCount = Annotated[int, Field(ge=0)]


class ImportBatchCreate(BaseModel):
    filename: RequiredFilename
    adapter_name: AdapterName = CANONICAL_ADAPTER_NAME
    adapter_version: AdapterVersion = CANONICAL_ADAPTER_VERSION
    account_label: AccountLabel | None = None
    status: ImportStatus = ImportStatus.PENDING
    row_count: NonNegativeCount = 0
    imported_count: NonNegativeCount = 0
    rejected_count: NonNegativeCount = 0


class ImportBatchRead(ImportBatchCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class ImportBatchWithTransactions(ImportBatchRead):
    transactions: list[TransactionRead] = Field(default_factory=list)
