from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.document_extraction import DocumentExtractionStatus

Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class DocumentTextSpanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    page_number: Annotated[int, Field(gt=0)]
    section_number: Annotated[int, Field(gt=0)]
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(ge=0)]
    text: str
    text_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_offsets(self) -> "DocumentTextSpanRead":
        if self.end_offset < self.start_offset:
            raise ValueError("end_offset must be greater than or equal to start_offset")
        if self.end_offset - self.start_offset != len(self.text):
            raise ValueError("text length must match the source offsets")
        return self


class DocumentExtractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    document_id: UUID
    status: DocumentExtractionStatus
    extractor_name: Annotated[str, Field(min_length=1, max_length=100)]
    extractor_version: Annotated[str, Field(min_length=1, max_length=50)]
    document_sha256: Sha256Digest
    started_at: datetime
    completed_at: datetime | None
    failure_code: Annotated[str, Field(min_length=1, max_length=100)] | None
    spans: list[DocumentTextSpanRead]
    created_at: datetime
    updated_at: datetime
