from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ReminderStatus = Literal["expired", "expires_today", "upcoming"]
ReminderChannel = Literal["in_app"]


class DocumentExpirationReminderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    enabled: bool
    channel: ReminderChannel
    lead_time_days: Annotated[int, Field(ge=0, le=3650)]
    acknowledged_expiration_date: date | None
    snoozed_until: date | None
    updated_at: datetime


class DocumentExpirationReminderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    lead_time_days: Annotated[int, Field(ge=0, le=3650)] = 90


class DocumentReminderSnooze(BaseModel):
    model_config = ConfigDict(extra="forbid")

    until: date


class DocumentReminderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    display_name: Annotated[str, Field(min_length=1, max_length=255)]
    expiration_date: date
    days_until_expiration: int
    status: ReminderStatus
    lead_time_days: Annotated[int, Field(ge=0, le=3650)]
    channel: ReminderChannel


class DocumentReminderListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: date
    household_timezone: str
    items: list[DocumentReminderItem]


class DocumentReminderActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reminder: DocumentExpirationReminderRead
    expiration_date: date
