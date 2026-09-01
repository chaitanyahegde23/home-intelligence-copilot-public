from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

QuestionText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]


class QuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: QuestionText


class AnalyticsEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


class QuestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["verified", "clarification", "refusal"]
    answer: Annotated[str, Field(min_length=1, max_length=4000)]
    verified: bool
    model: str | None
    evidence: list[AnalyticsEvidence]
