# Home Intelligence Copilot Roadmap

## Status vocabulary

- **Completed:** Acceptance criteria are implemented and validated.
- **In progress:** Some approved backlog tasks are complete, while milestone work remains.
- **Next:** Recommended milestone; implementation requires explicit approval.
- **Planned:** Ordered but not approved for implementation.
- **Blocked:** Cannot proceed until a named dependency or decision is resolved.

## Completed baseline

### Backend and development foundation

- **Status:** Completed
- **Delivered:** Python 3.12 FastAPI project, environment settings, PostgreSQL, SQLAlchemy, Alembic, Docker Compose, Dockerfile, health endpoint, Pytest, Ruff, and mypy.
- **Evidence:** Health/API tests pass, Compose services run, and the PostgreSQL migration is at `20260801_01`.

### Transaction models and CSV ingestion

- **Status:** Completed
- **Delivered:** `ImportBatch` and `Transaction` models, UUIDs, exact money storage, constraints, indexes, atomic CSV import, strict validation, row errors, upload limit, sample data, and rollback tests.
- **Evidence:** Synthetic canonical/Citi/Chase/Bank of America imports, transaction/import queries, analytics, provenance, strict header-location detection, and metadata-row accounting are working; private in-memory API smoke imports passed 27/27 Chase and 16/16 Bank of America rows, and the full suite contains 198 passing tests after HIC-030.

## Milestone 1: Transaction query and import-history APIs

- **Completion status:** Completed — HIC-001 through HIC-003 plus HIC-031 are implemented and validated.
- **User value:** Users can inspect what was imported, find transactions, and verify provenance before trusting analytics.
- **Scope:** Paginated transaction listing; filters for date, account, category, merchant, and import batch; import-batch list/detail endpoints; atomic owned-batch deletion with dependent-record cascades; stable sorting; typed response schemas and an explicit deletion confirmation UI.
- **Exclusions:** Editing individual transactions, restoring deleted imports, analytics totals, duplicate decisions, categorization rules, and AI.
- **Technical tasks:** Define query contracts; add repository/query services; add thin routes; implement pagination and bounded filters; expose import counts/status/timestamps; update OpenAPI and docs.
- **Acceptance criteria:** APIs return deterministic order, validated filters, pagination metadata, Decimal-safe amounts, and clear 404/validation responses; an import can be traced to its transactions.
- **Required tests:** Empty/list/detail cases; pagination boundaries; each filter; combined filters; ordering; invalid ranges/UUIDs; missing batch; query-count or eager-loading regression where relevant.
- **Dependencies:** Completed models, migration, and CSV ingestion.
- **Risks:** Unbounded queries, unstable pagination, accidental exposure of sensitive fields, and API contracts that make later analytics awkward.

## Milestone 1A: Multi-institution CSV adapters

- **Completion status:** Completed — HIC-026 through HIC-030 plus HIC-032 are implemented and validated for all currently reviewed household CSV layouts.
- **User value:** Household members can repeatedly upload the Citi, Chase, and Bank of America CSV exports they already use without private manual conversion steps.
- **Scope:** Versioned adapter/provenance contracts; exact header-signature and reviewed-row detection; canonical importer refactor; reviewed statement and activity-report layouts per institution/product; explicit account labels; imported Citi categories; sanitized synthetic fixtures; direct upload through the existing endpoint.
- **Exclusions:** Direct bank connections, credential storage, scraping, OFX/PDF support, heuristic format guessing, automatic support for unreviewed layout changes, and committing real statements or identifiers.
- **Technical tasks:** Add adapter provenance migration; define typed adapter protocol and registry; preserve the canonical format; implement strict institution mappings one at a time; extend import/history/detail responses; add fixture privacy checks and private local smoke-test procedures.
- **Acceptance criteria:** Supported formats are detected uniquely and normalize deterministically into the existing model; unknown/ambiguous formats fail before persistence; every batch records adapter/version provenance; all existing size, validation, error-count, and atomicity guarantees remain; repository fixtures are synthetic and sanitized.
- **Required tests:** Provenance model/migration; registry selection and ambiguity; canonical regression; per-adapter dates/signs/fields; malformed/mixed rows; rollback; response provenance; privacy scans; private local end-to-end smoke tests.
- **Dependencies:** Completed atomic importer and inspection APIs plus privately reviewed Citi, Chase, and Bank of America samples; those samples remain outside source control.
- **Risks:** Institutions change headers without notice, different products from one institution use different formats, debit/credit conventions may invert amounts, real samples may leak sensitive data, and overlapping exports may introduce duplicates before duplicate detection exists.

## Milestone 2: Deterministic spending analytics

