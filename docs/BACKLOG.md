# Home Intelligence Copilot Backlog

## Backlog rules

- Tasks are ordered by priority and intended to fit one focused Codex session.
- **Ready** means prerequisites are satisfied and the task may be proposed for approval.
- **Planned** means ordered but not yet ready or selected.
- **Blocked** names an unmet dependency; it is not approval to start prerequisite work.
- **Completed** requires acceptance criteria, tests, validation, and roadmap/backlog updates.
- No task may silently expand into an adjacent task.

The backend foundation, models/migration, and CSV transaction import are completed baseline capabilities and are not repeated as open tasks.

## P0 — Make imported data inspectable

### HIC-001 — Add paginated transaction query API

- **Purpose:** Let users and future analytics inspect normalized transactions without direct database access.
- **Implementation scope:** Add `GET /transactions`; query service/repository; limit/offset pagination; deterministic newest-first ordering with UUID tie-breaker; optional filters for inclusive start/end transaction date, account name, category, merchant name, and import batch UUID; response and pagination schemas.
- **Acceptance criteria:** Results are stable and bounded; combined filters work; amounts remain Decimal-safe in serialization; invalid date ranges/limits return useful validation errors; no analytics totals or mutation behavior is added.
- **Tests required:** Empty results; default ordering; page boundaries; each filter; combined filters; inclusive dates; invalid ranges; invalid batch UUID; maximum limit; response schema.
- **Dependencies:** Completed transaction model and import flow.
- **Status:** Completed — implemented and validated with focused API tests, the full test suite, Ruff, formatting, mypy, and Alembic drift checks.

### HIC-002 — Add import-batch history API

- **Purpose:** Show which files were imported and whether each import succeeded, partially succeeded, or failed.
- **Implementation scope:** Add `GET /imports`; bounded pagination; newest-first ordering; optional status filter; import count/timestamp response schema; query service.
- **Acceptance criteria:** Every persisted batch can be listed with filename, status, counts, and timestamps; ordering and pagination are stable; no file contents or secrets are exposed.
- **Tests required:** Empty/list cases; status filter; ordering; pagination; count fields; invalid status/limit.
- **Dependencies:** HIC-001 query conventions should be reused where appropriate.
- **Status:** Completed — implemented and validated with focused API tests, the full test suite, Ruff, formatting, mypy, live PostgreSQL validation, and Alembic drift checks.

### HIC-003 — Add import-batch detail API

- **Purpose:** Let a user inspect one import and navigate to its transactions.
- **Implementation scope:** Add `GET /imports/{batch_id}`; batch detail schema; transaction count/provenance link or documented filter URL; clear not-found behavior.
- **Acceptance criteria:** Existing batches return complete metadata and counts; unknown UUIDs return 404; the response does not claim row errors are persisted when they are not.
- **Tests required:** Existing/completed/failed batches; unknown UUID; malformed UUID; relationship/count behavior.
- **Dependencies:** HIC-001 and HIC-002.
- **Status:** Completed — implemented and validated with focused API tests, the full test suite, Ruff, formatting, mypy, live PostgreSQL validation, and Alembic drift checks.

### HIC-031 — Delete an import batch and its transactions

- **Purpose:** Let a household remove an incorrectly uploaded statement and every normalized transaction created by that import.
- **Implementation scope:** Add household-scoped `DELETE /imports/{batch_id}` service/API behavior; atomically cascade transactions and dependent duplicate/category-assignment records; add explicit import-history UI confirmation and refresh behavior.
- **Acceptance criteria:** Deleting an owned batch removes the batch and all dependent records; unknown or cross-household IDs return 404; unrelated imports, transactions, categories, and rules remain; the UI states the transaction count and requires confirmation.
- **Tests required:** Successful cascade; empty/failed batch; unknown ID; household isolation; rollback; frontend API behavior; confirmation/cancellation/success/error states.
- **Dependencies:** HIC-003, HIC-010, HIC-012, HIC-015, and HIC-025.
- **Status:** Completed — household-scoped atomic deletion, database-owned cascades, explicit UI confirmation, history refresh, rollback/isolation coverage, and backend/frontend validation are implemented.

## P0 — Support recurring institution CSV exports

### HIC-026 — Add import-source provenance and adapter contracts

- **Purpose:** Establish a safe, auditable boundary for converting explicitly supported institution exports into the canonical transaction model.
- **Implementation scope:** Define typed adapter/detection/result contracts; record adapter name and version on `ImportBatch` through a reviewed migration; define an explicit user-supplied account label; document fixture sanitization and format-versioning rules. Do not parse a bank format yet.
- **Acceptance criteria:** Every future import can identify the adapter and version that normalized it; adapter outputs use canonical strict date/`Decimal` types; ambiguous or unsupported formats have typed failures; real source files and member/account identifiers never enter fixtures or logs.
- **Tests required:** Model/schema defaults and constraints; migration upgrade/check; contract validation; float rejection; invalid/ambiguous result states; provenance serialization; fixture privacy scan.
- **Dependencies:** Existing atomic canonical importer, import-batch model, and synthetic-data policy.
- **Status:** Completed — typed adapter, normalization, and detection contracts; persisted provenance; canonical defaults; explicit account labels; migration; API serialization; and privacy/contract tests are implemented and validated.

### HIC-027 — Refactor canonical import behind an adapter registry

- **Purpose:** Preserve the current CSV behavior while giving all supported formats one detection, normalization, validation, and persistence pipeline.
- **Implementation scope:** Implement an exact-header-signature registry; wrap the existing canonical format as `canonical_v1`; route uploads through detection and the selected adapter; retain file-size/type controls, row errors, atomic persistence, and source filename; expose adapter provenance in import responses/history/detail.
- **Acceptance criteria:** Existing canonical uploads remain backward compatible; exactly one adapter must match; unknown and ambiguous headers fail without persistence; normalized rows pass the same strict validator; routes remain thin.
- **Tests required:** Canonical regression; supported/unsupported/ambiguous detection; duplicate/unexpected headers; adapter exception rollback; provenance response fields; size/type controls; full import regression.
- **Dependencies:** HIC-026.
- **Status:** Completed — exact unique-header-set detection, the `canonical_csv` version `1` adapter, shared normalization/persistence orchestration, pre-persistence unsupported/ambiguous failures, and regression/rollback tests are implemented and validated.

### HIC-028 — Add Citi credit-card CSV adapter

