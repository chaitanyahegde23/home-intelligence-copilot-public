from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentMetadataSource
from app.models.document_extraction import DocumentExtraction
from app.models.document_metadata import DocumentMetadataInference
from app.services.document_text_extractor import ExtractedDocumentText
from app.services.document_text_extractor import ExtractedTextSpan as ExtractedTextValue

CLASSIFIER_NAME = "household_document_rules"
CLASSIFIER_VERSION = "2"
AUTOMATIC_SOURCE: DocumentMetadataSource = "automatic"
MINIMUM_TYPE_SCORE = 4
MINIMUM_WIN_MARGIN = 2

_GENERIC_TITLES = {
    "document",
    "Microsoft Word",
    "scan",
    "scanned document",
    "untitled",
}

_TYPE_SIGNALS: dict[str, tuple[tuple[str, int], ...]] = {
    "identity": (
        ("passport", 4),
        ("driver license", 4),
        ("social security", 4),
        ("birth certificate", 4),
        ("date of birth", 2),
    ),
    "tax": (
        ("form 1040", 4),
        ("form w-2", 4),
        ("form w2", 4),
        ("form 1099", 4),
        ("tax return", 3),
        ("internal revenue service", 3),
    ),
    "financial": (
        ("bank statement", 4),
        ("credit card statement", 4),
        ("account statement", 3),
        ("brokerage statement", 4),
        ("statement", 2),
    ),
    "insurance": (
        ("insurance policy", 4),
        ("insurance", 3),
        ("policy number", 2),
        ("premium", 2),
        ("coverage", 1),
    ),
    "warranty": (
        ("limited warranty", 4),
        ("warranty", 3),
        ("serial number", 2),
        ("warranty expires", 3),
    ),
    "home": (
        ("mortgage", 4),
        ("property deed", 4),
        ("home inspection", 4),
        ("lease agreement", 4),
        ("rental agreement", 4),
        ("property tax", 3),
    ),
    "employment": (
        ("cover letter", 4),
        ("employment letter", 4),
        ("offer letter", 4),
        ("employment agreement", 4),
        ("curriculum vitae", 4),
        ("resume", 3),
    ),
    "immigration": (
        ("visa application", 5),
        ("visa letter", 4),
        ("immigration", 4),
        ("residence permit", 4),
        ("consulate", 3),
        ("embassy", 3),
    ),
    "legal": (
        ("power of attorney", 4),
        ("court order", 4),
        ("legal notice", 4),
        ("affidavit", 4),
    ),
    "medical": (
        ("medical record", 4),
        ("health record", 4),
        ("vaccination record", 4),
        ("immunization record", 4),
        ("prescription", 3),
    ),
    "education": (
        ("academic transcript", 4),
        ("school transcript", 4),
        ("degree certificate", 4),
        ("diploma", 4),
        ("enrollment letter", 4),
    ),
    "correspondence": (
        ("official correspondence", 4),
        ("formal notice", 4),
        ("reference letter", 4),
        ("recommendation letter", 4),
    ),
    "receipt": (
        ("purchase receipt", 4),
        ("payment receipt", 4),
        ("tax invoice", 4),
        ("invoice number", 3),
        ("receipt number", 3),
    ),
}

_DESCRIPTIVE_FILENAME_PHRASES = ("application letter",) + tuple(
    phrase
    for signals in _TYPE_SIGNALS.values()
    for phrase, _weight in signals
    if phrase
    not in {
        "statement",
        "insurance",
        "coverage",
        "premium",
        "resume",
        "prescription",
        "diploma",
        "immigration",
        "consulate",
        "embassy",
        "affidavit",
    }
)


@dataclass(frozen=True)
class InferredDocumentMetadata:
    title: str
    title_evidence_code: str
    document_type: str | None
    document_type_confidence: Decimal | None
    evidence_codes: tuple[str, ...]


def infer_document_metadata(
    *, original_filename: str, extracted: ExtractedDocumentText
) -> InferredDocumentMetadata:
    title, title_evidence = _infer_title(original_filename, extracted)
    document_type, confidence, evidence = _infer_type(
        original_filename=original_filename,
        title=title,
        text="\n".join(span.text for span in extracted.spans),
    )
    return InferredDocumentMetadata(
        title=title,
        title_evidence_code=title_evidence,
        document_type=document_type,
        document_type_confidence=confidence,
        evidence_codes=evidence,
    )