- **Completion status:** Completed — HIC-004 through HIC-008 define and implement deterministic analytics semantics version `1.0`.
- **User value:** Users can answer exact spending questions by date, category, merchant, and account and compare periods confidently.
- **Scope:** Typed analytics services and read-only APIs for totals, grouped breakdowns, period comparison, large transactions, and explicit inclusion/exclusion rules.
- **Exclusions:** Natural language, AI explanations, predictive advice, categorization inference, and document-derived amounts.
- **Technical tasks:** Define date-range semantics; implement Decimal aggregation; create result schemas with filters and record counts; add analytics routes; document verified versus inferred values.
- **Acceptance criteria:** Synthetic fixtures produce exact expected totals; all endpoints return explicit date ranges/currency assumptions; calculations never use float or an LLM.
- **Required tests:** Empty periods; credits/refunds; negative and positive amounts; category/account filters; boundary dates; rounding/precision; period comparisons; large-transaction thresholds.
- **Dependencies:** Milestone 1 query contracts and normalized transaction data.
- **Risks:** Ambiguous sign conventions, incorrect treatment of transfers/income/refunds, timezone/date-boundary confusion, and misleading category gaps.

## Milestone 3: Duplicate transaction detection

- **Completion status:** Completed — HIC-009 and HIC-010 implement non-destructive persistence, versioned exact cross-import detection, atomic candidate creation, and review/query APIs.
- **User value:** Re-importing overlapping files does not silently inflate spending totals.
- **Scope:** Deterministic candidate fingerprinting, duplicate status/reason, import-time candidate detection, and review-friendly query results.
- **Exclusions:** Automatic destructive deletion, probabilistic ML matching, cross-household comparison, and bank-specific identifiers not present in the source.
- **Technical tasks:** Define duplicate semantics; add schema/migration if needed; implement canonical fingerprint/candidate service; integrate with imports; expose candidate state to queries.
- **Acceptance criteria:** Exact duplicate fixtures are consistently identified; legitimate same-day/same-amount transactions are not automatically discarded; every decision retains provenance.
- **Required tests:** Same file twice; overlapping files; whitespace variants; posted-date differences; same amount at different merchants; false-positive boundaries; migration and rollback behavior.
- **Dependencies:** Milestones 1 and 2, especially established transaction semantics.
- **Risks:** False positives, false negatives, changing fingerprints after normalization changes, and analytics including unresolved candidates inconsistently.

## Milestone 4: Transaction categorization

- **Completion status:** Completed - HIC-011 and HIC-012 are implemented, validated, documented, and merged.
- **User value:** Users get useful category breakdowns while retaining control over how transactions are classified.
- **Scope:** Transparent deterministic rules, category assignment provenance, manual override capability through APIs, and uncategorized review.
- **Exclusions:** LLM-only categorization, opaque ML models, tax classification, and a comprehensive merchant database.
- **Technical tasks:** Delivered category/rule/current-assignment persistence, normalized deterministic matching, priority/UUID precedence, visible conflicts, atomic scoped application, manual override protection, denormalized-label synchronization, and focused APIs.
- **Acceptance criteria:** The same inputs and rules always produce the same category; manual choices are never silently overwritten; uncategorized transactions remain visible.
- **Required tests:** Rule precedence; normalization; conflicting rules; manual override protection; batch recategorization; rollback; analytics integration.
- **Dependencies:** Milestone 2 analytics and Milestone 3 duplicate semantics.
- **Risks:** Rule conflicts, category drift, overbroad merchant matching, and recalculation changing historical reports unexpectedly.

## Milestone 5: Basic web frontend

- **Completion status:** Completed — HIC-013 through HIC-015 deliver the tested browser import-to-insight workflow.
- **User value:** Non-technical users can upload files, review imports, browse transactions, and view analytics without Swagger or command-line tools.
- **Scope:** Small web shell, CSV upload/results, import history, transaction table/filters, and deterministic analytics views.
- **Exclusions:** AI chat, document workflows, mobile-native applications, complex design systems, and multi-user administration.
- **Technical tasks:** React, TypeScript, and Vite were selected through ADR-016. The shell, health client, local proxy, error boundary, responsive styling, typed API clients, multipart upload/results, import history/detail, transaction filtering/pagination, spending/category/period analytics, recoverable URL state, and automated frontend checks are delivered.
- **Acceptance criteria:** A user can complete the core import-to-insight workflow in a browser; errors and rejected rows are understandable; no business calculations run only in the browser.
- **Required tests:** Component states; form validation; upload flow; filter/pagination integration; accessibility checks; end-to-end happy path and failed import.
- **Dependencies:** Milestones 1 through 4 and stable API contracts.
- **Risks:** Premature UI abstractions, duplicated business logic, accessibility gaps, and exposing sensitive data through browser logs/storage.

## Milestone 6: OpenAI integration with controlled tool calling