- **Purpose:** Allow the household's recurring Citi statement exports to upload directly through Swagger/UI without manual conversion.
- **Implementation scope:** Add an exact Citi header signature; parse `MM/dd/yyyy`; map debit to negative `Decimal` and credit to positive `Decimal`; require exactly one amount side; normalize descriptions; ignore member name as an identity source; use an explicit generic/user account label; add only sanitized synthetic fixtures derived from the reviewed shape.
- **Acceptance criteria:** A structurally matching Citi export imports directly with correct signs, dates, counts, and provenance; malformed dates/amount sides fail at row level; member names are neither persisted nor logged; canonical imports remain unchanged.
- **Tests required:** Purchases; credits/refunds; payment; zero/blank/both amount sides; invalid date/precision; whitespace/quoted commas; mixed valid/invalid rows; atomic rollback; synthetic fixture privacy scan; live local smoke test using a user-held file outside the repository.
- **Dependencies:** HIC-027 and a private local Citi sample for format verification.
- **Status:** Completed — the strict Citi adapter, sanitized fixture, sign/date/amount-side validation, provenance, rollback coverage, privacy scan, canonical regression, and private local smoke test are implemented and validated.

### HIC-029 — Add Chase CSV adapter

- **Purpose:** Support recurring Chase account or card exports through the same auditable pipeline.
- **Implementation scope:** Privately inspect the specific Chase product export; define an exact signature and versioned sign/date mapping; implement one adapter; add sanitized synthetic fixtures; preserve account label and adapter provenance.
- **Acceptance criteria:** The reviewed Chase format imports directly with deterministic signs/dates and no real identifiers in source control; a different or changed Chase layout is rejected rather than guessed.
- **Tests required:** Every observed transaction type/sign case; dates; optional fields; quoted text; malformed/mixed rows; detection conflicts; rollback; privacy scan; private local smoke test.
- **Dependencies:** HIC-027 and at least one representative private Chase CSV. Separate materially different checking/card layouts require separate adapter versions or tasks.
- **Status:** Completed — exact Chase credit-card detection, signed Decimal/date/field mapping, synthetic fixture, provenance, changed-layout rejection, rollback/privacy coverage, and a 27-row private in-memory API smoke import passed.

### HIC-030 — Add Bank of America CSV adapter

- **Purpose:** Support recurring Bank of America account or card exports through the same auditable pipeline.
- **Implementation scope:** Privately inspect the specific Bank of America product export; define an exact signature and versioned sign/date mapping; implement one adapter; add sanitized synthetic fixtures; preserve account label and adapter provenance.
- **Acceptance criteria:** The reviewed Bank of America format imports directly with deterministic signs/dates and no real identifiers in source control; an unrecognized layout is rejected rather than guessed.
- **Tests required:** Every observed transaction type/sign case; dates; optional fields; quoted text; malformed/mixed rows; detection conflicts; rollback; privacy scan; private local smoke test.
- **Dependencies:** HIC-027 and at least one representative private Bank of America CSV. Separate materially different checking/card layouts require separate adapter versions or tasks.
- **Status:** Completed — exact Bank of America account detection at the reviewed row-7 header, deterministic beginning-balance exclusion, grouped signed Decimal mapping, synthetic fixture, provenance, changed-layout rejection, rollback/privacy coverage, and a 16-row private in-memory API smoke import passed.

### HIC-032 — Support Citi activity-report CSV layout with categories

- **Purpose:** Import the reviewed Citi activity-report export that includes bank-provided categories.
- **Implementation scope:** Extend the Citi adapter to version `2` with exact row-3 `Date,Description,Debit,Credit,Category` detection after two metadata rows, strict month-name dates, layout-specific debit/credit signs, category persistence, and a sanitized synthetic fixture.
- **Acceptance criteria:** Both reviewed Citi layouts detect deterministically; category, date, and sign normalization are exact; unexpected headers, locations, dates, and signs fail explicitly; real statement content stays outside the repository.
- **Tests required:** Row-3 detection; legacy regression; date/sign/category normalization; malformed rows; API persistence/provenance; rollback; privacy scan; private in-memory smoke validation.
- **Dependencies:** HIC-026 through HIC-028 and a privately held representative export.
- **Status:** Completed — both Citi layouts are supported by the strict version `2` adapter with synthetic fixture, category persistence, negative-credit activity semantics, regression/failure tests, and privacy-safe private validation.

## P1 — Build trusted deterministic analytics

### HIC-004 — Define transaction and analytics semantics

- **Purpose:** Prevent incorrect totals caused by ambiguous signs, date ranges, income, refunds, or transfers.
- **Implementation scope:** Add an ADR/spec defining spending sign convention, inclusive/exclusive dates, treatment of positive amounts, missing categories, currency assumption, and transfer limitations; derive typed analytics input/output contracts.
- **Acceptance criteria:** Every planned analytics endpoint has unambiguous calculation rules and examples using synthetic transactions; unresolved questions are documented rather than assumed in code.
- **Tests required:** Documentation consistency checks where available; no product-code tests unless typed contracts are introduced.
- **Dependencies:** HIC-001 query API findings.
- **Status:** Completed — semantics version 1.0, synthetic examples, typed filters/summary contracts, and contract tests are implemented and validated.

### HIC-005 — Add deterministic spending-summary API

- **Purpose:** Answer “How much did I spend in this date range?” exactly.
- **Implementation scope:** Implement a Decimal-based summary service and `GET /analytics/spending/summary` with explicit date range and optional account/category filters; return total, transaction count, and applied filters.
- **Acceptance criteria:** Results follow HIC-004 semantics, use no float, and return zero for valid empty ranges; no AI dependency exists.
- **Tests required:** Exact totals; empty range; credits/refunds per policy; date boundaries; filters; Decimal precision; invalid ranges.
- **Dependencies:** HIC-001 and HIC-004.
- **Status:** Completed — deterministic SQL aggregation, typed API response, focused policy/precision tests, full validation, and live PostgreSQL verification passed.

### HIC-006 — Add category spending breakdown

- **Purpose:** Show where household spending went.
- **Implementation scope:** Add category-grouped analytics service/API for a date range; define handling of `NULL` category; stable result ordering and percentages computed without float drift.
- **Acceptance criteria:** Category totals reconcile exactly to the corresponding summary under the same filters; uncategorized spending is explicit.
- **Tests required:** Multiple/empty/null categories; reconciliation; ordering; precision; filters.
- **Dependencies:** HIC-005.
- **Status:** Completed — deterministic service and typed API implemented with explicit missing-category representation, exact totals/count reconciliation, stable ordering, Decimal percentages, focused tests, and full validation.

### HIC-007 — Add period comparison analytics

- **Purpose:** Explain how spending changed between two explicit periods.
- **Implementation scope:** Add service/API returning both totals, absolute Decimal change, category deltas, counts, and applied ranges.
- **Acceptance criteria:** Both periods use identical semantics; category deltas reconcile to total change; division-by-zero behavior is explicit if percentages are included.
- **Tests required:** Higher/lower/equal periods; empty baseline; category reconciliation; boundary dates; precision.
- **Dependencies:** HIC-005 and HIC-006.
- **Status:** Completed — typed service/API returns exact period totals, signed Decimal changes, explicit zero-baseline percentages, and reconciling category/count deltas with focused and full validation.

