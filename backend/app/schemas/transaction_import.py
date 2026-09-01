from uuid import UUID

from pydantic import BaseModel, Field

from app.models.import_batch import ImportStatus
from app.schemas.import_adapter import AccountLabel, AdapterName, AdapterVersion


class RowValidationError(BaseModel):
    row_number: int | None = None
    field: str | None = None
    message: str


class TransactionImportResponse(BaseModel):
    import_batch_id: UUID
    filename: str
    adapter_name: AdapterName
    adapter_version: AdapterVersion
    account_label: AccountLabel | None
    status: ImportStatus
    total_rows: int = Field(ge=0)
    imported_rows: int = Field(ge=0)
    rejected_rows: int = Field(ge=0)
    duplicate_candidates_created: int = Field(default=0, ge=0)
    errors: list[RowValidationError] = Field(default_factory=list)