- **Completion status:** Completed — HIC-016 defines the provider-independent read-only analytics tool boundary and HIC-017 adds the optional bounded OpenAI orchestrator, strict tool calls, deterministic safety policy, evidence responses, and numeric grounding checks.
- **User value:** Users can ask plain-language questions and receive explanations grounded in verified analytics.
- **Scope:** Intent/clarification flow, allowlisted read-only tools backed by deterministic services, typed tool arguments/results, answer grounding, and clear fact-versus-interpretation language.
- **Exclusions:** Direct model database access, model-calculated totals, autonomous actions, document RAG, financial advice, and unrestricted code/tool execution.
- **Technical tasks:** The immutable four-tool allowlist, argument/result schemas, ambiguity rules, shared deterministic result builders, OpenAI Responses provider, strict single-tool loop, refusal and clarification policy, privacy-safe result minimization, numeric grounding validation, and optional API surface are delivered. A conversational web view remains optional future interface work.
- **Acceptance criteria:** Supported questions invoke the correct approved tool; numeric claims exactly match tool results; unsupported/advisory requests are refused or redirected; AI can be disabled without breaking analytics.
- **Required tests:** Tool selection; argument validation; ambiguous questions; prompt injection; unsupported requests; grounding; timeout/provider failure; no-secret logging.
- **Dependencies:** Completed and tested Milestone 2 analytics, plus stable query/category behavior.
- **Risks:** Hallucination, prompt injection, privacy leakage, provider changes, latency/cost, and overconfidence in interpretations.

## Milestone 7: AI answer evaluation

- **Completion status:** Completed — HIC-018 provides a versioned synthetic suite, deterministic graders, privacy-safe reports, exact release thresholds, and a live synthetic provider runner.
- **User value:** AI behavior can improve without silently regressing factual accuracy, safety, or usefulness.
- **Scope:** Synthetic evaluation dataset, tool-selection scoring, numeric-grounding checks, refusal/clarification tests, qualitative rubrics, and repeatable regression reports.
- **Exclusions:** Training a custom model, evaluations using real household data, and optimizing only for style.
- **Technical tasks:** Synthetic cases, deterministic graders, model/prompt/tool/dataset metadata, the automated runner, critical-case rule, and 100% release threshold are complete. Human review remains an optional supplement for clarity and tone.
- **Acceptance criteria:** Every AI change can be evaluated against a versioned synthetic suite; numeric mismatches and missing citations fail; results are reproducible enough for comparison.
- **Required tests:** Eval runner unit tests; intentionally bad-answer detection; tool-result mismatch; ambiguity; refusal; injection; provider-error handling.
- **Dependencies:** Milestone 6 controlled tool calling.
- **Risks:** Brittle graders, evaluator-model bias, non-determinism, leaking test cases into prompts, and metrics that do not reflect user trust.

## Milestone 8: Household document ingestion

- **Completion status:** Completed — HIC-019 accepted the architecture, HIC-020 added bounded private PDF lifecycle, and HIC-021 added versioned native-text extraction with page/section provenance, visible failures, retry, and cascade deletion.
- **User value:** Users can privately organize and search bills, receipts, policies, warranties, and project records.
- **Scope:** Document metadata, safe upload/storage, checksums, processing status, text extraction for selected formats, provenance, and deletion/retention behavior.
- **Exclusions:** RAG answers, every file type, perfect OCR, automated advice, email/drive connectors, and broad third-party synchronization.
- **Technical tasks:** The storage/security ADR, initial PDF boundary, metadata and extraction migrations, private adapter, lifecycle/compensation flow, checksum duplicate rule, bounded upload, retention/deletion/backup policy, household migration plan, versioned extractor adapter, page/section character provenance, and processing/retry states are complete.
- **Acceptance criteria:** Supported synthetic documents can be uploaded, extracted, retrieved, and deleted with provenance; unsupported/malicious inputs fail safely; originals are private.
- **Required tests:** Type/size validation; checksum behavior; extraction fixtures; failure/retry; path traversal; deletion; authorization boundaries when available; migration tests.
- **Dependencies:** Stable core platform and privacy design; may proceed independently of AI but follows the ordered roadmap.
- **Risks:** Sensitive data exposure, malicious files, extractor vulnerabilities, OCR errors, storage growth, and unclear retention/backups.

## Milestone 9: RAG with citations

