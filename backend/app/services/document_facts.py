from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentStatus
from app.models.document_extraction import DocumentExtraction
from app.models.document_fact import DocumentFact, DocumentFactType
from app.schemas.document import (
    DocumentExpirationItem,
    DocumentExpirationResponse,
    DocumentExpirationStatus,
)
from app.services.document_text_extractor import ExtractedDocumentText
from app.services.document_text_extractor import ExtractedTextSpan as ExtractedTextValue

INFERENCE_NAME = "household_document_facts"
INFERENCE_VERSION = "1"

_DATE_VALUE = (
    r"(?:\d{4}-\d{2}-\d{2}|"
    r"[A-Za-z]+\s+\d{1,2},\s+\d{4}|"
    r"\d{1,2}\s+[A-Za-z]+\s+\d{4})"
)
_EXPIRATION_PATTERN = re.compile(
    rf"\b(?P<label>expiration date|expiry date|expires|valid until|valid through)\b"
    rf"\s*[:\-]?\s*(?P<value>{_DATE_VALUE})",
    re.IGNORECASE,
)
_DOCUMENT_DATE_PATTERN = re.compile(
    rf"\b(?P<label>date of issue|issue date|document date|issued on)\b"
    rf"\s*[:\-]?\s*(?P<value>{_DATE_VALUE})",
    re.IGNORECASE,
)
_TEXT_PATTERNS: dict[DocumentFactType, re.Pattern[str]] = {
    DocumentFactType.ISSUER: re.compile(
        r"^(?P<label>issuer|issued by|provider|authority)\s*:\s*(?P<value>[^\n]{2,120})$",
        re.IGNORECASE,
    ),
    DocumentFactType.REFERENCE_NUMBER: re.compile(
        r"^(?P<label>reference|document number|policy number|passport number|"
        r"receipt number|invoice number)\s*:\s*(?P<value>[A-Za-z0-9][A-Za-z0-9 ./_-]{2,63})$",
        re.IGNORECASE,
    ),
}
_SUBTYPE_SIGNALS = {
    "passport": ("passport",),
    "visa": ("visa application", "entry visa", "visa letter"),
    "insurance_policy": ("insurance policy",),
    "warranty": ("limited warranty", "home warranty", "warranty expires"),
    "tax_return": ("form 1040", "tax return"),
    "invoice": ("tax invoice", "invoice number"),
    "receipt": ("purchase receipt", "payment receipt", "receipt number"),
    "employment_letter": ("offer letter", "employment letter"),
}


@dataclass(frozen=True)
class InferredDocumentFact:
    fact_type: DocumentFactType
    value_text: str | None
    value_date: date | None
    confidence: Decimal
    page_number: int
    evidence_code: str


class DocumentFactNotFoundError(LookupError):
    pass


class DocumentFactPersistenceError(RuntimeError):
    pass


def infer_document_facts(extracted: ExtractedDocumentText) -> tuple[InferredDocumentFact, ...]:
    candidates: dict[DocumentFactType, list[InferredDocumentFact]] = {}
    for span in extracted.spans:
        for line in span.text.splitlines():
            normalized_line = " ".join(line.split())
            if not normalized_line:
                continue
            _collect_date_candidate(
                candidates,
                DocumentFactType.EXPIRATION_DATE,
                _EXPIRATION_PATTERN,
                normalized_line,
                span.page_number,
            )
            _collect_date_candidate(
                candidates,
                DocumentFactType.DOCUMENT_DATE,
                _DOCUMENT_DATE_PATTERN,
                normalized_line,
                span.page_number,
            )
            for fact_type, pattern in _TEXT_PATTERNS.items():
                match = pattern.match(normalized_line)
                if match is None:
                    continue
                value = _safe_text_value(match.group("value"))
                if value is None:
                    continue
                _append_candidate(
                    candidates,
                    InferredDocumentFact(
                        fact_type=fact_type,
                        value_text=value,
                        value_date=None,
                        confidence=Decimal("0.950"),
                        page_number=span.page_number,
                        evidence_code=f"label:{_code(match.group('label'))}",
                    ),
                )
        _collect_subtype_candidates(candidates, span)

    inferred: list[InferredDocumentFact] = []
    for fact_type in DocumentFactType:
        typed_candidates = candidates.get(fact_type, [])
        values = {(candidate.value_text, candidate.value_date) for candidate in typed_candidates}
        if len(values) == 1:
            inferred.append(typed_candidates[0])
    return tuple(inferred)


