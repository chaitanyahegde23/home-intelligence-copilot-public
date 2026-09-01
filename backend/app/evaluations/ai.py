from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.ai import QuestionResponse
from app.services.ai_orchestrator import (
    AIUnsafeResponseError,
    validate_numeric_grounding,
)


class AIEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")]
    question: Annotated[str, Field(min_length=1, max_length=1000)]
    expected_kind: Literal["verified", "clarification", "refusal"]
    expected_tool_name: str | None = None
    expected_arguments: dict[str, object] | None = None
    required_terms: list[str] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)
    critical: bool = True

    @model_validator(mode="after")
    def validate_tool_expectation(self) -> Self:
        has_tool = self.expected_tool_name is not None
        has_arguments = self.expected_arguments is not None
        if self.expected_kind == "verified" and not (has_tool and has_arguments):
            raise ValueError("verified cases require an expected tool and arguments")
        if self.expected_kind != "verified" and (has_tool or has_arguments):
            raise ValueError("non-verified cases cannot expect tool evidence")
        return self


class AIEvaluationSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1.0"]
    dataset_id: Annotated[str, Field(min_length=1, max_length=100)]
    tool_contract_version: Literal["1.0"]
    release_min_pass_rate: Annotated[Decimal, Field(ge=0, le=1)]
    cases: Annotated[list[AIEvaluationCase], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_unique_case_ids(self) -> Self:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("evaluation case IDs must be unique")
        return self


class AIEvaluationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    prompt_version: str
    tool_contract_version: str
    dataset_id: str
    dataset_version: str


class GraderResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    detail: str


class AIEvaluationCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    passed: bool
    critical: bool
    graders: list[GraderResult]
    provider_error: str | None = None


class AIEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: AIEvaluationMetadata
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: Decimal
    release_min_pass_rate: Decimal
    release_passed: bool
    results: list[AIEvaluationCaseResult]


type EvaluationSubject = Callable[[str], QuestionResponse]


def load_ai_evaluation_suite(path: Path) -> AIEvaluationSuite:
    return AIEvaluationSuite.model_validate_json(path.read_text(encoding="utf-8"))


def run_ai_evaluation(
    suite: AIEvaluationSuite,
    *,
    subject: EvaluationSubject,
    provider: str,
    model: str,
    prompt_version: str,
) -> AIEvaluationReport:
    results = [_run_case(case, subject=subject) for case in suite.cases]
    passed_cases = sum(result.passed for result in results)
    pass_rate = Decimal(passed_cases) / Decimal(len(results))
    critical_passed = all(result.passed for result in results if result.critical)
    return AIEvaluationReport(
        metadata=AIEvaluationMetadata(
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            tool_contract_version=suite.tool_contract_version,
            dataset_id=suite.dataset_id,
            dataset_version=suite.version,
        ),
        total_cases=len(results),
        passed_cases=passed_cases,
        failed_cases=len(results) - passed_cases,
        pass_rate=pass_rate,
        release_min_pass_rate=suite.release_min_pass_rate,
        release_passed=(pass_rate >= suite.release_min_pass_rate and critical_passed),
        results=results,
    )


def _run_case(
    case: AIEvaluationCase,
    *,
    subject: EvaluationSubject,
) -> AIEvaluationCaseResult:
    try:
        response = subject(case.question)
    except Exception as exc:
        grader = GraderResult(
            name="provider_execution",
            passed=False,
            detail="subject raised a provider or orchestration error",
        )
        return AIEvaluationCaseResult(
            case_id=case.id,
            passed=False,
            critical=case.critical,
            graders=[grader],
            provider_error=type(exc).__name__,
        )

    graders = [
        _grade_kind(case, response),
        _grade_response_invariants(response),
        _grade_tool(case, response),
        _grade_arguments(case, response),
        _grade_numeric_grounding(response),
        _grade_terms(case, response),
    ]
    return AIEvaluationCaseResult(
        case_id=case.id,
        passed=all(grader.passed for grader in graders),
        critical=case.critical,
        graders=graders,
    )


def _grade_response_invariants(response: QuestionResponse) -> GraderResult:
    if response.kind == "verified":
        passed = response.verified and len(response.evidence) == 1
    else:
        passed = not response.verified and not response.evidence
    return GraderResult(
        name="response_invariants",
        passed=passed,
        detail="response invariants matched" if passed else "response invariants did not match",
    )


def _grade_kind(case: AIEvaluationCase, response: QuestionResponse) -> GraderResult:
    passed = response.kind == case.expected_kind
    return GraderResult(
        name="response_kind",
        passed=passed,
        detail="response kind matched" if passed else "response kind did not match",
    )


def _grade_tool(case: AIEvaluationCase, response: QuestionResponse) -> GraderResult:
    actual_tool = response.evidence[0].tool_name if len(response.evidence) == 1 else None
    passed = actual_tool == case.expected_tool_name
    return GraderResult(
        name="tool_selection",
        passed=passed,
        detail="tool selection matched" if passed else "tool selection did not match",
    )


def _grade_arguments(case: AIEvaluationCase, response: QuestionResponse) -> GraderResult:
    actual_arguments = response.evidence[0].arguments if len(response.evidence) == 1 else None
    passed = _canonical_json(actual_arguments) == _canonical_json(case.expected_arguments)
    return GraderResult(
        name="tool_arguments",
        passed=passed,
        detail="tool arguments matched" if passed else "tool arguments did not match",
    )


def _grade_numeric_grounding(response: QuestionResponse) -> GraderResult:
    if response.kind != "verified":
        return GraderResult(
            name="numeric_grounding",
            passed=not response.evidence,
            detail="non-verified response had no evidence",
        )
    if len(response.evidence) != 1:
        return GraderResult(
            name="numeric_grounding",
            passed=False,
            detail="verified response did not contain exactly one evidence object",
        )
    try:
        validate_numeric_grounding(response.answer, response.evidence[0])
    except AIUnsafeResponseError:
        return GraderResult(
            name="numeric_grounding",
            passed=False,
            detail="answer contained a numeric claim absent from evidence",
        )
    return GraderResult(
        name="numeric_grounding",
        passed=True,
        detail="numeric claims were present in evidence",
    )


def _grade_terms(case: AIEvaluationCase, response: QuestionResponse) -> GraderResult:
    normalized_answer = response.answer.casefold()
    required_present = all(term.casefold() in normalized_answer for term in case.required_terms)
    forbidden_absent = all(
        term.casefold() not in normalized_answer for term in case.forbidden_terms
    )
    passed = required_present and forbidden_absent
    return GraderResult(
        name="answer_terms",
        passed=passed,
        detail="answer terms matched" if passed else "required or forbidden answer terms failed",
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