- **Completion status:** Completed — provenance-preserving lexical retrieval, household filtering, strict structured claims, server-rendered citations, source-instruction filtering, explicit conflicts/no-results, analytics routing, and the synthetic RAG release suite are implemented. Lexical evaluation did not justify embeddings.
- **User value:** Users can ask document questions and verify answers against exact household sources.
- **Scope:** Chunking with provenance, retrieval, optional embeddings if justified, context assembly, cited answers, uncertainty handling, and retrieval evaluation.
- **Exclusions:** Uncited claims, using RAG for exact transaction totals, cross-household retrieval, and autonomous document actions.
- **Technical tasks:** Chunk schemas, deterministic chunking, PostgreSQL lexical retrieval, authorization, bounded context, source-instruction filtering, strict claim schemas, exact citation rendering, numeric grounding, answer policy, and versioned retrieval/citation evaluation are complete.
- **Acceptance criteria:** Material claims link to correct document locations; missing evidence produces an explicit limitation; retrieval never crosses the active household; analytics questions still use analytics tools.
- **Required tests:** Chunk provenance; retrieval relevance; citation correctness; no-result/conflict behavior; prompt injection in documents; authorization filtering; regression evals.
- **Dependencies:** Milestones 7 and 8, with a reliable evaluation harness and document pipeline.
- **Risks:** Prompt injection, irrelevant retrieval, incorrect citations, context leakage, embedding cost, and overconfident synthesis.

## Milestone 10: Authentication and privacy hardening

- **Completion status:** Completed foundation — HIC-024 accepted the threat model and HIC-025 implements the selected owner authentication, opaque sessions, CSRF/origin controls, audit events, non-null household backfill, tenant-scoped persistence, and protected frontend. Production operation still requires TLS, encrypted/protected backups, monitoring, and deployment review.
- **User value:** The application can be used beyond a trusted local machine with enforceable identity, household isolation, and operational safeguards.
- **Scope:** Authentication, household authorization, secure sessions, CSRF/rate-limit protections, audit events, secret management, transport guidance, retention/deletion, and backup/restore procedures.
- **Exclusions:** Enterprise identity administration, social-network features, financial account custody, and compliance certifications not justified by deployment scope.
- **Technical tasks:** Threat model, authentication/household-isolation ADR, identity/session/audit schema, deterministic bootstrap backfill, non-null ownership, scoped services/tools/retrieval, CSRF/rate limits, secure configuration, recovery, and operational validation are complete.
- **Acceptance criteria:** Every sensitive record is household-scoped; unauthenticated/cross-household access fails; secrets and logs are reviewed; backup, restore, export, and deletion behavior are documented and tested.
- **Required tests:** Authentication/session lifecycle; authorization matrix; IDOR attempts; CSRF; rate limits; tool and retrieval isolation; audit redaction; migration/backfill; backup/restore exercise.
- **Dependencies:** Stable data domains and interfaces from earlier milestones. Basic privacy rules remain mandatory before this milestone.
- **Risks:** Authorization gaps, migration of existing unowned data, recovery complexity, secret leakage, and a false sense of security from incomplete hardening.

## Milestone 11: Copilot and document workspace UI

- **Completion status:** Completed — HIC-033 through HIC-036 provide the household-scoped document library, private document workspace, controlled evidence/citation Copilot, integrated accessibility coverage, isolated synthetic browser QA, and manual testing guidance.
- **User value:** Users can manage household documents and ask grounded financial or document questions without relying on Swagger.
- **Scope:** Paginated document discovery, document upload/extraction/index/search/delete workflows, distinct analytics/document Copilot modes, evidence and citation rendering, responsive accessibility, and integrated browser validation.
- **Exclusions:** Mobile apps, PDF rendering/download, OCR, embeddings, autonomous actions, multi-turn memory, streaming, broad visual redesign, and production hosting.
- **Technical tasks:** Add a metadata-only document list API; build document API clients and workspace; build controlled Copilot clients and response views; add integrated accessibility and browser coverage; document manual testing.
- **Acceptance criteria:** A user can complete upload through deletion in the web app; ask supported analytics and document questions; inspect deterministic evidence and exact citations; recover from disabled/error/no-result/conflict states; and use primary flows by keyboard on desktop and mobile layouts.
- **Required tests:** Backend document query/isolation/redaction tests; frontend API/component/integration/accessibility tests; production build and dependency audit; browser primary, failure, responsive, and console checks.
- **Dependencies:** Completed Milestones 5–10, especially HIC-015, HIC-017, HIC-023, and HIC-025.
- **Risks:** Sensitive-text exposure, stale lifecycle state, inaccessible citation controls, accidental RAG use for financial totals, provider cost/failures, and UI state divergence.

## Milestone 12: Document-first workspace refinement

