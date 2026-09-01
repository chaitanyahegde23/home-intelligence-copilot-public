# Controlled AI Orchestration

## Scope

HIC-017 adds an optional natural-language explanation layer around the four approved deterministic
analytics tools. It does not give a model database access, calculate totals in a prompt, add mutation
tools, or answer document questions.

## Configuration

AI is off unless `AI_ENABLED=true`. Enabling it requires `OPENAI_API_KEY`; startup fails closed when
the key is absent. The default model is `gpt-5.6-luna`, selected for cost-sensitive workloads.
`OPENAI_TIMEOUT_SECONDS` and `OPENAI_MAX_OUTPUT_TOKENS` bound each provider request. Secrets use
Pydantic `SecretStr`, remain in `.env`, and are not logged or returned.
`HOUSEHOLD_TIMEZONE` is a validated IANA timezone and defaults to `America/Los_Angeles`; it controls
the server calendar date used for deterministic relative-period resolution.

## Request flow

1. `POST /ai/questions` validates a bounded question under the authenticated household scope.
2. Deterministic policy refuses advice, mutations, credential/prompt extraction, database dumping,
   and recognizable instruction-injection attempts before a provider call.
3. Application code resolves the exact phrase `last month` to the previous calendar month's
   inclusive first and last dates in `HOUSEHOLD_TIMEZONE`; other incomplete periods remain ambiguous.
4. The OpenAI Responses API receives the question, any server-resolved range, and four strict JSON-schema function tools.
   Parallel calls are disabled.
5. A direct response is accepted only when prefixed as a clarification or refusal.
6. Exactly one function call may proceed. Its name must be allowlisted, and its JSON arguments are
   validated again by the existing Pydantic analytics contract.
7. Application code executes the deterministic tool with the request-scoped SQLAlchemy session.
   The provider never receives that session or arbitrary query access.
8. The second and final provider request receives minimized tool JSON. Import IDs, source filenames,
   internal timestamps, credentials, and database handles are omitted from provider payloads.
9. The final answer must identify itself as verified. Numeric claims not present in the deterministic
   arguments or result are rejected rather than returned.

The client receives a structured `verified`, `clarification`, or `refusal` response. Verified answers
include authoritative local evidence: tool name, validated arguments, and the complete deterministic
result.

## Data boundary

Enabling AI explicitly sends the user's question and a minimized analytics result to OpenAI. Large
transaction explanations may include the date, description, merchant, amount, category, and spending
magnitude needed for the explanation. Raw CSV/PDF bytes, document text, credentials, source filenames,
import identifiers, and unrestricted transaction dumps are outside HIC-017.

Provider exceptions are converted to generic timeout or failure responses without response bodies,
tokens, credentials, or request payloads. The deterministic analytics APIs remain usable when AI is
disabled or unavailable.

## Grounding limitations

Numeric-token validation prevents a returned answer from introducing a number not present in the tool
evidence. It does not prove that every qualitative interpretation is useful. HIC-018 adds versioned
synthetic evaluation for tool choice, grounding, clarification, refusal, injection, and explanation
quality before broader UI exposure.