### HIC-008 — Add large-transaction query

- **Purpose:** Help users identify transactions that materially affected a period.
- **Implementation scope:** Add threshold-based deterministic service/API with date/account/category filters, stable ordering, and bounded results.
- **Acceptance criteria:** Threshold inclusion is documented; results retain transaction and import provenance; no subjective AI classification is used.
- **Tests required:** Exact threshold; negative/positive semantics; ordering/ties; filters; bounded limit; empty results.
- **Dependencies:** HIC-001 and HIC-004.
- **Status:** Completed — deterministic threshold query/API implements inclusive Decimal magnitude, outflow-only semantics, exact filters, stable ordering, bounded results, and transaction/import provenance with focused and full validation.

## P1 — Protect analytics quality

### HIC-009 — Define duplicate model and migration

- **Purpose:** Represent duplicate candidates without silently deleting source records.
- **Implementation scope:** Write duplicate-semantics ADR; add fingerprint/status/reason fields or a dedicated candidate model; create migration and schemas; preserve import provenance.
- **Acceptance criteria:** Schema supports unresolved, confirmed, and dismissed candidates; migration upgrade/downgrade is reviewed; no automatic deletion occurs.
- **Tests required:** Model constraints/defaults; relationships; migration apply/check; status validation.
- **Dependencies:** HIC-004 and query APIs.
- **Status:** Completed — the non-destructive `DuplicateCandidate` model, canonical pair constraints, review states, Pydantic schemas, semantics specification, and reversible PostgreSQL migration are implemented and validated.

### HIC-010 — Detect duplicates during import

- **Purpose:** Flag overlapping imports before they inflate trusted analytics.
- **Implementation scope:** Implement deterministic canonical fingerprint/candidate matching; integrate with atomic import; expose duplicate outcome in structured responses or history.
- **Acceptance criteria:** Re-imported exact rows are flagged consistently; likely legitimate same-value transactions are not silently rejected; persistence remains atomic.
- **Tests required:** Same file twice; overlapping files; whitespace/date variants; false-positive cases; rollback; analytics inclusion policy.
- **Dependencies:** HIC-009.
- **Status:** Completed — versioned full-field SHA-256 matching, cross-import representative selection, PostgreSQL import serialization, atomic unresolved-candidate persistence, upload/detail outcomes, candidate query/review APIs, and regression tests are implemented and validated.

### HIC-011 — Add category and categorization-rule schema

- **Purpose:** Store transparent classification rules and manual overrides.
- **Implementation scope:** Define category/rule/assignment provenance models; add migration; define precedence and manual-override representation; add Pydantic schemas.
- **Acceptance criteria:** Schema distinguishes manual from rule-derived categories and supports deterministic precedence; migration has no model drift.
- **Tests required:** Constraints; relationships; precedence metadata; migration apply/check; schema validation.
- **Dependencies:** HIC-006 and duplicate semantics.
- **Status:** Completed - category, deterministic rule, and one-current-assignment provenance models; source/rule constraints; stable priority/UUID precedence metadata; Pydantic schemas; a reversible PostgreSQL migration; and focused model/schema tests are implemented and validated.

### HIC-012 — Implement deterministic categorization service

- **Purpose:** Categorize transactions consistently while keeping user decisions authoritative.
- **Implementation scope:** Rule matcher; normalization; precedence; batch recategorization; manual override protection; focused APIs for rule management/application.
- **Acceptance criteria:** Identical inputs/rules produce identical output; manual overrides survive reruns; conflicts are visible and deterministic.
- **Tests required:** Merchant/description matching; precedence; conflicts; override protection; rollback; uncategorized cases.
- **Dependencies:** HIC-011.
- **Status:** Completed - normalized exact/prefix/contains matching, priority/UUID precedence, visible conflicts, scoped atomic application, manual override protection, category/rule synchronization, focused management APIs, analytics integration, rollback tests, and full validation are implemented.

## P2 — Add the primary web interface

### HIC-013 — Choose frontend stack and scaffold web shell

- **Purpose:** Establish a maintainable browser interface without duplicating backend business logic.
- **Implementation scope:** Record frontend ADR; scaffold one minimal application; configure API base URL and local development; add navigation, error boundary, and automated test command.
- **Acceptance criteria:** The shell runs locally, calls `/health`, and has documented setup; no analytics or import feature is bundled into the scaffold task.
- **Tests required:** App render; health-client success/failure; lint/type/build checks; basic accessibility smoke test.
- **Dependencies:** Stable API conventions from HIC-001 through HIC-003.
- **Status:** Completed — React, TypeScript, and Vite are recorded in ADR-016; the responsive semantic shell, configurable API client/proxy, health states, error boundary, accessibility smoke test, and test/lint/type/build workflows are implemented and browser-verified.

### HIC-014 — Add CSV upload and import-result UI

- **Purpose:** Replace Swagger as the normal upload workflow.
- **Implementation scope:** File picker, upload progress/state, structured batch summary, row-error display, size/type guidance, and retry/reset behavior.
- **Acceptance criteria:** A user can upload the synthetic CSV and understand complete, partial, failed, unsupported, and oversized outcomes.
- **Tests required:** Valid/mixed/failed responses; client validation; API failure; accessibility of file and error controls; end-to-end synthetic upload.
- **Dependencies:** HIC-013 and existing import API.
- **Status:** Completed — the tested browser workflow provides file/type/size guidance, multipart upload, indeterminate processing state, complete/partial/failed summaries, adapter and batch provenance, row errors, and retry/reset behavior without client-side transaction parsing.

### HIC-015 — Add transaction, import-history, and analytics views

- **Purpose:** Provide the core import-to-insight browser workflow.
- **Implementation scope:** Paginated tables, filters, batch detail navigation, summary/category/period views, loading/empty/error states.
- **Acceptance criteria:** UI values come from APIs; filtering and pagination are shareable or recoverable; no financial calculation exists only in frontend code.
- **Tests required:** Component states; filter serialization; pagination; API error handling; end-to-end browse and analytics paths.
- **Dependencies:** HIC-002 through HIC-008 and HIC-013.
- **Status:** Completed — typed API clients and responsive views provide recoverable filtered transaction pages, import history/detail navigation, and backend-derived spending/category/period analytics with loading, empty, and failure states plus automated and live-browser validation.

## P3 — Add controlled AI only after analytics

### HIC-016 — Define approved analytics tool contracts