- **Completion status:** Completed — HIC-037 through HIC-042 are delivered and tracked as Linear HOM-41 through HOM-46.
- **User value:** A household can use the product as a compact, searchable private document archive while retaining a practical transaction workspace and trustworthy answers.
- **Scope:** Denser responsive presentation; compact modal transaction import and master-detail history; automatic PDF extraction and indexing; actionable duplicate-upload recovery; document metadata, filtering, secure original access, and citation links; readable Copilot answers and deterministic relative-date handling; transaction category editing and backend-derived totals.
- **Exclusions:** Public document links, cloud-drive synchronization, OCR and broad file-format support, mobile-native apps, autonomous financial actions, AI-generated financial calculations, and production hosting.
- **Technical tasks:** Compact the current shell and import workspace; orchestrate the existing upload/extract/index services behind one user action; extend the existing `Document` metadata model only where organization requires it; consolidate document search and library workflows; add authorized original-content delivery; safely render answer emphasis; resolve relative periods in deterministic code; integrate existing category-assignment APIs and deterministic summaries into transactions.
- **Acceptance criteria:** Core desktop views require materially less scrolling; a valid PDF becomes searchable after one upload action; duplicate content points to the existing record; users can organize, find, and securely retrieve originals; Copilot answers contain no literal formatting markers and resolve “last month” explicitly; transaction categories and active-filter totals are useful without relying on AI arithmetic.
- **Required tests:** Frontend component/integration/accessibility and responsive tests; document lifecycle, metadata, authorization, secure-content, and citation tests; relative-date boundary tests; category update and deterministic-total tests; full backend/frontend regressions and focused browser QA.
- **Dependencies:** Milestones 2, 4, 5, 6, 9, 10, and 11.
- **Risks:** Sensitive-document exposure, partial processing states, duplicate confusion, unsafe rendered model text, timezone ambiguity, clutter returning as features grow, and transaction-summary drift.

## Milestone 13: Automated document understanding

- **Completion status:** Completed — HIC-043 delivered the versioned metadata classifier, provenance persistence, user-override protection, API/UI presentation, migration, automated coverage, and responsive browser QA; tracked as Linear HOM-47.
- **User value:** Newly uploaded household PDFs organize themselves with a useful title and conservative document type while every user correction remains authoritative.
- **Scope:** Safe embedded-title extraction; deterministic filename/text classification for identity, tax, financial, insurance, warranty, and home documents; inference provenance/confidence; automatic application to blank fields; subtle library presentation.
- **Exclusions:** OCR, external-model classification, people/account/identifier extraction, arbitrary taxonomies, retention automation, autonomous actions, and silent background inspection of existing stored files.
- **Technical tasks:** Add household-scoped inference persistence and migration; version the classifier; integrate it atomically with extraction; track automatic versus user sources; expose results in library schemas; present provenance; document semantics.
- **Acceptance criteria:** Recognizable synthetic documents receive useful metadata; weak/tied results remain unclassified; inference contains no raw text; manual values and explicit clears survive retry/version changes; deletion and household isolation include inference records.
- **Required tests:** Rule coverage, ambiguity, title precedence, persistence, provenance, override/clear protection, retry/idempotency, deletion, household scoping, API/UI rendering, migrations, regressions, and browser QA.
- **Dependencies:** Milestones 8, 10, 11, and 12.
- **Risks:** Misclassification, misleading confidence, sensitive evidence leakage, classifier drift, and users mistaking suggestions for verified document facts.

## Milestone 14: Broader private-document compatibility

- **Completion status:** Completed — HIC-044 (Linear HOM-48) and HIC-045 (Linear HOM-49) pass full regression, migration/schema, build/audit, and private local compatibility checks and have been delivered.
- **User value:** Common letters and records with ordinary links upload successfully and organize into useful employment, immigration, legal, medical, education, correspondence, or receipt types.
- **Scope:** Strictly validated web/email PDF links; specific unsafe-content errors; classifier version 2; broader deterministic taxonomy; descriptive-filename title precedence; matching UI choices; private local compatibility checks.
- **Exclusions:** OCR, external-model classification, arbitrary link execution, automatic form processing, structured expiration facts, notifications, and committing real household documents.
- **Technical tasks:** Narrow annotation validation to safe URI actions; preserve deny-first handling for executable behavior; expand and version type signals; improve title precedence; update UI options, documentation, and synthetic tests.
- **Acceptance criteria:** Safe synthetic URI links pass while unsafe actions fail before persistence; each new type has deterministic coverage; weak/tied documents stay unclassified; user overrides still win; provided private local documents validate without entering repository history.
- **Required tests:** Link scheme/action matrix, rollback, classifier matrix and ambiguity, title precedence, UI options, full regressions, static checks, production build/audit, and local-only API validation.
- **Dependencies:** Milestones 8, 10, 11, 12, and 13.
- **Risks:** Permitting overly broad PDF actions, unsafe schemes, classification collisions, misleading titles, and accidental inclusion of private samples.

## Milestone 15: Local OCR for scanned documents

