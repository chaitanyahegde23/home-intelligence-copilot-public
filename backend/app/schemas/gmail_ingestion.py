from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.gmail_ingestion import GmailIngestionStatus


class GmailIngestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    sender: str
    subject: str | None
    received_at: datetime
    original_filename: str
    status: GmailIngestionStatus
    attempt_count: int
    failure_code: str | None
    document_id: UUID | None
    created_at: datetime
    updated_at: datetime


class GmailIngestionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    poll_interval_seconds: int
    allowed_sender_count: int
    items: list[GmailIngestionRead]
    limit: int = Field(ge=1, le=100)
