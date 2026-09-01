from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

DocumentQuestionText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]


class DocumentQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: DocumentQuestionText
    document_id: UUID | None = None


class DocumentCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: Annotated[str, Field(pattern=r"^C[1-9][0-9]*$")]
    document_id: UUID
    chunk_id: UUID
    original_filename: Annotated[str, Field(min_length=1, max_length=255)]
    page_number: Annotated[int, Field(gt=0)]
    section_number: Annotated[int, Field(gt=0)]
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(gt=0)]
    document_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    chunk_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    excerpt: Annotated[str, Field(min_length=1)]


class DocumentQuestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["verified", "no_results", "analytics_required"]
    answer: Annotated[str, Field(min_length=1, max_length=4000)]
    verified: bool
    evidence_status: Literal["supported", "conflicting", "none"]
    model: str | None
    retrieval_terms: list[str]
    citations: list[DocumentCitation]