- **Completion status:** Completed — HIC-046 delivers and validates native-first local OCR, bounded runtime configuration, synthetic scan coverage, Docker engines, immutable provenance, safe failures, metadata inference, and searchable output.
- **User value:** Printed household records scanned as image-only PDFs become searchable and usable by metadata inference and cited document answers without a cloud OCR bill or external document processor.
- **Scope:** Native-first page extraction; local OCRmyPDF/Tesseract fallback for pages without native text; versioned extraction provenance; language, timeout, and text bounds; Docker runtime; synthetic validation.
- **Exclusions:** Cloud OCR, handwriting guarantees, layout coordinates/tables, background workers, arbitrary image formats, structured expiration facts, and notifications.
- **Technical tasks:** Add the composite extractor and fixed OCR runner; configure local engine/language/timeout; install runtime dependencies; exercise OCR spans through persistence, metadata inference, chunking/search compatibility, and safe failure states; document privacy and operations.
- **Acceptance criteria:** Native documents avoid OCR; a synthetic scan becomes searchable with correct page/source provenance; originals remain immutable; failures and timeouts fail closed; no OCR content leaves the local environment.
- **Required tests:** Native bypass; image-only and mixed-page extraction; text/time/configuration limits; engine failure; persistence/provenance; retrieval compatibility; regressions; Docker build and live OCR smoke test.
- **Dependencies:** Milestones 8 through 10, 12 through 14, and their document privacy/provenance foundations.
- **Risks:** CPU and latency spikes, poor scan/language quality, OCR inaccuracies, oversized container images, temporary-file exposure, and synchronous request timeouts.

## Milestone 16: Structured document facts and expiration tracking

- **Completion status:** Completed — HIC-047 delivers conservative provenanced facts, authoritative corrections, expiration-state queries, library presentation, PostgreSQL migration, and full automated/runtime validation.
- **User value:** Household records expose useful dates and identifiers in the library, users can correct them, and expiring documents can be queried predictably.
- **Scope:** Five conservative structured fact types; extraction/page/rule provenance; manual overrides and explicit clears; expiration state; API and library UI.
- **Exclusions:** Notifications, background scheduling, retention enforcement, tax interpretation, person/entity graphs, cloud extraction, and probabilistic fact generation.
- **Technical tasks:** Add household-owned fact persistence and migration; deterministic labeled-value rules shared by native/OCR extraction; atomic refresh with override protection; fact and expiration APIs; correction and provenance UI; documentation.
- **Acceptance criteria:** Unambiguous labeled facts persist with provenance; uncertain dates are omitted; user values always win; expiration state is reproducible from caller input; facts obey ownership and lifecycle boundaries.
- **Required tests:** Rules and ambiguity, constraints, atomic extraction, retries/version changes, correction/clear, expiration boundaries, deletion/isolation, API/UI, migrations, regressions, static checks, build, and audit.
- **Dependencies:** Milestones 8, 10, 11, 13, and 15.
- **Risks:** Incorrect dates appearing authoritative, sensitive identifiers leaking through logs, stale facts, timezone confusion, and notification fatigue in future work.

## Milestone 17: In-app document expiration reminders

- **Completion status:** Completed — HIC-048 delivers opt-in, duplicate-free in-app reminders, household-timezone date semantics, acknowledgement and renewal behavior, snooze, source-linked UI, migration, and full automated/runtime validation.
- **User value:** Expired and soon-to-expire household records appear in one actionable, source-linked dashboard.
- **Scope:** Explicit opt-in; one in-app configuration per document; configurable lead windows; household timezone; acknowledgement, renewal reactivation, and snooze.
- **Exclusions:** Email, Slack, push notifications, background schedulers, retention enforcement, renewal automation, and legal/compliance advice.
- **Technical tasks:** Add household-owned reminder persistence and migration; deterministic lifecycle service and APIs; library configuration controls; attention dashboard; tests and documentation.
- **Acceptance criteria:** Alerts are duplicate-free and date-boundary correct; user actions persist; a changed expiration reactivates an acknowledged reminder; deletion and ownership boundaries hold.
- **Required tests:** Model/API lifecycle, timezone and date boundaries, acknowledgement/renewal, snooze, deletion/isolation, UI interactions, migrations, regressions, static checks, build, and audit.
- **Dependencies:** Milestones 10 and 16.
- **Risks:** Alert fatigue, incorrect source dates, stale acknowledgements, timezone confusion, and users assuming in-app alerts are guaranteed external delivery.

## Milestone 18: Compact document-first workspace

- **Completion status:** Completed — HIC-049 makes the private document archive the default application experience while preserving financial features behind a runtime capability flag.
- **User value:** Users see a compact records workspace with fast browsing, original previews, metadata, reminders, and a Copilot scoped to the selected document.
- **Scope:** Runtime capabilities; fail-closed financial feature boundary; document-first sidebar; dense archive rows; selected-record preview/detail; scoped cited questions; responsive and accessibility coverage.
- **Exclusions:** Collections/tags, cloud synchronization, mobile-native applications, external notifications, public links, and changes to deterministic financial calculations.
- **Technical tasks:** Add the capabilities route and middleware boundary; conditionally compose the frontend; compact the shell and archive; add authorized inline preview; pass document identity through the question and retrieval layers; update tests and configuration.
- **Acceptance criteria:** Docker starts document-first by default; finance can be restored through configuration; disabled financial APIs are unavailable; document questions initiated from the detail panel retrieve only that document; primary layouts remain usable at narrow widths.
- **Required tests:** Backend capability/scoping and full regression; frontend component/integration/accessibility and full regression; lint, formatting, type checks, build, audit, and Alembic head/drift verification.
- **Dependencies:** Milestones 10 through 17.
- **Risks:** Hidden routes remaining callable, ambiguous selected-document context, excessive density on small screens, and feature-flag divergence.