- **Purpose:** Create a safe typed boundary between future natural-language orchestration and deterministic analytics.
- **Implementation scope:** Tool names, descriptions, argument/result schemas, allowlist, read-only guarantees, ambiguity rules, and direct tests; no OpenAI SDK call.
- **Acceptance criteria:** Each supported financial question maps to a deterministic tool contract; tools return evidence/filters and cannot mutate state.
- **Tests required:** Argument validation; exact result pass-through; unsupported tools; ambiguous ranges; mutation prohibition.
- **Dependencies:** HIC-005 through HIC-008 completed and tested.
- **Status:** Completed — four immutable provider-independent contracts reuse the deterministic analytics services and typed results, require explicit validated ranges, reject unsupported dispatch, expose evidence/filters, and pass exact result/read-only tests without an OpenAI dependency.

### HIC-017 — Add OpenAI tool-calling orchestrator

- **Purpose:** Let users ask supported questions in natural language while preserving verified calculations.
- **Implementation scope:** Provider configuration, orchestrator, allowlisted tool execution, clarification, grounded response schema, refusal policy, and privacy-aware error handling.
- **Acceptance criteria:** Numeric claims match tool results; AI can be disabled; unsupported advice/actions are refused; the model has no direct database access.
- **Tests required:** Tool selection; argument validation; grounding; ambiguity; injection attempts; provider timeout/error; no-secret logging.
- **Dependencies:** HIC-016 and explicit user approval for OpenAI integration.
- **Status:** Completed — optional fail-closed configuration, a bounded OpenAI Responses API adapter, strict allowlisted tool selection, household-scoped execution, deterministic refusal/injection policy, clarification responses, minimized provider payloads, numeric grounding checks, privacy-safe provider errors, and focused/live synthetic validation are implemented.

### HIC-018 — Add synthetic AI evaluation harness

- **Purpose:** Detect regressions in tool use, factual grounding, refusals, and explanations.
- **Implementation scope:** Versioned synthetic cases, deterministic graders, result report, model/tool metadata, and release thresholds.
- **Acceptance criteria:** Known bad answers fail; numeric/tool mismatches are detected; evaluations use no real household data.
- **Tests required:** Runner; graders; malformed cases; deterministic mismatch checks; provider-failure reporting.
- **Dependencies:** HIC-017.
- **Status:** Completed — the versioned seven-case synthetic suite, deterministic response/tool/argument/numeric/term graders, privacy-safe provider-failure reporting, version metadata, 100% critical release gate, and live synthetic runner are implemented and tested.

## P4 — Add household documents and cited retrieval

### HIC-019 — Decide private document storage and metadata architecture

- **Purpose:** Establish safe lifecycle and provenance before accepting sensitive files.
- **Implementation scope:** Threat/storage ADR; supported initial type; retention/deletion/backup behavior; document metadata model and migration plan.
- **Acceptance criteria:** Storage location, encryption assumptions, ownership, checksum, provenance, and deletion behavior are explicit; no document upload implementation yet.
- **Tests required:** Documentation review checklist; model/migration tests only if schema is included in the approved scope.
- **Dependencies:** Product privacy principles and deployment assumptions.
- **Status:** Completed — the accepted architecture selects bounded unencrypted PDF, PostgreSQL metadata, opaque-key private filesystem blobs, SHA-256 provenance, local single-household ownership until HIC-025, compensating lifecycle transitions, idempotent deletion, bounded staging/backup retention, and explicit threat controls; no ingestion code or schema was added.

### HIC-020 — Add bounded document upload and metadata persistence

- **Purpose:** Safely register and store one selected synthetic household-document format.
- **Implementation scope:** File validation, private storage adapter, checksum, metadata/status persistence, atomic failure behavior, and deletion path.
- **Acceptance criteria:** Supported synthetic files upload and delete safely; unsupported/oversized/path-traversal inputs fail; original content is not logged.
- **Tests required:** Type/size; checksum; duplicate file; storage failure rollback; path traversal; deletion; migration.
- **Dependencies:** HIC-019 and later authorization design where deployment requires it.
- **Status:** Completed — bounded unencrypted PDFs are streamed into opaque private storage with strict metadata/structure/active-content/size/page checks, SHA-256 duplicate detection, PostgreSQL lifecycle metadata, compensating rollback, deny-first idempotent deletion, privacy-safe audit records, a reversible migration, synthetic fixtures, and failure-path tests. Remote and multi-household use remains prohibited before HIC-025.

### HIC-021 — Add document text extraction with provenance

- **Purpose:** Produce reviewable text for search without losing source location.
- **Implementation scope:** One extractor adapter, processing states, page/section provenance, retry/failure behavior, and synthetic fixtures.
- **Acceptance criteria:** Extracted text maps back to exact source locations; failures are visible; originals remain unchanged.
- **Tests required:** Extraction fixture; page provenance; malformed file; retry; idempotency; failure status.
- **Dependencies:** HIC-020.
- **Status:** Completed — `pypdf_native` version `1` verifies immutable source bytes, extracts bounded native text into versioned whole-page spans with page/section/character/hash provenance, persists explicit processing/completed/failed states, supports idempotent completion plus failed/stale retry, cascades deletion, exposes safe machine failure codes, and passes fixture, provenance, malformed, integrity, retry, idempotency, limit, and migration tests. OCR, search, and background processing remain excluded.

### HIC-022 — Add lexical retrieval baseline

- **Purpose:** Establish measurable retrieval before introducing embeddings.
- **Implementation scope:** Chunk model, deterministic chunking, PostgreSQL lexical search, household filters, ranked results, and retrieval evaluation cases.
- **Acceptance criteria:** Synthetic questions retrieve relevant source chunks with provenance; no cross-household result is possible once ownership exists.
- **Tests required:** Chunk boundaries; indexing; ranking fixtures; no-result case; authorization filter; migration.
- **Dependencies:** HIC-021 and an ownership model before multi-user use.
- **Status:** Completed — deterministic `deterministic_chars:1` chunks preserve document/extraction/span/page/section/offset/checksum provenance; PostgreSQL `simple` full-text search uses a GIN expression index, OR term matching, stable ranked results, bounded responses, synthetic evaluation cases, explicit local-only scope, cascade deletion, and a reversible drift-free migration. Embeddings, answer generation, citations, and remote/multi-household access remain excluded.

### HIC-023 — Add cited document answers and evaluate RAG

- **Purpose:** Answer document questions with verifiable evidence.
- **Implementation scope:** Citation schema/rendering, context assembly, injection defenses, answer policy, retrieval/citation evaluations; embeddings only if lexical evaluation justifies them.
- **Acceptance criteria:** Material claims cite correct locations; missing/conflicting evidence is explicit; transaction totals continue using analytics tools.
- **Tests required:** Citation correctness; grounding; injection documents; no-result/conflict; retrieval regression; authorization.
- **Dependencies:** HIC-018 and HIC-022.
- **Status:** Completed — bounded household-scoped retrieval feeds strict structured claims; application code filters recognized source instructions, renders exact-provenance citations, rejects unknown/uncited/numerically unsupported output, reports conflicts/no-results, redirects transaction totals, and runs a versioned synthetic RAG gate. Lexical evaluation did not justify embeddings.

