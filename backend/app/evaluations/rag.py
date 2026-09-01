from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.evaluations.ai import GraderResult
from app.schemas.document_answers import DocumentQuestionResponse


class SyntheticRAGDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    text: str


class RAGEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")]
    question: Annotated[str, Field(min_length=1, max_length=200)]
    expected_kind: Literal["verified", "no_results", "analytics_required"]
    expected_evidence_status: Literal["supported", "conflicting", "none"]
    expected_filenames: list[str]
    required_terms: list[str]
    forbidden_terms: list[str]
    critical: bool = True


class RAGEvaluationSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1.0"]
    dataset_id: str
    release_min_pass_rate: Annotated[Decimal, Field(ge=0, le=1)]
    documents: Annotated[list[SyntheticRAGDocument], Field(min_length=1)]
    cases: Annotated[list[RAGEvaluationCase], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_unique_values(self) -> RAGEvaluationSuite:
        if len({item.filename for item in self.documents}) != len(self.documents):
            raise ValueError("synthetic document filenames must be unique")
        if len({item.id for item in self.cases}) != len(self.cases):
            raise ValueError("RAG evaluation case IDs must be unique")
        return self


class RAGEvaluationCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    passed: bool
    critical: bool
    graders: list[GraderResult]
    provider_error: str | None = None


class RAGEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    dataset_version: str
    provider: str
    model: str
    prompt_version: str
    total_cases: int
    passed_cases: int
    pass_rate: Decimal
    release_passed: bool
    results: list[RAGEvaluationCaseResult]


type RAGEvaluationSubject = Callable[[str], DocumentQuestionResponse]


def load_rag_evaluation_suite(path: Path) -> RAGEvaluationSuite:
    return RAGEvaluationSuite.model_validate_json(path.read_text(encoding="utf-8"))


def run_rag_evaluation(
    suite: RAGEvaluationSuite,
    *,
    subject: RAGEvaluationSubject,
    provider: str,
    model: str,
    prompt_version: str,
) -> RAGEvaluationReport:
    results = [_run_case(case, subject) for case in suite.cases]
    passed = sum(result.passed for result in results)
    pass_rate = Decimal(passed) / Decimal(len(results))
    critical_passed = all(result.passed for result in results if result.critical)
    return RAGEvaluationReport(
        dataset_id=suite.dataset_id,
        dataset_version=suite.version,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        total_cases=len(results),
        passed_cases=passed,
        pass_rate=pass_rate,
        release_passed=pass_rate >= suite.release_min_pass_rate and critical_passed,
        results=results,
    )


def _run_case(
    case: RAGEvaluationCase,
    subject: RAGEvaluationSubject,
) -> RAGEvaluationCaseResult:
    try:
        response = subject(case.question)
    except Exception as exc:
        return RAGEvaluationCaseResult(
            case_id=case.id,
            passed=False,
            critical=case.critical,
            graders=[
                GraderResult(
                    name="provider_execution",
                    passed=False,
                    detail="subject raised a provider or document-answer error",
                )
            ],
            provider_error=type(exc).__name__,
        )
    filenames = {citation.original_filename for citation in response.citations}
    answer = response.answer.casefold()
    graders = [
        _grader("response_kind", response.kind == case.expected_kind),
        _grader(
            "evidence_status",
            response.evidence_status == case.expected_evidence_status,
        ),
        _grader("citation_sources", filenames == set(case.expected_filenames)),
        _grader(
            "answer_terms",
            all(term.casefold() in answer for term in case.required_terms)
            and all(term.casefold() not in answer for term in case.forbidden_terms),
        ),
    ]
    return RAGEvaluationCaseResult(
        case_id=case.id,
        passed=all(grader.passed for grader in graders),
        critical=case.critical,
        graders=graders,
    )


def _grader(name: str, passed: bool) -> GraderResult:
    return GraderResult(
        name=name,
        passed=passed,
        detail=f"{name} matched" if passed else f"{name} did not match",
    )
