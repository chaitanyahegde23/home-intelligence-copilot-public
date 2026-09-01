from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class RetrievalScope(StrEnum):
    LOCAL_SINGLE_HOUSEHOLD = "local_single_household"


class DocumentChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    document_id: UUID
    extraction_id: UUID
    text_span_id: UUID
    chunker_name: Annotated[str, Field(min_length=1, max_length=100)]
    chunker_version: Annotated[str, Field(min_length=1, max_length=50)]
    chunk_index: Annotated[int, Field(gt=0)]
    page_number: Annotated[int, Field(gt=0)]
    section_number: Annotated[int, Field(gt=0)]
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(gt=0)]
    text: Annotated[str, Field(min_length=1)]
    text_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_offsets(self) -> "DocumentChunkRead":
        if self.end_offset - self.start_offset != len(self.text):
            raise ValueError("chunk text length must match its span-relative offsets")
        return self


class DocumentChunkBuildResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    extraction_id: UUID
    chunker_name: str
    chunker_version: str
    chunk_count: Annotated[int, Field(ge=0)]
    chunks: list[DocumentChunkRead]


class DocumentSearchResult(DocumentChunkRead):
    original_filename: Annotated[str, Field(min_length=1, max_length=255)]
    document_sha256: Sha256Digest
    extractor_name: Annotated[str, Field(min_length=1, max_length=100)]
    extractor_version: Annotated[str, Field(min_length=1, max_length=50)]
    relevance_score: Annotated[Decimal, Field(gt=0)]


class DocumentSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, Field(min_length=1, max_length=200)]
    terms: list[str]
    scope: Literal[RetrievalScope.LOCAL_SINGLE_HOUSEHOLD]
    search_config: Literal["simple"] = "simple"
    result_count: Annotated[int, Field(ge=0)]
    limit: Annotated[int, Field(ge=1, le=50)]
    results: list[DocumentSearchResult]