## P4 — Authentication and privacy hardening

### HIC-024 — Write threat model and authentication ADR

- **Purpose:** Select identity and household-isolation controls based on an explicit deployment model.
- **Implementation scope:** Assets, actors, trust boundaries, threats, local-versus-remote assumptions, identity options, session design, and migration strategy for existing data.
- **Acceptance criteria:** Chosen approach and rejected alternatives are documented; authorization boundaries cover APIs, tools, documents, and retrieval.
- **Tests required:** Security review checklist; no implementation tests unless a small proof is explicitly approved.
- **Dependencies:** Stable interfaces and intended deployment decision.
- **Status:** Completed — the accepted design documents assets, actors, trust boundaries, local-versus-secure deployment modes, a threat/control matrix, fail-closed authorization boundaries for APIs/tools/documents/retrieval, application-managed Argon2id owner credentials, opaque server-side sessions, CSRF/origin controls, non-null household ownership, deterministic bootstrap migration, rejected alternatives, residual risks, and HIC-025 security gates. No runtime authentication was added.

### HIC-025 — Implement authentication and household ownership foundation

- **Purpose:** Enforce identity and prevent cross-household access.
- **Implementation scope:** Approved identity/session mechanism, household ownership fields, migration/backfill, repository authorization filters, and basic audit events.
- **Acceptance criteria:** Unauthenticated and cross-household requests fail; existing local data is migrated deliberately; secrets and sensitive payloads are absent from logs.
- **Tests required:** Login/session lifecycle; authorization matrix; IDOR attempts; migration/backfill; tool/query isolation; audit redaction.
- **Dependencies:** HIC-024 and explicit approval of security design.
- **Status:** Completed — application-managed Argon2id owner credentials, opaque digest-only sessions, CSRF/Origin/Host checks, rate limiting, revocation/recovery, redacted audits, deterministic bootstrap backfill, non-null household ownership, global query scoping, relationship/write guards, protected APIs, and login/logout UI are implemented and validated. Local mode remains an explicit trusted-development option; secure production mode requires same-origin TLS and deployment hardening.

## P5 — Deliver the Copilot and document workspace

### HIC-033 — Add paginated document library API

- **Purpose:** Let the web client discover and monitor household documents without knowing IDs.
- **Implementation scope:** Household-scoped `GET /documents`; bounded pagination; stable ordering; safe metadata; newest extraction status; current chunk count/readiness; typed schemas and service separation.
- **Acceptance criteria:** Only the active household's documents are returned; pagination is deterministic; lifecycle is visible without extracted text, storage keys, or raw content.
- **Tests required:** Pagination/order; lifecycle summaries; empty state; household isolation; response redaction; API validation.
- **Dependencies:** HIC-020, HIC-021, HIC-022, and HIC-025.
- **Status:** Completed — the metadata-only household-scoped library returns deterministic bounded pages, latest extraction state, current chunk readiness, and no storage keys or extracted text; tracked as Linear HOM-37.

### HIC-034 — Build document management web workspace

- **Purpose:** Let users manage synthetic household PDFs without Swagger.
- **Implementation scope:** Document navigation, upload, paginated library, lifecycle actions, lexical search, deletion confirmation, responsive loading/empty/error states.
- **Acceptance criteria:** Upload → extraction → chunking → search → deletion works in the web app with recoverable failures and intended-only sensitive-text display.
- **Tests required:** API client; upload/lifecycle/search/delete components; keyboard/accessibility; responsive and error states.
- **Dependencies:** HIC-033.
- **Status:** Completed — the responsive web workspace supports bounded PDF selection, paginated lifecycle metadata, explicit extraction and indexing, provenance-rich lexical search, recoverable errors, and inline deletion confirmation; tracked as Linear HOM-38.

### HIC-035 — Build controlled Copilot and citation UI

- **Purpose:** Expose analytics and cited-document questions through a trustworthy web experience.
- **Implementation scope:** Separate analytics/document modes; question submission; all response states; deterministic evidence and exact citation rendering; privacy/cost guidance.
- **Acceptance criteria:** Supported questions expose inspectable evidence; modes never silently use RAG for totals; disabled/error states are understandable and recoverable.
- **Tests required:** API clients; every response kind; evidence/citation rendering; keyboard/accessibility; privacy-safe errors.
- **Dependencies:** HIC-017, HIC-018, HIC-023, and HIC-034.
- **Status:** Completed — the web client keeps analytics and document modes explicit, renders all safe response states, exposes deterministic evidence or exact citation provenance, communicates cost/privacy boundaries, and retains no question history; tracked as Linear HOM-39.

### HIC-036 — Validate milestone 11 end-to-end UX and accessibility

- **Purpose:** Prove the integrated document and Copilot workflows are usable and trustworthy.
- **Implementation scope:** Integrated tests, synthetic browser smoke flow, responsive/keyboard/accessibility QA, failure/retry/console review, and manual-test documentation.
- **Acceptance criteria:** Primary and important failure flows pass automated/browser QA with no serious accessibility violations or sensitive test artifacts.
- **Tests required:** Frontend integration/accessibility; backend regression; production build/audit; browser primary/failure/responsive/console checks.
- **Dependencies:** HIC-034 and HIC-035.
- **Status:** Completed — integrated synthetic automation and isolated browser QA cover the primary document/Copilot flows, important recovery states, responsive and keyboard behavior, accessibility, console safety, full regressions, and manual testing guidance; tracked as Linear HOM-40.

## P0 — Refine the document-first household workspace

### HIC-037 — Compact the primary workspace

- **Purpose:** Reduce oversized typography, dead space, and scrolling while preserving accessible workflows.
- **Implementation scope:** Smaller global headings and section spacing; subtle API health; a coherent responsive import/history layout; removal of the oversized empty import result; compact import batch detail.
- **Acceptance criteria:** Primary desktop workflows expose materially more information above the fold; health remains visible but secondary; import and history form one responsive workspace; result, error, and detail states remain usable; backend behavior is unchanged.
- **Tests required:** Frontend unit/integration tests; lint; formatting; type checking; production build; focused browser accessibility and responsive QA.
- **Dependencies:** HIC-015 and HIC-036.
- **Status:** Completed — the document-first shell, restrained type scale and spacing, subtle local-API status, responsive import/history pair, conditional import feedback, compact batch detail, and desktop/mobile browser QA are delivered; tracked as Linear HOM-41.

### HIC-038 — Automate document intake and duplicate recovery

