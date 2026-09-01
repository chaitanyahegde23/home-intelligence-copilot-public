from pathlib import Path

from app.evaluations.rag import load_rag_evaluation_suite, run_rag_evaluation
from app.schemas.document_answers import DocumentCitation, DocumentQuestionResponse

SUITE_PATH = Path(__file__).resolve().parents[2] / "sample-data" / "synthetic-rag-evaluation.json"


def _citation(filename: str, citation_id: str = "C1") -> DocumentCitation:
    from uuid import uuid4

    return DocumentCitation(
        citation_id=citation_id,
        document_id=uuid4(),
        chunk_id=uuid4(),
        original_filename=filename,
        page_number=1,
        section_number=1,
        start_offset=0,
        end_offset=4,
        document_sha256="a" * 64,
        chunk_sha256="b" * 64,
        excerpt="test",
    )


def test_committed_rag_suite_is_versioned_and_synthetic() -> None:
    suite = load_rag_evaluation_suite(SUITE_PATH)

    assert suite.version == "1.0"
    assert len(suite.cases) == 5
    assert all(document.filename.startswith("synthetic-") for document in suite.documents)


def test_rag_evaluation_grades_kind_sources_and_terms() -> None:
    suite = load_rag_evaluation_suite(SUITE_PATH)

    def subject(question: str) -> DocumentQuestionResponse:
        if "Aster" in question:
            return DocumentQuestionResponse(
                kind="verified",
                answer="The warranty expires on 2028-06-30 [C1].",
                verified=True,
                evidence_status="supported",
                model="test-model",
                retrieval_terms=["aster"],
                citations=[_citation("synthetic-aster-warranty.pdf")],
            )
        if "Helios" in question:
            return DocumentQuestionResponse(
                kind="verified",
                answer="The documents conflict: $500 [C1] and $750 [C2].",
                verified=True,
                evidence_status="conflicting",
                model="test-model",
                retrieval_terms=["helios"],
                citations=[
                    _citation("synthetic-helios-policy-a.pdf", "C1"),
                    _citation("synthetic-helios-policy-b.pdf", "C2"),
                ],
            )
        if "Orchid" in question:
            return DocumentQuestionResponse(
                kind="verified",
                answer="The interval is 6 months [C1].",
                verified=True,
                evidence_status="supported",
                model="test-model",
                retrieval_terms=["orchid"],
                citations=[_citation("synthetic-orchid-maintenance.pdf")],
            )
        if "Zenith" in question:
            return DocumentQuestionResponse(
                kind="no_results",
                answer="No indexed household document contains enough evidence.",
                verified=False,
                evidence_status="none",
                model=None,
                retrieval_terms=["zenith"],
                citations=[],
            )
        return DocumentQuestionResponse(
            kind="analytics_required",
            answer="Use deterministic spending analytics.",
            verified=False,
            evidence_status="none",
            model=None,
            retrieval_terms=[],
            citations=[],
        )

    report = run_rag_evaluation(
        suite,
        subject=subject,
        provider="test-provider",
        model="test-model",
        prompt_version="1",
    )

    assert report.release_passed
    assert report.passed_cases == 5


def test_rag_evaluation_known_bad_source_and_provider_failure_fail_safely() -> None:
    suite = load_rag_evaluation_suite(SUITE_PATH).model_copy(
        update={"cases": load_rag_evaluation_suite(SUITE_PATH).cases[:1]}
    )
    bad = DocumentQuestionResponse(
        kind="verified",
        answer="The answer is unsupported.",
        verified=True,
        evidence_status="supported",
        model="test-model",
        retrieval_terms=[],
        citations=[_citation("wrong-source.pdf")],
    )
    report = run_rag_evaluation(
        suite,
        subject=lambda _question: bad,
        provider="test-provider",
        model="test-model",
        prompt_version="1",
    )
    assert not report.release_passed

    def fail(_question: str) -> DocumentQuestionResponse:
        raise RuntimeError("private provider body")

    failed = run_rag_evaluation(
        suite,
        subject=fail,
        provider="test-provider",
        model="test-model",
        prompt_version="1",
    )
    assert failed.results[0].provider_error == "RuntimeError"
    assert "private provider body" not in failed.model_dump_json()
