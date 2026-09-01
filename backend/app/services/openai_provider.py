from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import SecretStr


class AIProviderError(RuntimeError):
    """A privacy-safe provider failure that contains no response body or secret."""


class AIProviderTimeoutError(AIProviderError):
    pass


@dataclass(frozen=True)
class ProviderFunctionCall:
    call_id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class ProviderTurn:
    output_items: tuple[dict[str, Any], ...]
    function_calls: tuple[ProviderFunctionCall, ...]
    output_text: str


class AIProvider(Protocol):
    def create_turn(
        self,
        *,
        model: str,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_output_tokens: int,
        response_schema: dict[str, Any] | None = None,
    ) -> ProviderTurn: ...


class OpenAIResponsesProvider:
    def __init__(self, *, api_key: SecretStr, timeout_seconds: float) -> None:
        self._client = OpenAI(
            api_key=api_key.get_secret_value(),
            timeout=timeout_seconds,
            max_retries=1,
        )

    def create_turn(
        self,
        *,
        model: str,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_output_tokens: int,
        response_schema: dict[str, Any] | None = None,
    ) -> ProviderTurn:
        try:
            text = (
                {
                    "format": {
                        "type": "json_schema",
                        "name": "home_intelligence_response",
                        "strict": True,
                        "schema": response_schema,
                    }
                }
                if response_schema is not None
                else None
            )
            response = cast(Any, self._client.responses).create(
                model=model,
                instructions=instructions,
                input=input_items,
                tools=tools,
                tool_choice="auto",
                parallel_tool_calls=False,
                max_output_tokens=max_output_tokens,
                **({"text": text} if text is not None else {}),
            )
        except APITimeoutError as exc:
            raise AIProviderTimeoutError("AI provider request timed out") from exc
        except (APIConnectionError, APIStatusError) as exc:
            raise AIProviderError("AI provider request failed") from exc

        output_items: list[dict[str, Any]] = []
        function_calls: list[ProviderFunctionCall] = []
        for item in response.output:
            serialized = cast(dict[str, Any], item.model_dump(mode="json", exclude_none=True))
            output_items.append(serialized)
            if item.type == "function_call":
                function_calls.append(
                    ProviderFunctionCall(
                        call_id=item.call_id,
                        name=item.name,
                        arguments_json=item.arguments,
                    )
                )
        return ProviderTurn(
            output_items=tuple(output_items),
            function_calls=tuple(function_calls),
            output_text=response.output_text.strip(),
        )