- **Purpose:** Turn document upload into one dependable action rather than three manual lifecycle steps.
- **Implementation scope:** Automatically extract and index after upload; clear the native file input after success; refresh lifecycle state; parse duplicate-content conflicts and focus the existing document; retain explicit retry after processing failures.
- **Acceptance criteria:** A valid PDF becomes searchable after one upload action; the selected filename clears; duplicate content identifies the existing record; partial failures are explicit and retryable.
- **Tests required:** Upload pipeline; file reset; duplicate conflict action; extraction/index failure; lifecycle refresh; accessibility; backend regressions.
- **Dependencies:** HIC-037 and the existing HIC-020 through HIC-022 lifecycle services.
- **Status:** Completed — one upload now stores, extracts, and indexes a valid PDF; the native picker clears, lifecycle state refreshes, duplicate-content conflicts link to the existing record, and stored partial failures retain explicit retry actions; covered by API, component, integration, accessibility, build, audit, and live browser validation; tracked as Linear HOM-42.

### HIC-039 — Promote the document library into a household archive

- **Purpose:** Make household records easy to organize, find, inspect, and retrieve later.
- **Implementation scope:** Extend the existing `Document` metadata entity with justified user-managed fields; consolidate lexical search into the library; add filters and authorized original-document access; connect citations to documents. Storage paths and public URLs remain private.
- **Acceptance criteria:** Users can browse/filter an inventory, edit useful metadata, search from the same workspace, securely open or download an authorized original, and navigate citations to their document.
- **Tests required:** Migration/model constraints; metadata CRUD/filtering; authorization and IDOR; safe content headers; citation links; search/library integration; deletion; frontend accessibility.
- **Dependencies:** HIC-038 and HIC-025 authorization.
- **Status:** Completed — the existing household-owned `Document` now carries normalized optional title/type/notes, archive queries filter by type or display name, text search is integrated into the library, originals stream only through a household-scoped no-store/nosniff endpoint, and Copilot citations link to that endpoint; migration, metadata/filter, IDOR, header, API/component/integration, accessibility, full regression, build, audit, and live browser checks passed; tracked as Linear HOM-43.

### HIC-040 — Improve Copilot answer readability and date semantics

- **Purpose:** Make grounded answers readable and useful while keeping implementation details secondary.
- **Implementation scope:** Safely render controlled emphasis; make deterministic evidence and technical provenance collapsible; resolve relative periods such as “last month” in deterministic timezone-aware code; integrate authorized document links from HIC-039.
- **Acceptance criteria:** Literal Markdown markers never leak into answers; evidence remains inspectable but subtle; “last month” resolves to an explicit inclusive range without unnecessary clarification; financial values still originate only from deterministic tools; cited sources are navigable.
- **Tests required:** Sanitization/XSS; response rendering; relative-date boundaries, timezone, and leap years; grounding; citation links; accessibility.
- **Dependencies:** HIC-038 and HIC-039 for the complete citation-link experience.
- **Status:** Completed — analytics and document answers render a safe React-only `**emphasis**` subset without arbitrary HTML or leaked markers, evidence/provenance remain inspectable disclosures, secure citation links are preserved, and `last month` resolves server-side from a validated IANA household timezone before deterministic tool execution; leap year, year rollover, timezone midnight, injection rendering, grounding, accessibility, full regression, build, and audit tests passed; tracked as Linear HOM-44.

### HIC-041 — Consolidate transactions and deterministic summaries

- **Purpose:** Make transactions the useful financial workspace and de-emphasize the redundant standalone analytics section.
- **Implementation scope:** Inline manual category assignment through the existing API; backend-derived gross, spend, and income summaries for active filters; clearer totals; fold selected analytics into transactions and simplify navigation. AI may explain deterministic results but must not calculate them.
- **Acceptance criteria:** Users can update a category and see its provenance; active-filter totals come from backend deterministic services; standalone analytics becomes secondary or is removed without losing supported capabilities.
- **Tests required:** Category update/error; filter-summary agreement; Decimal formatting; pagination versus full-filter totals; responsive/accessibility; backend regression.
- **Dependencies:** HIC-037, HIC-012, and HIC-015.
- **Status:** Completed — the transaction query returns Decimal-safe spending, income, net, and gross totals for the complete active filter set independently of pagination; rows include category-assignment provenance; users can create categories and assign them inline; the redundant standalone analytics view is removed from primary navigation while deterministic analytics APIs and Copilot tools remain available; tracked as Linear HOM-45.

### HIC-042 — Simplify navigation and transaction-import UX

- **Purpose:** Keep transaction import compact and make import history readable without a permanent full-page form.
- **Implementation scope:** Compact import trigger; accessible upload and drag-and-drop modal; full-width import history with responsive side detail; removal of the nonessential Foundation section; preserved validation, retry, deletion, and keyboard behavior.
- **Acceptance criteria:** Import occupies only a small toolbar until opened; modal focus and Escape behavior are correct; picker/drop paths share validation; history/detail form a clear responsive master-detail layout; Foundation content is absent; backend behavior is unchanged.
- **Tests required:** Modal lifecycle/focus; drag/drop; upload/error/result; history/detail semantics; accessibility; responsive browser QA; frontend regression.
- **Dependencies:** HIC-037.
- **Status:** Completed — the compact trigger, accessible picker/drop modal, explicit Escape/focus restoration, full-width responsive history/detail layout, Foundation removal, automated regression, and desktop/mobile browser QA are delivered; tracked as Linear HOM-46.

## P1 — Automated document understanding

### HIC-043 — Automatically understand document metadata

- **Purpose:** Organize newly uploaded private PDFs without requiring manual title and type entry.
- **Implementation scope:** Extract safe embedded titles; infer a title and existing archive type from filename and native text through a versioned deterministic classifier; persist confidence and non-sensitive provenance separately; auto-fill only fields without a user override; expose provenance in the document library.
- **Acceptance criteria:** Recognizable synthetic documents are titled/classified after extraction; weak/tied signals remain unclassified; user edits and explicit clears always win; inference is household-scoped and removed with the document; no content is sent externally.
- **Tests required:** Classifier matrix/ambiguity; embedded/heading/filename precedence; atomic persistence; override/retry/deletion/isolation; API/UI; migration; full validation and browser QA.
- **Dependencies:** HIC-021, HIC-025, HIC-038, and HIC-039.
- **Status:** Completed — deterministic title/type inference, confidence/provenance persistence, manual-override protection, migration, API/UI support, automated validation, and desktop/mobile browser QA are delivered; tracked as Linear HOM-47.

### HIC-044 — Accept safe PDF hyperlinks without weakening ingestion security

- **Purpose:** Store ordinary exported letters and records containing clickable web or email links without accepting executable PDF behavior.
- **Implementation scope:** Permit only well-formed `/Link` `/URI` actions using `http`, `https`, or `mailto`; retain deny-first rejection for JavaScript, automatic actions, forms, embedded files, file attachments, launch actions, unsafe schemes, control characters, and malformed URLs; return specific safe errors.
- **Acceptance criteria:** Synthetic ordinary links upload successfully; unsafe/executable links fail before persistence; existing PDF limits, rollback, duplicate detection, and private storage remain unchanged; private local samples validate without entering Git.
- **Tests required:** Safe-scheme matrix; unsafe scheme, malformed host, and launch-action rejection; persistence/rollback regression; full backend validation and local-only compatibility check.
- **Dependencies:** HIC-020 and HIC-043.
- **Status:** Completed — safe-link security tests, full backend regression, migration drift check, and private local compatibility checks pass; delivered and tracked as Linear HOM-48.

