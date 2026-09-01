from __future__ import annotations

from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from app.models.document import Document, DocumentStatus
from app.models.document_fact import DocumentFact, DocumentFactType
from app.models.document_reminder import DocumentExpirationReminder
from app.schemas.document_reminder import (
    DocumentExpirationReminderRead,
    DocumentReminderActionResponse,
    DocumentReminderItem,
    DocumentReminderListResponse,
    ReminderStatus,
)


class DocumentReminderNotFoundError(LookupError):
    pass


class DocumentReminderUnavailableError(ValueError):
    pass


class DocumentReminderPersistenceError(RuntimeError):
    pass


def household_today(timezone_name: str) -> date:
    return datetime.now(ZoneInfo(timezone_name)).date()


def configure_document_reminder(
    session: Session,
    *,
    document_id: UUID,
    enabled: bool,
    lead_time_days: int,
) -> DocumentExpirationReminder:
    document = session.scalar(
        select(Document)
        .options(joinedload(Document.expiration_reminder))
        .where(Document.id == document_id, Document.status == DocumentStatus.STORED)
    )
    if document is None:
        raise DocumentReminderNotFoundError
    reminder = document.expiration_reminder
    if reminder is None:
        reminder = DocumentExpirationReminder(
            household_id=document.household_id,
            document_id=document.id,
            enabled=enabled,
            lead_time_days=lead_time_days,
        )
        session.add(reminder)
    else:
        reminder.enabled = enabled
        reminder.lead_time_days = lead_time_days
    try:
        session.commit()
        session.refresh(reminder)
    except SQLAlchemyError as exc:
        session.rollback()
        raise DocumentReminderPersistenceError from exc
    return reminder


def list_due_document_reminders(
    session: Session,
    *,
    as_of: date,
    household_timezone: str,
) -> DocumentReminderListResponse:
    rows = session.execute(
        select(DocumentExpirationReminder, Document, DocumentFact)
        .join(Document, Document.id == DocumentExpirationReminder.document_id)
        .join(DocumentFact, DocumentFact.document_id == Document.id)
        .where(
            DocumentExpirationReminder.enabled.is_(True),
            DocumentExpirationReminder.channel == "in_app",
            Document.status == DocumentStatus.STORED,
            DocumentFact.fact_type == DocumentFactType.EXPIRATION_DATE.value,
            DocumentFact.is_cleared.is_(False),
            DocumentFact.value_date.is_not(None),
        )
    ).all()
    items: list[DocumentReminderItem] = []
    for reminder, document, fact in rows:
        expiration_date = fact.value_date
        assert expiration_date is not None
        days = (expiration_date - as_of).days
        if days > reminder.lead_time_days:
            continue
        if reminder.acknowledged_expiration_date == expiration_date:
            continue
        if reminder.snoozed_until is not None and reminder.snoozed_until >= as_of:
            continue
        status: ReminderStatus = (
            "expired" if days < 0 else "expires_today" if days == 0 else "upcoming"
        )
        items.append(
            DocumentReminderItem(
                document_id=document.id,
                display_name=document.title or document.original_filename,
                expiration_date=expiration_date,
                days_until_expiration=days,
                status=status,
                lead_time_days=reminder.lead_time_days,
                channel=reminder.channel,
            )
        )
    items.sort(key=lambda item: (item.expiration_date, str(item.document_id)))
    return DocumentReminderListResponse(
        as_of=as_of,
        household_timezone=household_timezone,
        items=items,
    )


def acknowledge_document_reminder(
    session: Session,
    *,
    document_id: UUID,
) -> DocumentReminderActionResponse:
    reminder, expiration_date = _active_reminder_and_expiration(session, document_id)
    reminder.acknowledged_expiration_date = expiration_date
    reminder.snoozed_until = None
    _commit_reminder(session, reminder)
    return DocumentReminderActionResponse(
        reminder=DocumentExpirationReminderRead.model_validate(reminder),
        expiration_date=expiration_date,
    )


def snooze_document_reminder(
    session: Session,
    *,
    document_id: UUID,
    until: date,
    as_of: date,
) -> DocumentReminderActionResponse:
    if until <= as_of:
        raise DocumentReminderUnavailableError("snooze date must be after the household date")
    reminder, expiration_date = _active_reminder_and_expiration(session, document_id)
    reminder.snoozed_until = until
    _commit_reminder(session, reminder)
    return DocumentReminderActionResponse(
        reminder=DocumentExpirationReminderRead.model_validate(reminder),
        expiration_date=expiration_date,
    )


def _active_reminder_and_expiration(
    session: Session, document_id: UUID
) -> tuple[DocumentExpirationReminder, date]:
    row = session.execute(
        select(DocumentExpirationReminder, DocumentFact.value_date)
        .join(Document, Document.id == DocumentExpirationReminder.document_id)
        .join(DocumentFact, DocumentFact.document_id == Document.id)
        .where(
            Document.id == document_id,
            Document.status == DocumentStatus.STORED,
            DocumentExpirationReminder.enabled.is_(True),
            DocumentFact.fact_type == DocumentFactType.EXPIRATION_DATE.value,
            DocumentFact.is_cleared.is_(False),
            DocumentFact.value_date.is_not(None),
        )
    ).one_or_none()
    if row is None:
        raise DocumentReminderUnavailableError(
            "an enabled reminder and current expiration date are required"
        )
    reminder, expiration_date = row
    assert expiration_date is not None
    return reminder, expiration_date


def _commit_reminder(session: Session, reminder: DocumentExpirationReminder) -> None:
    try:
        session.commit()
        session.refresh(reminder)
    except SQLAlchemyError as exc:
        session.rollback()
        raise DocumentReminderPersistenceError from exc