## Milestone 19: Household archive organization

- **Completion status:** Completed — HIC-050 adds user-managed collections and tags to the document-first workspace.
- **User value:** Users can group records by household purpose and add lightweight labels without changing automatically detected document type or facts.
- **Scope:** One optional collection and up to 20 normalized tags per document; metadata updates; collection filtering; compact collection rail and organization bar.
- **Exclusions:** Nested folders, collection sharing, automatic AI tagging, bulk operations, cloud synchronization, and retention automation.
- **Technical tasks:** Extend document persistence and migration; validate and normalize metadata; add query filtering and schema fields; render and edit organization metadata; add focused API/UI tests.
- **Acceptance criteria:** Collection/tag changes are durable, household-scoped, removable, visible, and filterable; existing deterministic provenance remains authoritative and unchanged.
- **Required tests:** Migration/model, metadata normalization, query filter, API schema, client/component, full regressions, static checks, build, audit, and migration drift.
- **Dependencies:** Milestones 12, 13, and 18.
- **Risks:** Inconsistent user naming, over-tagging, pagination hiding collection discovery, and future migration from a single collection to richer folder membership.

## Milestone 20: Document archive pane refinement

- **Completion status:** Completed — HIC-052 separates and compacts the archive list and selected-document inspector.
- **User value:** Document names, types, key dates, previews, and metadata are easier to scan without columns colliding or the interface feeling like one merged surface.
- **Scope:** Independent pane surfaces and gutters; safe list-column sizing; compact row typography; constrained status/date values; an earlier responsive detail-pane transition.
- **Exclusions:** New document behavior, backend changes, metadata schema changes, bulk actions, alternate archive views, or a broader visual redesign.
- **Technical tasks:** Remove incompatible minimum column widths; reset inherited button typography; give the collection, list, and detail panes independent boundaries; tune detail preview height and responsive breakpoints.
- **Acceptance criteria:** No list cell enters the detail pane; each pane is visually distinct; document names retain priority; dates and statuses are compact; responsive layouts remain usable.
- **Required tests:** Document workspace component regression; frontend test, lint, type, and production-build gates; responsive visual verification when the browser runtime is available.
- **Dependencies:** Milestones 18 and 19.
- **Risks:** Excessive compaction, long translated labels, and future columns reintroducing minimum-width overflow.

## Milestone 21: Compact archive interactions and retrieval results

- **Completion status:** Completed — HIC-053 consolidates archive search/filtering, compacts controls, and removes the redundant standalone document Copilot from the document-first shell.
- **User value:** Users can scan, filter, search, open, organize, and ask about documents with fewer large controls and less empty space.
- **Scope:** Archive-specific compact controls; collapsible collections; unified text/filename search; immediate type filtering; bounded linked search context; consistent key dates; consolidated organization and selected-document question interactions.
- **Exclusions:** Backend retrieval changes, semantic/vector search, search-result highlighting, collection hierarchy, bulk document operations, new metadata, or changes to the grounded-answer service.
- **Technical tasks:** Branch the existing search interaction by explicit mode; constrain result excerpts; link authorized originals; remove the permanent organization row; resize archive controls and actions; add collection-collapse and key-date presentation state.
- **Acceptance criteria:** Search mode is explicit; filename-only queries filter the archive without chunk search; text results are concise and source-linked; key dates contain dates only; collections can release horizontal space; large archive buttons and the redundant question panel chrome are removed.
- **Required tests:** Component search/filter/collapse/date/metadata coverage; full frontend regression; ESLint; TypeScript; production build; responsive visual verification when browser QA is available.
- **Dependencies:** Milestones 18 through 20.
- **Risks:** Users overlooking filename-only mode, collection discovery on paginated data, over-compaction on touch devices, and excerpts omitting useful surrounding context.

## Milestone 22: Full-width archive and reminder notification center

