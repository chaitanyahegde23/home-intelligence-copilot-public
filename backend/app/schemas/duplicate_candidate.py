from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from app.models.duplicate_candidate import DuplicateStatus

DuplicateFingerprint = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
DuplicateReason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
ResolutionNote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]


class DuplicateCandidateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_transaction_id: UUID
    second_transaction_id: UUID
    fingerprint: DuplicateFingerprint
    reason: DuplicateReason

    @model_validator(mode="after")
    def validate_pair_order(self) -> Self:
        if self.first_transaction_id >= self.second_transaction_id:
            raise ValueError("first_transaction_id must be less than second_transaction_id")
        return self


class DuplicateCandidateReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[DuplicateStatus.CONFIRMED, DuplicateStatus.DISMISSED]
    resolution_note: ResolutionNote | None = None


class DuplicateCandidateRead(DuplicateCandidateCreate):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    status: DuplicateStatus
    resolution_note: str | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_resolution_state(self) -> Self:
        if self.status is DuplicateStatus.UNRESOLVED and self.resolved_at is not None:
            raise ValueError("unresolved candidates cannot have resolved_at")
        if self.status is not DuplicateStatus.UNRESOLVED and self.resolved_at is None:
            raise ValueError("resolved candidates require resolved_at")
        return self