def persist_document_metadata_inference(
    session: Session,
    *,
    document: Document,
    extraction: DocumentExtraction,
    extracted: ExtractedDocumentText,
) -> DocumentMetadataInference:
    inferred = infer_document_metadata(
        original_filename=document.original_filename,
        extracted=extracted,
    )
    stored = session.scalar(
        select(DocumentMetadataInference).where(
            DocumentMetadataInference.extraction_id == extraction.id,
            DocumentMetadataInference.classifier_name == CLASSIFIER_NAME,
            DocumentMetadataInference.classifier_version == CLASSIFIER_VERSION,
        )
    )
    if stored is None:
        stored = DocumentMetadataInference(
            document=document,
            extraction=extraction,
            classifier_name=CLASSIFIER_NAME,
            classifier_version=CLASSIFIER_VERSION,
            suggested_title=inferred.title,
            title_evidence_code=inferred.title_evidence_code,
            suggested_document_type=inferred.document_type,
            document_type_confidence=inferred.document_type_confidence,
            evidence_codes=list(inferred.evidence_codes),
        )
        session.add(stored)
    else:
        stored.suggested_title = inferred.title
        stored.title_evidence_code = inferred.title_evidence_code
        stored.suggested_document_type = inferred.document_type
        stored.document_type_confidence = inferred.document_type_confidence
        stored.evidence_codes = list(inferred.evidence_codes)

    if document.title_source in (None, AUTOMATIC_SOURCE):
        document.title = inferred.title
        document.title_source = AUTOMATIC_SOURCE
    if document.document_type_source in (None, AUTOMATIC_SOURCE):
        document.document_type = inferred.document_type
        document.document_type_source = (
            AUTOMATIC_SOURCE if inferred.document_type is not None else None
        )
    return stored


def ensure_document_metadata_inference(
    session: Session,
    *,
    document: Document,
    extraction: DocumentExtraction,
) -> bool:
    existing_id = session.scalar(
        select(DocumentMetadataInference.id).where(
            DocumentMetadataInference.extraction_id == extraction.id,
            DocumentMetadataInference.classifier_name == CLASSIFIER_NAME,
            DocumentMetadataInference.classifier_version == CLASSIFIER_VERSION,
        )
    )
    if existing_id is not None:
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
    persist_document_metadata_inference(
        session,
        document=document,
        extraction=extraction,
        extracted=extracted,
    )
    return True


def _infer_title(original_filename: str, extracted: ExtractedDocumentText) -> tuple[str, str]:
    embedded = _safe_title(extracted.embedded_title)
    if embedded is not None:
        return embedded, "pdf:embedded_title"

    stem = original_filename.rsplit(".", 1)[0]
    filename_title = _safe_title(re.sub(r"[_-]+", " ", stem))
    if filename_title is not None and any(
        phrase in filename_title.casefold() for phrase in _DESCRIPTIVE_FILENAME_PHRASES
    ):
        return filename_title[:1].upper() + filename_title[1:], "filename:descriptive_stem"

    for span in extracted.spans:
        for line in span.text.splitlines():
            heading = _safe_heading(line)
            if heading is not None:
                return heading, "text:first_heading"

    if filename_title is None:
        return "Uploaded document", "filename:fallback"
    return filename_title[:1].upper() + filename_title[1:], "filename:stem"


def _safe_heading(value: str) -> str | None:
    candidate = _safe_title(value)
    if candidate is None:
        return None
    words = candidate.split()
    if not 2 <= len(words) <= 14 or len(candidate) > 120:
        return None
    if candidate.endswith((".", ":", ";")) or "://" in candidate:
        return None
    return candidate


def _safe_title(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    printable = "".join(character for character in value if character.isprintable())
    candidate = " ".join(printable.split()).strip()
    if (
        not candidate
        or len(candidate) > 255
        or candidate.casefold() in {title.casefold() for title in _GENERIC_TITLES}
    ):
        return None
    return candidate


def _infer_type(
    *, original_filename: str, title: str, text: str
) -> tuple[str | None, Decimal | None, tuple[str, ...]]:
    sources = {
        "filename": (original_filename.casefold(), 2),
        "title": (title.casefold(), 2),
        "text": (text.casefold(), 1),
    }
    scores: dict[str, int] = {}
    evidence_by_type: dict[str, list[str]] = {}
    for document_type, signals in _TYPE_SIGNALS.items():
        score = 0
        evidence: list[str] = []
        for phrase, weight in signals:
            code = phrase.replace(" ", "_").replace("-", "")
            for source_name, (source_value, multiplier) in sources.items():
                if phrase in source_value:
                    score += weight * multiplier
                    evidence.append(f"{source_name}:{code}")
        scores[document_type] = score
        evidence_by_type[document_type] = evidence

    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    winner, winning_score = ordered[0]
    runner_up_score = ordered[1][1]
    margin = winning_score - runner_up_score
    if winning_score < MINIMUM_TYPE_SCORE or margin < MINIMUM_WIN_MARGIN:
        return None, None, ()

    confidence = min(
        Decimal("0.980"),
        Decimal("0.600")
        + Decimal(min(winning_score, 8)) * Decimal("0.040")
        + Decimal(min(margin, 5)) * Decimal("0.020"),
    ).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return winner, confidence, tuple(sorted(set(evidence_by_type[winner])))
