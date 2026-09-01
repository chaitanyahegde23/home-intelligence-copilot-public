from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models.document import DocumentSource, DocumentStatus
from app.models.document_fact import DocumentFactType

Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
DocumentTitle = Annotated[str, Field(min_length=1, max_length=255)]
DocumentType = Annotated[str, Field(min_length=1, max_length=50, pattern=r"^[a-z0-9][a-z0-9_-]*$")]
DocumentNotes = Annotated[str, Field(min_length=1, max_length=2000)]
DocumentCollection = Annotated[str, Field(min_length=1, max_length=100)]
DocumentTag = Annotated[str, Field(min_length=1, max_length=50, pattern=r"^[a-z0-9][a-z0-9 _-]*$")]
DocumentMetadataSource = Literal["automatic", "user"]
DocumentExpirationStatus = Literal["expired", "expires_today", "upcoming"]


class DocumentMetadataInferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    classifier_name: Annotated[str, Field(min_length=1, max_length=100)]
    classifier_version: Annotated[str, Field(min_length=1, max_length=50)]
    suggested_title: DocumentTitle
    title_evidence_code: Annotated[str, Field(min_length=1, max_length=100)]
    suggested_document_type: DocumentType | None
    document_type_confidence: Annotated[Decimal, Field(ge=0, le=1)] | None
    evidence_codes: list[Annotated[str, Field(min_length=1, max_length=100)]]


class DocumentFactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    fact_type: DocumentFactType
    value_text: Annotated[str, Field(min_length=1, max_length=255)] | None
    value_date: date | None
    is_cleared: bool
    source: DocumentMetadataSource
    confidence: Annotated[Decimal, Field(ge=0, le=1)] | None
    source_page_number: Annotated[int, Field(gt=0)] | None
    inference_name: Annotated[str, Field(min_length=1, max_length=100)]
    inference_version: Annotated[str, Field(min_length=1, max_length=50)]
    evidence_code: Annotated[str, Field(min_length=1, max_length=100)]


class DocumentFactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value_text: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    value_date: date | None = None
    is_cleared: bool = False

    @field_validator("value_text", mode="before")
    @classmethod
    def normalize_fact_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = " ".join(value.split())
            return normalized or None
        return value

    @model_validator(mode="after")
    def validate_fact_value(self) -> "DocumentFactUpdate":
        supplied = int(self.value_text is not None) + int(self.value_date is not None)
        if self.is_cleared and supplied:
            raise ValueError("a cleared fact cannot include a value")
        if not self.is_cleared and supplied != 1:
            raise ValueError("exactly one fact value is required")
        return self


class DocumentExpirationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    display_name: DocumentTitle
    expiration_date: date
    days_until_expiration: int
    status: DocumentExpirationStatus
    source: DocumentMetadataSource
    confidence: Annotated[Decimal, Field(ge=0, le=1)] | None
    source_page_number: Annotated[int, Field(gt=0)] | None


class DocumentExpirationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: date
    within_days: Annotated[int, Field(ge=0, le=3650)]
    items: list[DocumentExpirationItem]


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    status: DocumentStatus
    original_filename: Annotated[str, Field(min_length=1, max_length=255)]
    media_type: Annotated[str, Field(min_length=1, max_length=100)]
    size_bytes: Annotated[int, Field(gt=0)]
    sha256: Sha256Digest
    storage_backend: Annotated[str, Field(min_length=1, max_length=50)]
    source: DocumentSource
    title: DocumentTitle | None
    title_source: DocumentMetadataSource | None
    document_type: DocumentType | None
    document_type_source: DocumentMetadataSource | None
    notes: DocumentNotes | None
    collection_name: DocumentCollection | None = None
    tags: list[DocumentTag] = Field(default_factory=list, max_length=20)
    created_at: datetime
    updated_at: datetime


class DuplicateDocumentDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = "duplicate_document"
    existing_document_id: UUID


class DocumentMetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: DocumentTitle | None = None
    document_type: DocumentType | None = None
    notes: DocumentNotes | None = None
    collection_name: DocumentCollection | None = None
    tags: list[DocumentTag] | None = Field(default=None, max_length=20)

    @field_validator("title", "document_type", "notes", "collection_name", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = " ".join(value.split())
            return normalized or None
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, list):
            return value
        normalized = [" ".join(tag.casefold().split()) for tag in value if isinstance(tag, str)]
        return list(dict.fromkeys(tag for tag in normalized if tag))

    @model_validator(mode="after")
    def validate_patch(self) -> "DocumentMetadataUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one document metadata field is required")
        return self
