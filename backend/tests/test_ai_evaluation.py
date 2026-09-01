from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluations.ai import (
    AIEvaluationCase,
    AIEvaluationSuite,
    load_ai_evaluation_suite,
    run_ai_evaluation,
)
from app.schemas.ai import AnalyticsEvidence, QuestionResponse

SAMPLE_SUITE = Path(__file__).resolve().parents[2] / "sample-data" / "synthetic-ai-evaluation.json"


def _case(**overrides: object) -> AIEvaluationCase:
    values: dict[str, object] = {
        "id": "summary_case",
        "question": "How much did I spend from 2026-01-01 through 2026-01-31?",
        "expected_kind": "verified",
        "expected_tool_name": "get_spending_summary",
        "expected_arguments": {"start_date": "2026-01-01", "end_date": "2026-01-31"},
    }
    values.update(overrides)
    return AIEvaluationCase.model_validate(values)


def _suite(*cases: AIEvaluationCase, threshold: str = "1.0") -> AIEvaluationSuite:
    return AIEvaluationSuite(
        version="1.0",
        dataset_id="synthetic-test-v1",
        tool_contract_version="1.0",
        release_min_pass_rate=Decimal(threshold),
        cases=list(cases),
    )


def _verified_response(
    *,
    answer: str = "Verified spending was $350.45.",
    tool_name: str = "get_spending_summary",
    arguments: dict[str, object] | None = None,
) -> QuestionResponse:
    return QuestionResponse(
        kind="verified",
        answer=answer,
        verified=True,
        model="test-model",
        evidence=[
            AnalyticsEvidence(
                tool_name=tool_name,
                arguments=arguments or {"start_date": "2026-01-01", "end_date": "2026-01-31"},
                result={"total_spending": "350.45", "transaction_count": 2},
            )
        ],
    )


def test_loads_committed_synthetic_suite() -> None:
    suite = load_ai_evaluation_suite(SAMPLE_SUITE)

    assert suite.version == "1.0"
    assert suite.release_min_pass_rate == Decimal("1.0")
    assert len(suite.cases) == 7
    assert all("synthetic" not in case.question.casefold() for case in suite.cases)


@pytest.mark.parametrize(
    "payload",
    [
        {"expected_tool_name": None},
        {"expected_arguments": None},
        {
            "expected_kind": "refusal",
            "expected_tool_name": "get_spending_summary",
            "expected_arguments": {},
        },
    ],
)
def test_rejects_inconsistent_case_contract(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _case(**payload)


def test_rejects_duplicate_case_ids() -> None:
    with pytest.raises(ValidationError, match="unique"):
        _suite(_case(), _case())


def test_good_response_passes_with_version_metadata() -> None:
    report = run_ai_evaluation(
        _suite(_case()),
        subject=lambda _question: _verified_response(),
        provider="test-provider",
        model="test-model",
        prompt_version="1",
    )

    assert report.release_passed
    assert report.passed_cases == 1
    assert report.metadata.model == "test-model"
    assert report.metadata.dataset_version == "1.0"


@pytest.mark.parametrize(
    ("response", "failed_grader"),
    [
        (
            QuestionResponse(
                kind="refusal",
                answer="I cannot answer that.",
                verified=False,
                model=None,
                evidence=[],
            ),
            "response_kind",
        ),
        (_verified_response(tool_name="get_spending_by_category"), "tool_selection"),
        (
            _verified_response(arguments={"start_date": "2025-01-01", "end_date": "2025-01-31"}),
            "tool_arguments",
        ),
        (_verified_response(answer="Verified spending was $999.99."), "numeric_grounding"),
    ],
)
def test_known_bad_answers_fail(
    response: QuestionResponse,
    failed_grader: str,
) -> None:
    report = run_ai_evaluation(
        _suite(_case()),
        subject=lambda _question: response,
        provider="test-provider",
        model="test-model",
        prompt_version="1",
    )

    assert not report.release_passed
    grader = next(item for item in report.results[0].graders if item.name == failed_grader)
    assert not grader.passed


def test_required_and_forbidden_terms_are_graded() -> None:
    case = _case(required_terms=["exact"], forbidden_terms=["estimate"])
    report = run_ai_evaluation(
        _suite(case),
        subject=lambda _question: _verified_response(answer="This estimate was $350.45."),
        provider="test-provider",
        model="test-model",
        prompt_version="1",
    )

    assert not next(
        grader for grader in report.results[0].graders if grader.name == "answer_terms"
    ).passed


def test_provider_failure_reports_only_exception_type() -> None:
    def fail(_question: str) -> QuestionResponse:
        raise RuntimeError("secret provider detail")

    report = run_ai_evaluation(
        _suite(_case()),
        subject=fail,
        provider="test-provider",
        model="test-model",
        prompt_version="1",
    )

    assert report.results[0].provider_error == "RuntimeError"
    assert "secret provider detail" not in report.model_dump_json()


def test_critical_failure_blocks_release_even_when_threshold_is_met() -> None:
    good = _case(id="good_case", critical=False)
    critical = _case(id="critical_case", critical=True)
    responses = iter([_verified_response(), _verified_response(answer="Total was $999.99.")])
    report = run_ai_evaluation(
        _suite(good, critical, threshold="0.5"),
        subject=lambda _question: next(responses),
        provider="test-provider",
        model="test-model",
        prompt_version="1",
    )

    assert report.pass_rate == Decimal("0.5")
    assert not report.release_passed
