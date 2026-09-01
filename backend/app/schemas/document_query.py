from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.document import DocumentSource, DocumentStatus
from app.models.document_extraction import DocumentExtractionStatus
from app.schemas.document import (
    DocumentFactRead,
    DocumentMetadataInferenceRead,
    DocumentMetadataSource,
    Sha256Digest,
)
from app.schemas.document_reminder import DocumentExpirationReminderRead
from app.schemas.transaction_query import PaginationMetadata

Limit = Annotated[int, Field(ge=1, le=100)]
Offset = Annotated[int, Field(ge=0)]


class DocumentQueryParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: Limit = 50
    offset: Offset = 0
    document_type: Annotated[
        str | None, Field(min_length=1, max_length=50, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    ] = None
    name: Annotated[str | None, Field(min_length=1, max_length=100)] = None
    collection_name: Annotated[str | None, Field(min_length=1, max_length=100)] = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized


class DocumentLibraryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: DocumentStatus
    original_filename: Annotated[str, Field(min_length=1, max_length=255)]
    media_type: Annotated[str, Field(min_length=1, max_length=100)]
    size_bytes: Annotated[int, Field(gt=0)]
    sha256: Sha256Digest
    source: DocumentSource
    title: str | None
    title_source: DocumentMetadataSource | None
    document_type: str | None
    document_type_source: DocumentMetadataSource | None
    notes: str | None
    collection_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata_inference: DocumentMetadataInferenceRead | None
    facts: list[DocumentFactRead]
    expiration_reminder: DocumentExpirationReminderRead | None
    created_at: datetime
    updated_at: datetime
    latest_extraction_status: DocumentExtractionStatus | None
    latest_extraction_updated_at: datetime | None
    chunk_count: Annotated[int, Field(ge=0)]
    is_searchable: bool


class DocumentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DocumentLibraryItem]
    pagination: PaginationMetadata
