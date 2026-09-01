from datetime import date

from app.models.document_fact import DocumentFactType
from app.services.document_facts import infer_document_facts
from app.services.document_text_extractor import ExtractedDocumentText, ExtractedTextSpan


def extracted(*pages: str) -> ExtractedDocumentText:
    return ExtractedDocumentText(
        spans=tuple(
            ExtractedTextSpan(page_number=index, section_number=1, text=text)
            for index, text in enumerate(pages, start=1)
        )
    )


def test_infers_supported_facts_with_page_provenance() -> None:
    result = infer_document_facts(
        extracted(
            "Insurance Policy\nIssuer: Example Mutual\nPolicy Number: POL-SYNTH-42\n"
            "Issue Date: June 1, 2026",
            "Expiration Date: 30 June 2028",
        )
    )
    by_type = {fact.fact_type: fact for fact in result}

    assert by_type[DocumentFactType.ISSUER].value_text == "Example Mutual"
    assert by_type[DocumentFactType.REFERENCE_NUMBER].value_text == "POL-SYNTH-42"
    assert by_type[DocumentFactType.DOCUMENT_DATE].value_date == date(2026, 6, 1)
    assert by_type[DocumentFactType.EXPIRATION_DATE].value_date == date(2028, 6, 30)
    assert by_type[DocumentFactType.EXPIRATION_DATE].page_number == 2
    assert by_type[DocumentFactType.DOCUMENT_SUBTYPE].value_text == "insurance_policy"


def test_conflicting_values_and_ambiguous_numeric_dates_are_ignored() -> None:
    result = infer_document_facts(
        extracted(
            "Expiration Date: 2028-06-30\nExpiration Date: 2029-06-30\nIssue Date: 06/01/2026"
        )
    )

    assert all(
        fact.fact_type not in {DocumentFactType.EXPIRATION_DATE, DocumentFactType.DOCUMENT_DATE}
        for fact in result
    )


def test_invalid_calendar_date_is_ignored() -> None:
    result = infer_document_facts(extracted("Warranty expires: 2026-02-30"))

    assert all(fact.fact_type is not DocumentFactType.EXPIRATION_DATE for fact in result)