def persist_document_fact_inference(
    session: Session,
    *,
    document: Document,
    extraction: DocumentExtraction,
    extracted: ExtractedDocumentText,
) -> tuple[DocumentFact, ...]:
    inferred = {fact.fact_type.value: fact for fact in infer_document_facts(extracted)}
    existing = {
        fact.fact_type: fact
        for fact in session.scalars(
            select(DocumentFact).where(DocumentFact.document_id == document.id)
        )
    }
    for fact_type in DocumentFactType:
        stored = existing.get(fact_type.value)
        candidate = inferred.get(fact_type.value)
        if stored is not None and stored.source == "user":
            continue
        if candidate is None:
            if stored is not None:
                session.delete(stored)
            continue
        if stored is None:
            stored = DocumentFact(document=document, fact_type=fact_type.value)
            session.add(stored)
        stored.extraction = extraction
        stored.value_text = candidate.value_text
        stored.value_date = candidate.value_date
        stored.is_cleared = False
        stored.source = "automatic"
        stored.confidence = candidate.confidence
        stored.source_page_number = candidate.page_number
        stored.inference_name = INFERENCE_NAME
        stored.inference_version = INFERENCE_VERSION
        stored.evidence_code = candidate.evidence_code
    return tuple(existing.values())


def ensure_document_fact_inference(
    session: Session,
    *,
    document: Document,
    extraction: DocumentExtraction,
) -> bool:
    has_current_automatic_fact = session.scalar(
        select(DocumentFact.id).where(
            DocumentFact.document_id == document.id,
            DocumentFact.extraction_id == extraction.id,
            DocumentFact.inference_name == INFERENCE_NAME,
            DocumentFact.inference_version == INFERENCE_VERSION,
        )
    )
    if has_current_automatic_fact is not None:
        return False
    extracted = ExtractedDocumentText(
        spans=tuple(
            ExtractedTextValue(
                page_number=span.page_number,
                section_number=span.section_number,
                text=span.text,
            )
            for span in extraction.spans
        )
    )
    persist_document_fact_inference(
        session,
        document=document,
        extraction=extraction,
        extracted=extracted,
    )
    return True


def set_user_document_fact(
    session: Session,
    *,
    document_id: UUID,
    fact_type: DocumentFactType,
    value_text: str | None,
    value_date: date | None,
    is_cleared: bool,
) -> DocumentFact:
    document = session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.status == DocumentStatus.STORED,
        )
    )
    if document is None:
        raise DocumentFactNotFoundError("stored document not found")
    stored = session.scalar(
        select(DocumentFact).where(
            DocumentFact.document_id == document.id,
            DocumentFact.fact_type == fact_type.value,
        )
    )
    if stored is None:
        stored = DocumentFact(document=document, fact_type=fact_type.value)
        session.add(stored)
    stored.extraction = None
    stored.value_text = value_text
    stored.value_date = value_date
    stored.is_cleared = is_cleared
    stored.source = "user"
    stored.confidence = None
    stored.source_page_number = None
    stored.inference_name = "user"
    stored.inference_version = "1"
    stored.evidence_code = "user:cleared" if is_cleared else "user:provided"
    try:
        session.commit()
        session.refresh(stored)
    except SQLAlchemyError as exc:
        session.rollback()
        raise DocumentFactPersistenceError("document fact could not be persisted") from exc
    return stored