- **Completion status:** Completed — HIC-054 removes duplicated global navigation and moves reminders into an on-demand notification view.
- **User value:** The archive has more working space, while expiring records remain visible through a familiar bell and focused reminder list only when needed.
- **Scope:** Compact top bar; subtle API status; optional financial links; full-width archive; reminder count badge; populated and empty notification views; existing acknowledgement and snooze actions.
- **Exclusions:** External email/push notifications, background schedulers, browser notification permissions, reminder-rule changes, collection redesign, or backend API changes.
- **Technical tasks:** Recompose the application shell; remove duplicate document/reminder/collection links; move reminder rendering out of the archive; add view state, notification badge, action feedback, and responsive presentation.
- **Acceptance criteria:** No permanent left sidebar or reminder banner remains; the archive receives the reclaimed width; the badge count is accurate; users can open, act on, and leave the reminder view; zero reminders have a useful empty state.
- **Required tests:** Shell semantics and accessibility; financial capability navigation; bell count; reminder populated/empty/action flows; full frontend regression, lint, typecheck, build, and audit.
- **Dependencies:** Milestones 17 through 21.
- **Risks:** Bell discoverability, users expecting operating-system notifications, reminder count staleness between refreshes, and loss of navigation context when optional financial features are enabled.

## Milestone 23: Bulk document organization and lifecycle actions

- **Completion status:** Completed — HIC-055 restores direct collection organization and adds bounded multi-upload and confirmed multi-delete workflows.
- **User value:** A household can upload, organize, and remove groups of records with far fewer repetitive interactions.
- **Scope:** Row/page selection; create-or-choose collection assignment; independent multi-PDF upload processing; explicit bulk-delete confirmation; partial-failure feedback; opaque self-closing upload surface.
- **Exclusions:** Backend bulk endpoints, cross-page selection, atomic all-or-nothing deletion, drag-and-drop folders, nested collections, bulk tag editing, or background job processing.
- **Technical tasks:** Generalize upload state and orchestration to multiple files; preserve per-file validation and processing; add selection state and toolbar; batch existing metadata/delete API calls with settled-result accounting; update archive layout and tests.
- **Acceptance criteria:** Selection and bulk actions are accessible; new and existing collection names work; multiple files reset and close correctly; deletion never occurs without confirmation; partial results are explicitly reconciled; single-document behavior remains intact.
- **Required tests:** Single/multiple upload and failures; popover lifecycle; selection; bulk collection assignment; guarded deletion; partial results; full frontend regression, lint, typecheck, build, and audit.
- **Dependencies:** Milestones 19 through 22.
- **Risks:** Partial client-side batch completion, long synchronous processing for many PDFs, selection limited to the current page, and accidental deletion if confirmation language becomes ambiguous.

## Milestone 24: Gmail document intake

- **Completion status:** Completed — HIC-056 delivers guarded OAuth polling, automatic private-document processing, audit/idempotency persistence, labels/retries, provenance, protected history, Docker profiles, and operator documentation; 463 backend tests, 78 frontend tests, all static/build/audit gates, isolated PostgreSQL migration/head/drift validation, Compose profile validation, image builds, and the unchanged production health check pass.
- **User value:** Household members can email PDFs to one dedicated address and have them appear automatically as searchable private records.
- **Scope:** One Gmail mailbox and destination household; OAuth refresh-token access; exact sender allowlist; bounded PDF polling; idempotent attachment audit; existing PDF validation/storage/OCR/metadata/fact/index pipeline; outcome labels; protected redacted history; source provenance.
- **Exclusions:** Mailbox passwords, email-body ingestion, non-PDF conversion, Gmail push/Pub/Sub, multiple mailbox connections, configuration UI, automatic forwarding, public document links, and external OCR.
- **Technical tasks:** Add fail-closed settings and worker; implement Gmail REST/OAuth adapter; persist household-scoped attachment outcomes; extend document source; reuse processing services; add retry/label rules; expose safe history; update Compose and operations documentation.
- **Acceptance criteria:** Only allowlisted senders are downloaded; unsupported/oversized/unsafe PDFs do not persist; the same attachment and same content cannot create duplicate documents; successful PDFs become searchable with Gmail provenance; transient failures retry within bounds; credentials, bodies, and provider IDs stay out of API/log output; the worker publishes no port.
- **Required tests:** OAuth/API parsing; sender and size rejection; automatic processing/indexing; message and checksum idempotency; retries and terminal labels; household scoping; protected/redacted API; migration/model; backend/frontend regressions; static checks; builds; Compose and PostgreSQL migration validation.
- **Dependencies:** HIC-020 through HIC-022, HIC-025, HIC-043, HIC-046, and HIC-049.
- **Risks:** OAuth token revocation, mailbox compromise, spoofed/forwarded senders, attachment bombs, poll starvation, retry loops, sensitive subject metadata, and operators mistaking polling for guaranteed immediate delivery.

## Roadmap governance

- Only one small backlog task should be approved and implemented at a time.
- Completion requires tests, validation commands, documentation updates, and explicit acceptance-criteria review.
- Roadmap status changes belong in the same task that provides the evidence.
- AI work cannot begin before deterministic analytics are completed and tested.
- Real household data must never be added to source control or test fixtures.
