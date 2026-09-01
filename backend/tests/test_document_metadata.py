from decimal import Decimal

import pytest

from app.services.document_metadata import infer_document_metadata
from app.services.document_text_extractor import (
    ExtractedDocumentText,
    ExtractedTextSpan,
)


def extracted(text: str, *, embedded_title: str | None = None) -> ExtractedDocumentText:
    return ExtractedDocumentText(
        spans=(ExtractedTextSpan(page_number=1, section_number=1, text=text),),
        embedded_title=embedded_title,
    )


@pytest.mark.parametrize(
    ("filename", "document_type"),
    [
        ("family-passport.pdf", "identity"),
        ("synthetic-tax-return.pdf", "tax"),
        ("monthly-bank-statement.pdf", "financial"),
        ("home-insurance-policy.pdf", "insurance"),
        ("appliance-warranty.pdf", "warranty"),
        ("mortgage-closing.pdf", "home"),
        ("synthetic-cover-letter.pdf", "employment"),
        ("synthetic-visa-application.pdf", "immigration"),
        ("synthetic-power-of-attorney.pdf", "legal"),
        ("synthetic-medical-record.pdf", "medical"),
        ("synthetic-academic-transcript.pdf", "education"),
        ("synthetic-reference-letter.pdf", "correspondence"),
        ("synthetic-purchase-receipt.pdf", "receipt"),
    ],
)
def test_infers_supported_document_types_from_safe_signals(
    filename: str, document_type: str
) -> None:
    result = infer_document_metadata(
        original_filename=filename,
        extracted=extracted(
            "This deliberately long synthetic paragraph has more than fourteen words so it is "
            "not selected as a document heading during metadata inference."
        ),
    )

    assert result.document_type == document_type
    assert result.document_type_confidence is not None
    assert Decimal("0.000") <= result.document_type_confidence <= Decimal("1.000")
    assert result.evidence_codes
    assert all("synthetic" not in code for code in result.evidence_codes)


def test_title_prefers_embedded_metadata_then_heading_then_filename() -> None:
    embedded = infer_document_metadata(
        original_filename="fallback.pdf",
        extracted=extracted("Visible Heading\nBody", embedded_title=" Embedded   Title "),
    )
    heading = infer_document_metadata(
        original_filename="fallback.pdf", extracted=extracted("Synthetic Warranty Summary\nBody")
    )
    filename = infer_document_metadata(
        original_filename="household_record.pdf",
        extracted=extracted(
            "This deliberately long synthetic paragraph cannot be treated as a heading because "
            "it contains far more words than the configured heading boundary."
        ),
    )

    assert (embedded.title, embedded.title_evidence_code) == (
        "Embedded Title",
        "pdf:embedded_title",
    )
    assert (heading.title, heading.title_evidence_code) == (
        "Synthetic Warranty Summary",
        "text:first_heading",
    )
    assert (filename.title, filename.title_evidence_code) == (
        "Household record",
        "filename:stem",
    )


def test_low_confidence_and_tied_classification_remain_unclassified() -> None:
    low_confidence = infer_document_metadata(
        original_filename="miscellaneous.pdf",
        extracted=extracted(
            "A long synthetic paragraph with no recognized household metadata signals anywhere."
        ),
    )
    tied = infer_document_metadata(
        original_filename="miscellaneous.pdf",
        extracted=extracted(
            "This intentionally lengthy neutral prefix keeps the line from becoming a heading "
            "while mentioning passport and form 1040 once each for an exact score tie."
        ),
    )

    assert low_confidence.document_type is None
    assert low_confidence.document_type_confidence is None
    assert tied.document_type is None
    assert tied.document_type_confidence is None
    assert tied.evidence_codes == ()


def test_descriptive_application_filename_beats_address_and_classifies_from_text() -> None:
    result = infer_document_metadata(
        original_filename="Application letter.pdf",
        extracted=extracted(
            "123 Example Street\nSample City, CA 90000\n"
            "This synthetic visa application and travel insurance note are provided only for "
            "deterministic testing."
        ),
    )

    assert (result.title, result.title_evidence_code) == (
        "Application letter",
        "filename:descriptive_stem",
    )
    assert result.document_type == "immigration"
    assert result.document_type_confidence is not None