def list_document_facts(session: Session, *, document_id: UUID) -> list[DocumentFact]:
    document_exists = session.scalar(
        select(Document.id).where(
            Document.id == document_id,
            Document.status == DocumentStatus.STORED,
        )
    )
    if document_exists is None:
        raise DocumentFactNotFoundError("stored document not found")
    return list(
        session.scalars(
            select(DocumentFact)
            .where(DocumentFact.document_id == document_id)
            .order_by(DocumentFact.fact_type)
        )
    )


def query_document_expirations(
    session: Session,
    *,
    as_of: date,
    within_days: int,
) -> DocumentExpirationResponse:
    cutoff = date.fromordinal(as_of.toordinal() + within_days)
    rows = session.execute(
        select(Document, DocumentFact)
        .join(DocumentFact, DocumentFact.document_id == Document.id)
        .where(
            Document.status == DocumentStatus.STORED,
            DocumentFact.fact_type == DocumentFactType.EXPIRATION_DATE.value,
            DocumentFact.is_cleared.is_(False),
            DocumentFact.value_date.is_not(None),
            DocumentFact.value_date <= cutoff,
        )
        .order_by(DocumentFact.value_date, Document.id)
    ).all()
    items: list[DocumentExpirationItem] = []
    for document, fact in rows:
        assert fact.value_date is not None
        days = (fact.value_date - as_of).days
        status: DocumentExpirationStatus = (
            "expired" if days < 0 else "expires_today" if days == 0 else "upcoming"
        )
        items.append(
            DocumentExpirationItem(
                document_id=document.id,
                display_name=document.title or document.original_filename,
                expiration_date=fact.value_date,
                days_until_expiration=days,
                status=status,
                source=fact.source,
                confidence=fact.confidence,
                source_page_number=fact.source_page_number,
            )
        )
    return DocumentExpirationResponse(as_of=as_of, within_days=within_days, items=items)


def _collect_date_candidate(
    candidates: dict[DocumentFactType, list[InferredDocumentFact]],
    fact_type: DocumentFactType,
    pattern: re.Pattern[str],
    line: str,
    page_number: int,
) -> None:
    match = pattern.search(line)
    if match is None:
        return
    parsed = _parse_unambiguous_date(match.group("value"))
    if parsed is None:
        return
    _append_candidate(
        candidates,
        InferredDocumentFact(
            fact_type=fact_type,
            value_text=None,
            value_date=parsed,
            confidence=Decimal("0.950"),
            page_number=page_number,
            evidence_code=f"label:{_code(match.group('label'))}",
        ),
    )


def _collect_subtype_candidates(
    candidates: dict[DocumentFactType, list[InferredDocumentFact]],
    span: ExtractedTextValue,
) -> None:
    lowered = span.text.casefold()
    for subtype, signals in _SUBTYPE_SIGNALS.items():
        if any(signal in lowered for signal in signals):
            _append_candidate(
                candidates,
                InferredDocumentFact(
                    fact_type=DocumentFactType.DOCUMENT_SUBTYPE,
                    value_text=subtype,
                    value_date=None,
                    confidence=Decimal("0.850"),
                    page_number=span.page_number,
                    evidence_code=f"phrase:{subtype}",
                ),
            )


def _append_candidate(
    candidates: dict[DocumentFactType, list[InferredDocumentFact]],
    candidate: InferredDocumentFact,
) -> None:
    candidates.setdefault(candidate.fact_type, []).append(candidate)


def _parse_unambiguous_date(value: str) -> date | None:
    for date_format in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    return None


def _safe_text_value(value: str) -> str | None:
    normalized = " ".join(value.split()).strip(" .;,")
    if (
        not normalized
        or len(normalized) > 255
        or any(ord(character) < 32 for character in normalized)
    ):
        return None
    return normalized


def _code(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