### HIC-045 — Expand deterministic document taxonomy and title quality

- **Purpose:** Organize a broader household archive, including employment and immigration records, without requiring every type to be assigned manually.
- **Implementation scope:** Version the classifier; add employment, immigration, legal, medical, education, correspondence, and receipt/invoice signals; prefer strongly descriptive filenames over address-like opening content; expose the new choices in library filters and metadata editing.
- **Acceptance criteria:** Synthetic classifier coverage exists for every new type; weak/tied signals remain unclassified; application and cover-letter patterns receive useful titles/types; user overrides remain authoritative; private local samples validate without becoming fixtures.
- **Tests required:** New type matrix, ambiguity regression, descriptive-filename/title precedence, API/UI option coverage, full backend/frontend validation, and local-only compatibility check.
- **Dependencies:** HIC-043 and HIC-044.
- **Status:** Completed — classifier version 2, broader types, descriptive-title precedence, control-character-safe extraction, UI coverage, full backend/frontend validation, and private local compatibility checks pass; delivered and tracked as Linear HOM-49.

## P1 — Local document OCR

### HIC-046 — Extract image-only PDF text with local OCR

- **Purpose:** Make scanned printed household PDFs searchable without sending private documents to a paid external OCR service.
- **Implementation scope:** Keep native `pypdf` extraction as the fast path; use local OCRmyPDF/Tesseract only when a PDF contains pages without native text; preserve the immutable original, page/checksum provenance, existing text limits, retry states, metadata inference, retrieval, and deletion behavior; add bounded language/timeout configuration and Docker dependencies.
- **Acceptance criteria:** Native PDFs do not invoke OCR; a synthetic image-only PDF produces searchable page text and metadata inference; originals remain byte-identical; OCR timeouts/failures expose only safe failure state; configuration is documented; no content leaves the local runtime.
- **Tests required:** Native bypass; synthetic image-only OCR; mixed/provenance persistence; text limit; invalid language; engine failure; retry/deletion regressions; full backend/frontend, migration, Docker build, and live local OCR validation.
- **Dependencies:** HIC-020, HIC-021, HIC-022, HIC-025, and HIC-043.
- **Status:** Completed — native-first local OCR, bounded configuration, immutable-source handling, safe failures, Docker runtime dependencies, a committed image-only synthetic fixture, documentation, 445 backend tests, 66 frontend tests, static/build/audit gates, migration drift checks, and a live OCR-to-search smoke test all pass.

## P1 — Structured document facts and lifecycle

### HIC-047 — Extract and manage structured document facts

- **Purpose:** Turn private household PDFs into an actionable archive by identifying important dates and reference details without external processing.
- **Implementation scope:** Deterministic expiration date, document date, issuer, reference number, and subtype extraction from native/OCR spans; household-scoped persistence and provenance; authoritative user correction/clear APIs and UI; deterministic expiration-state query.
- **Acceptance criteria:** Recognizable labeled synthetic facts include page/confidence provenance; ambiguous, invalid, or conflicting dates are ignored; user changes survive extraction versions; expiration state uses a caller-supplied date; deletion and household isolation cover facts.
- **Tests required:** Rule/date ambiguity; persistence and constraints; extraction integration; override/clear/version protection; deletion/isolation; API/UI; migration; regressions and static/build checks.
- **Dependencies:** HIC-021, HIC-025, HIC-039, HIC-043, and HIC-046.
- **Status:** Completed — deterministic rule, ambiguity, persistence, override/clear, extractor-version, expiration-boundary, deletion/isolation, API/UI, migration, backend/frontend regression, static analysis, production build, dependency audit, Docker rebuild, schema-drift, and live health checks pass.

### HIC-048 — Add expiration reminders and an attention dashboard

- **Purpose:** Turn structured expiration dates into an actionable in-app household checklist.
- **Implementation scope:** One opt-in reminder configuration per document; in-app channel; configurable lead time; household-timezone date resolution; due dashboard; acknowledgement tied to the current expiration date; deterministic snooze; source-document links.
- **Acceptance criteria:** Disabled documents never alert; one document never produces duplicate alerts; due boundaries are deterministic; acknowledgement suppresses only the acknowledged date; renewal reactivates; snooze and deletion work; household data remains isolated.
- **Tests required:** Configuration constraints; due boundaries/order; acknowledgement/renewal; snooze; deduplication; deletion/isolation; API/UI; migration; regressions and static/build checks.
- **Dependencies:** HIC-047 and HIC-025.
- **Status:** Completed — opt-in configuration, lead-window boundaries, household-timezone state, deduplication, acknowledgement/renewal, snooze, deletion/isolation, API/UI, migration, 450 backend tests, 70 frontend tests, static analysis, production build, dependency audit, Docker rebuild, schema-drift, and live health checks pass.

## P0 — Document-first application shell

### HIC-049 — Build the compact document-first workspace

- **Purpose:** Make the household archive the primary product surface and keep optional financial workflows out of the way.
- **Implementation scope:** Runtime capabilities endpoint; fail-closed financial route flag; compact sidebar; dense archive rows; original-document preview; selected-record details; scoped document Copilot; responsive presentation.
- **Acceptance criteria:** Docker defaults to the document-only experience; disabled financial APIs return 404; enabling the flag restores existing financial UI/APIs; users can browse, inspect, edit, retrieve, and ask cited questions about one selected document from the compact workspace.
- **Tests required:** Capability API/middleware; document-scoped retrieval; frontend shell/component/integration/accessibility; backend/frontend regression; formatting/static/build/audit; migration drift.
- **Dependencies:** HIC-025, HIC-034, HIC-039, HIC-043, HIC-047, and HIC-048.
- **Status:** Completed — the runtime feature boundary, compact document-first shell, dense archive/detail/preview workspace, selected-document Copilot scoping, provenance display, responsive CSS, and full automated validation are delivered.

## P0 — Automated document delivery

### HIC-056 — Ingest allowlisted Gmail PDF attachments

