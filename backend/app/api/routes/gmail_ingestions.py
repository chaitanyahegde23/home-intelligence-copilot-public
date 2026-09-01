from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.gmail_ingestion import GmailIngestion
from app.schemas.gmail_ingestion import GmailIngestionListResponse, GmailIngestionRead

router = APIRouter(prefix="/gmail-ingestions", tags=["gmail document ingestion"])


@router.get("", response_model=GmailIngestionListResponse)
def list_gmail_ingestions(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> GmailIngestionListResponse:
    records = list(
        session.scalars(
            select(GmailIngestion)
            .order_by(GmailIngestion.updated_at.desc(), GmailIngestion.id.desc())
            .limit(limit)
        )
    )
    return GmailIngestionListResponse(
        enabled=settings.gmail_ingestion_enabled,
        poll_interval_seconds=settings.gmail_poll_interval_seconds,
        allowed_sender_count=len(settings.gmail_allowed_senders),
        items=[GmailIngestionRead.model_validate(record) for record in records],
        limit=limit,
    )