- **Purpose:** Let household members add records by emailing a dedicated inbox instead of opening the HIC upload interface.
- **Implementation scope:** Gmail OAuth REST client; bounded polling worker; exact sender allowlist; PDF-only attachment handling; household-scoped idempotency/outcome records; existing private document/OCR/index pipeline; retry and Gmail labels; protected redacted history; document-source UI provenance; Docker and operator setup.
- **Acceptance criteria:** An allowlisted synthetic PDF becomes one searchable document; repeated messages/content do not duplicate storage; unapproved senders are rejected before download; transient failures retry no more than configured; terminal messages are labeled; secrets, bodies, and provider IDs are never exposed; Gmail remains disabled unless completely configured.
- **Tests required:** Client parsing/token/label behavior; complete pipeline; attachment and content idempotency; sender/limit rejection; processing retry; status API and household scope; model/migration; full backend/frontend, static, build, audit, Compose, and live PostgreSQL gates.
- **Dependencies:** HIC-020, HIC-021, HIC-022, HIC-025, HIC-043, HIC-046, and HIC-049.
- **Status:** Completed — the OAuth/Gmail adapter, DMARC/spam and exact-address guards, bounded idempotent worker, existing OCR/index pipeline integration, redacted audit API, provenance UI, migration, Compose profiles, setup documentation, 463 backend tests, 78 frontend tests, static/build/audit checks, isolated PostgreSQL head/drift verification, container builds, and production health regression all pass.

## Recommended next task

### HIC-050 — Add document collections and tags

- **Purpose:** Keep a growing household archive browsable by user-defined context in addition to deterministic type and facts.
- **Implementation scope:** Optional normalized collection name and bounded normalized tags on each household document; collection filtering; metadata API updates; compact collection rail and organization controls.
- **Acceptance criteria:** Users can assign, replace, clear, display, and filter collections/tags; values remain household-scoped and are deleted with the document; deterministic classifier metadata is unchanged.
- **Tests required:** Migration/model defaults and constraints; normalization; metadata update; filtering; API client; component organization/filter UI; full regressions and delivery gates.
- **Dependencies:** HIC-039 and HIC-049.
- **Status:** Completed — collection/tag persistence, normalization, filtering, compact organization controls, collection navigation, migration, and focused automated coverage are delivered.

### HIC-052 — Separate and compact document archive panes

- **Purpose:** Keep the archive list and selected-document inspector visually distinct and readable at realistic desktop widths.
- **Implementation scope:** Replace the shared three-pane surface with independently bordered panes and gutters; remove inherited button emphasis from document rows; constrain name, type, and key-date cells; compact key-date/status typography; preserve responsive stacking.
- **Acceptance criteria:** List values cannot overflow into the detail pane; the selected-document pane has an unambiguous boundary; key dates and statuses remain legible without competing with document names; collections, selection, pagination, and narrow layouts remain usable.
- **Tests required:** Document workspace component regression; frontend test, lint, type, and production-build gates; responsive visual verification when the browser runtime is available.
- **Dependencies:** HIC-049 and HIC-050.
- **Status:** Completed — archive panes now have independent surfaces and gutters, list columns shrink safely, inherited row emphasis is reset, date/status values are compact, and the detail pane moves below the list before the desktop layout becomes cramped.

### HIC-053 — Compact archive controls and search workflow

- **Purpose:** Make the document workspace feel like a crisp archive rather than a set of oversized forms and competing panels.
- **Implementation scope:** Compact archive-scoped controls and document actions; collapsible collection navigation; filename-only search mode in the primary search field; immediate type filtering; concise two-line text-search context with filenames and original-document links; date-only key-date values; collection/tag editing inside document details; a compact selected-document question control without a redundant Copilot panel.
- **Acceptance criteria:** Primary controls and document actions use materially less space; collapsing collections gives the list more width; key-date cells contain only dates or an empty marker; filename search does not invoke text retrieval; text results contain bounded context and a PDF link without a full-card green hover; existing upload, selection, metadata, document-question, pagination, and responsive behavior remain accessible.
- **Tests required:** Text and filename-only search; result context/provenance link; immediate type filtering; collection collapse; date-only key-date behavior; organization editing; full frontend tests, lint, typecheck, and production build.
- **Dependencies:** HIC-039, HIC-049, HIC-050, and HIC-052.
- **Status:** Completed — archive controls/actions are compact, collections collapse, search modes share one field, results provide bounded context and source links, key dates are semantically consistent, organization/question controls are consolidated into the selected-document pane, and the redundant standalone document Copilot is absent from the document-first shell.

### HIC-054 — Replace duplicate sidebar navigation with reminder notifications

- **Purpose:** Give the archive maximum horizontal space while keeping time-sensitive document reminders discoverable without permanent banners.
- **Implementation scope:** Replace the document-first left sidebar with a compact top bar; keep collection navigation only inside the archive; add an always-available bell with a count badge; move reminder records and actions to a dedicated in-app notifications view; retain a subtle API health indicator and optional financial navigation.
- **Acceptance criteria:** The archive uses the full application width; document/collection/reminder links are not duplicated; no reminder banner or permanent reminder list appears in the archive; the bell badge reflects active reminders; the dedicated view supports empty state, source selection, acknowledgement, snooze, action feedback, and returning to documents; optional financial navigation remains available when enabled.
- **Tests required:** Compact shell and capability navigation; bell counts; empty and populated notification views; reminder actions and return navigation; accessibility; full frontend tests, lint, typecheck, build, and audit.
- **Dependencies:** HIC-048, HIC-049, and HIC-053.
- **Status:** Completed — the redundant sidebar and reminder banners are removed, the archive spans the viewport beneath a slim top bar, and reminder discovery/actions live behind a source-linked notification bell and dedicated view.

### HIC-055 — Restore collection organization and add bulk document actions

- **Purpose:** Let users organize and manage several household documents without repeating the same action one record at a time.
- **Implementation scope:** Add page-level and row-level document selection; selection-first create/choose collection assignment; confirmed multi-document deletion with explicit partial-failure reporting; multi-PDF upload through the existing bounded upload/extract/index pipeline; opaque upload popover; automatic file-control reset and popover close after processing.
- **Acceptance criteria:** One or many visible documents can be selected; typing a new collection name creates it through assignment while existing names are suggested; bulk collection updates refresh the archive; bulk deletion requires confirmation and reports successes/failures; multiple valid PDFs process independently; duplicate/upload/index failures are explained; the upload surface is opaque and closes after a completed attempt; individual actions remain available.
- **Tests required:** Single-upload regression; multiple upload/process/reset/close; duplicate and processing failures; select page; multi-document collection assignment; guarded multi-delete; partial-failure state; existing metadata/delete integration; full frontend tests, lint, typecheck, build, and audit.
- **Dependencies:** HIC-039, HIC-050, HIC-053, and HIC-054.
- **Status:** Completed — collection assignment is restored as a bulk toolbar, archive rows support multi-selection, uploads accept and process multiple PDFs in one attempt, confirmed bulk deletion is available, and the upload popover is opaque and self-closing.

## Recommended next task

HIC-051 — add a document retention and encrypted backup/restore workflow before expanding external notifications or cloud synchronization.
