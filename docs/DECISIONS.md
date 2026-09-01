# Architecture Decision Log

This is a lightweight log of decisions already established by project guidance and implementation. New decisions should be appended rather than rewriting the history of an accepted decision.

## ADR-001: PostgreSQL is the production system of record

- **Status:** Accepted
- **Context:** Transactions, future analytics, and household-document metadata need durable constraints, indexing, migrations, and predictable concurrent access.
- **Decision:** Use PostgreSQL for development integration and production-minded persistence. Embedded databases may be used for fast isolated tests but are not the production target.
- **Consequences:** PostgreSQL-specific migrations must be validated separately from SQLite tests. Local development requires Docker or another PostgreSQL installation.

## ADR-002: Money uses `Decimal` and PostgreSQL `NUMERIC`

- **Status:** Accepted
- **Context:** Binary floating-point can introduce rounding errors that are unacceptable in household financial totals.
- **Decision:** Represent monetary values as Python `Decimal` and store them as PostgreSQL `NUMERIC`; the current transaction column is `NUMERIC(18,2)`.
- **Consequences:** Parsers and schemas reject unsupported precision, analytics must remain Decimal-safe, and JSON presentation must avoid float-based recomputation.

## ADR-003: Financial calculations are deterministic

- **Status:** Accepted
- **Context:** LLM-generated arithmetic is not sufficiently reliable or auditable for financial facts.
- **Decision:** SQL queries and typed application services calculate totals, groupings, comparisons, and flags. An AI model may later explain verified structured results but may not calculate totals from raw text.
- **Consequences:** Analytics must exist and be tested before natural-language features. Explanations must distinguish verified facts from interpretations.

## ADR-004: API handlers remain thin

- **Status:** Accepted
- **Context:** Mixing HTTP concerns, parsing, validation, database access, and business rules makes behavior difficult to test and reuse.
- **Decision:** Routes translate HTTP inputs and domain exceptions; they delegate business operations to typed services.
- **Consequences:** Service APIs require clear contracts, and route tests focus on transport behavior rather than duplicating business tests.

## ADR-005: Business logic belongs in service modules

- **Status:** Accepted
- **Context:** CSV ingestion and future analytics need to be callable from APIs, jobs, tools, or tests without depending on route handlers.
- **Decision:** Keep parsing, normalization, import orchestration, analytics, and future tool logic in focused service modules. Keep database session lifecycle and models separate.
- **Consequences:** Services receive explicit dependencies and own transaction boundaries where appropriate.

## ADR-006: Repository data is synthetic only

- **Status:** Accepted
- **Context:** Financial and household information is highly sensitive, and source-control history is difficult to erase.
- **Decision:** Commit only synthetic examples, tests, and evaluation fixtures. Never commit real statements, account numbers, documents, credentials, or tokens.
- **Consequences:** Bugs requiring representative data must be reproduced with sanitized synthetic fixtures. `.gitignore` excludes common upload locations and secret files.

## ADR-007: AI follows reliable analytics

- **Status:** Accepted
- **Context:** AI added before reliable query and analytics contracts would encourage ungrounded answers and unstable tool behavior.
- **Decision:** Build transaction queries, deterministic analytics, duplicate handling, and useful categorization before adding OpenAI integration.
- **Consequences:** OpenAI, embeddings, RAG, and prompt work remain out of scope until prerequisite roadmap milestones are accepted and tested.

## ADR-008: Slack is not the primary interface

- **Status:** Accepted
- **Context:** A household application needs rich uploads, tables, filters, citations, privacy controls, and review workflows that do not fit naturally in Slack.
- **Decision:** Treat a web interface and API as the primary product surfaces. Slack may become an optional adapter only if a concrete use case justifies it.
- **Consequences:** No Slack-specific business logic or identity model should shape the core architecture.

## ADR-009: CSV imports use one atomic persistence unit

- **Status:** Accepted
- **Context:** A database failure after partially writing a batch could create unexplained counts or transactions without reliable provenance.
- **Decision:** Parse and validate first, then write the import batch and all valid rows in one SQLAlchemy transaction. Roll back the whole unit on an unexpected persistence failure.
- **Consequences:** Mixed validation outcomes may intentionally import valid rows, but infrastructure failures do not leave partial state. Row validation errors are currently returned rather than persisted.

## ADR-010: Imported transactions retain provenance

- **Status:** Accepted
- **Context:** Analytics and future corrections must trace every transaction back to the upload that created it.
- **Decision:** Every transaction requires an `ImportBatch` foreign key and source filename; deleting a batch cascades to its transactions.
- **Consequences:** Query and history APIs should expose provenance without leaking filesystem details. Duplicate handling must not discard provenance silently.
## ADR-011: Analytics use versioned gross-spending semantics

- **Status:** Accepted
- **Context:** Spending totals are ambiguous without explicit rules for amount signs, date boundaries, credits, refunds, transfers, duplicates, missing categories, currency, and precision.
- **Decision:** Adopt analytics semantics version `1.0` from [`ANALYTICS_SEMANTICS.md`](ANALYTICS_SEMANTICS.md). Use inclusive `transaction_date` ranges; treat negative amounts as gross spending magnitudes; exclude positive and zero amounts; do not net refunds; include possible transfers and duplicates until reliable states exist; use exact case-sensitive filters; represent missing categories explicitly; assume and report USD; and use `Decimal` only.
- **Consequences:** Initial totals are reproducible but may overstate consumption because transfers and duplicates remain included and may differ from net cost because refunds are not subtracted. Material rule changes require an explicit semantics version rather than silent reinterpretation.

## ADR-012: Institution CSV support uses explicit versioned adapters

- **Status:** Accepted
- **Context:** Citi, Chase, Bank of America, and different products expose incompatible headers, dates, debit/credit columns, and sign conventions. Guessing a format can silently invert household financial data.
- **Decision:** Normalize raw institution exports through small versioned adapters selected by exact reviewed header signatures at explicitly declared CSV row locations. Require exactly one match, preserve adapter/version provenance, let adapters explicitly count reviewed non-transaction metadata rows, keep canonical imports backward compatible, and reject unknown or ambiguous layouts before persistence. Real statements remain local and repository fixtures are independently sanitized synthetic examples.
- **Consequences:** HIC-026 provides provenance and strict contracts; HIC-027 provides registry selection, canonical compatibility, and shared atomic persistence; HIC-028 through HIC-030 implement strict Citi, Chase, and Bank of America adapters. The Bank of America format demonstrates why header location and beginning-balance metadata must be explicit rather than heuristically inferred. Each additional institution/product layout still requires private sample review, sanitized fixtures, tests, and maintenance when formats change. Direct bank connections remain out of scope.

## ADR-013: Duplicate evidence is non-destructive review state

- **Status:** Accepted
- **Context:** Overlapping CSV exports can create repeated source transactions, but same-day and same-amount records may also be legitimate. Silently deleting or excluding records would damage provenance and trust.
- **Decision:** Store a dedicated `DuplicateCandidate` for one canonically ordered transaction pair. Retain both source transactions, deterministic fingerprint evidence, a required reason, and unresolved/confirmed/dismissed review state. HIC-010 adds versioned full-normalized-field matching across prior imports, links each new match to one deterministic older representative, and serializes PostgreSQL import detection with a transaction advisory lock. Duplicate state does not alter analytics eligibility.
- **Consequences:** Exact overlapping imports are now flagged atomically without rejecting or deleting rows; repeated rows solely within one upload are not flagged; full-field equality deliberately favors false negatives over broad false positives. Any later analytics exclusion policy must decide which record is authoritative, preserve both import paths, and explicitly revise the analytics contract.
## ADR-014: Categorization separates catalog, rule, and current provenance

- **Status:** Accepted
- **Context:** A transaction text category alone cannot distinguish a bank-supplied label, deterministic rule result, or user correction, and unordered overlapping rules would make reruns unpredictable.
- **Decision:** Store reusable categories, explicit rule definitions, and at most one current structured assignment per transaction. Represent imported, rule, and manual sources separately; require rule provenance only for rule assignments; order rules by lower priority then UUID ascending; cascade transaction deletion but restrict deletion of referenced categories and rules. Keep `Transaction.category` as the analytics label and require HIC-012 to implement atomic synchronization.
- **Consequences:** Manual choices are structurally identifiable for future override protection and rule ordering is stable. The schema does not retain assignment history or enforce the cross-table rule/category equality invariant; HIC-012 enforces those service-level rules and documents replacement behavior.
## ADR-015: Categorization is explicit, deterministic, and manual-first

- **Status:** Accepted
- **Context:** Automatically applying opaque or unstable categorization during import would couple source ingestion to household policy, obscure conflicts, and risk overwriting user corrections.
- **Decision:** Normalize rule and transaction whitespace; use explicit exact, prefix, or contains operations; evaluate active rules by lower priority then UUID ascending; report every multi-rule match as a conflict; and apply changes only through an explicit all-transactions or import-batch operation. Never overwrite manual assignments. Atomically synchronize structured assignments and the existing `Transaction.category` analytics label.
- **Consequences:** Repeated application is reproducible and idempotent, conflicts are inspectable, and user choices remain authoritative. Imports do not automatically run rules; there is no background recategorization or assignment history; stale rule-owned labels are cleared when no active rule matches, while untouched imported labels remain.

## ADR-016: The initial web client uses React, TypeScript, and Vite

- **Status:** Accepted
- **Context:** The application needs an accessible browser interface for existing APIs without moving financial rules into the client or adopting a large framework before navigation and deployment requirements are known.
- **Decision:** Use React with strict TypeScript and Vite for the initial web client. Keep dependencies small, use a configurable same-origin API base URL with a local /api development proxy, and keep PostgreSQL-backed APIs authoritative. Use Vitest, Testing Library, jest-axe, ESLint, and the TypeScript build for automated validation. Do not persist transaction data in browser storage.
- **Consequences:** The shell can grow incrementally and remains independently testable. Feature routing, server-side rendering, a client state library, authentication, and production reverse-proxy deployment are deferred until their requirements are concrete.

## ADR-017: AI orchestration uses an immutable read-only analytics allowlist

- **Status:** Accepted
- **Context:** Natural-language explanations need a narrow boundary to verified financial results before any model provider is introduced. Dynamic function dispatch, direct database access, inferred date ranges, or mutation tools would undermine the deterministic core.
- **Decision:** Define four provider-independent analytics contracts with closed names, immutable registry/executor mappings, Pydantic argument and result schemas, explicit inclusive date ranges, and `read_only` access. Reuse the same deterministic result builders as HTTP routes. Reject unsupported names and ambiguous/invalid arguments before analytics execution.
- **Consequences:** An orchestrator can receive JSON schemas and exact typed evidence without calculating totals or accessing SQL. The exact phrase `last month` is resolved deterministically from the configured household timezone; other relative dates require explicit resolution or clarification. Imports, categorization, duplicate review, and all other mutations remain outside the AI tool boundary.

## ADR-018: Private documents use PostgreSQL metadata and opaque private blobs

- **Status:** Accepted
- **Context:** Household PDFs are sensitive, untrusted, and larger than relational metadata. The application has no authentication or multi-household ownership boundary yet, and a database/filesystem write cannot be one atomic transaction.
- **Decision:** Initially accept only bounded, unencrypted, structurally validated PDFs in a local/private single-household deployment. Store lifecycle and provenance metadata in PostgreSQL and immutable original bytes behind a private filesystem adapter using server-generated opaque keys. Use streaming SHA-256 plus size for duplicate detection, compensating state transitions for upload, deny-first idempotent deletion, infrastructure encryption, explicit retention/backup limits, and a planned non-null household backfill in HIC-025. Follow [`DOCUMENT_STORAGE_ARCHITECTURE.md`](DOCUMENT_STORAGE_ARCHITECTURE.md).
- **Consequences:** HIC-020 implements a narrow auditable storage boundary without AI, and HIC-021 layers versioned extraction on that immutable boundary. Remote/multi-user document use remains unsupported before authentication. Object storage, OCR, additional formats, application-level encryption, automated staging reconciliation, and automated backups remain separate decisions.

## ADR-019: Native PDF extraction is versioned and page-provenanced

- **Status:** Accepted
- **Context:** Searchable document text must remain traceable to an immutable source, while extraction libraries, layout behavior, and failure recovery can change independently of original storage.
- **Decision:** Verify the stored PDF size and SHA-256 before each actual run; identify a run by document, extractor name/version, and source checksum; persist explicit processing/completed/failed state; atomically store bounded whole-page spans with one-based page/section numbers, Unicode character offsets, and text checksums; return completed runs idempotently; and retry failed or stale runs without overwriting a different extractor version. Use deterministic native `pypdf` extraction first and exclude OCR.
- **Consequences:** Extracted text can be reviewed and later chunked without losing source lineage, originals remain unchanged, and failures expose safe codes rather than content. Version `1` offsets refer to normalized extracted page text rather than PDF bytes or visual bounding boxes. Synchronous requests, whole-page granularity, OCR, layout coordinates, background recovery, and search remain later work. See [`DOCUMENT_EXTRACTION.md`](DOCUMENT_EXTRACTION.md).

## ADR-020: Lexical retrieval precedes embeddings

- **Status:** Accepted
- **Context:** Document answers need measurable, provenance-preserving retrieval, while embeddings add another processor, cost, privacy boundary, versioning burden, and failure mode. The current deployment also lacks authenticated household ownership.
- **Decision:** First create deterministic bounded character chunks from versioned extraction spans and search them with PostgreSQL `simple` full-text search, a GIN expression index, OR term matching, `ts_rank_cd`, stable tie-breakers, and complete source provenance. Limit scope to the trusted local single household. Add embeddings only if versioned synthetic evaluation demonstrates a material lexical-retrieval gap, and never use document retrieval for exact financial calculations.
- **Consequences:** Retrieval is inexpensive, inspectable, reproducible, and useful before any model integration. Lexical search may miss synonyms and semantic paraphrases; evaluation will identify those gaps. Scores rank one query only and are not probabilities. HIC-023 still requires context limits, prompt-injection defenses, citations, uncertainty behavior, and provider evaluation; HIC-025 now supplies authoritative household filters. See [`DOCUMENT_RETRIEVAL.md`](DOCUMENT_RETRIEVAL.md).

## ADR-021: Secure mode uses application-managed credentials and opaque sessions

- **Status:** Accepted and implemented by HIC-025
- **Context:** The current service implicitly trusts every client that can reach it. Remote or multi-household use requires identity, revocation, CSRF protection, and a database-enforced ownership boundary without introducing a mandatory external identity processor for a personal self-hosted application.
- **Decision:** Keep the current runtime explicitly local-only until HIC-025 is complete. The first secure mode uses an interactively bootstrapped household owner, Argon2id password hashing, opaque 256-bit session tokens stored only as SHA-256 digests, host-only Secure/HttpOnly/SameSite cookies, server-side expiry/revocation/rotation, synchronizer CSRF plus Origin/Host validation, and a server-derived request principal. Add non-null `household_id` to every sensitive table, enforce parent/child consistency and household-scoped uniqueness, and require household predicates across APIs, analytics, tools, blobs, extraction, and retrieval. Secure mode uses same-origin TLS and fails startup rather than enabling an auth bypass.
- **Rejected alternatives:** Network location or UUID secrecy, shared API keys/Basic Auth, JWTs in browser storage or stateless cookies, client-supplied household IDs, runtime development bypass headers, and mandatory OIDC are rejected for the first release. Passkeys, OIDC, MFA, email recovery, invitations, and multi-household membership are deferred.
- **Consequences:** The design preserves self-hosted privacy and straightforward revocation. HIC-025 implements the cross-cutting migration and authorization boundary. Password recovery requires an interactive local operator command, and phishing-resistant authentication is not yet provided. Public exposure still requires same-origin TLS and deployment hardening. See [`AUTHENTICATION_ARCHITECTURE.md`](AUTHENTICATION_ARCHITECTURE.md) and [`SECURITY_THREAT_MODEL.md`](SECURITY_THREAT_MODEL.md).

## ADR-022: PDF links are allowlisted by action and URI scheme

- **Status:** Accepted
- **Context:** Word processors commonly export ordinary hyperlinks as `/Link` annotations containing `/URI` actions. Rejecting every annotation action blocks benign household documents, while accepting arbitrary PDF actions would permit JavaScript, file launches, form submission, embedded content, or automatic behavior.
- **Decision:** Accept only well-formed `/Link` `/URI` actions using `http`, `https`, or `mailto`, with bounded length and no control characters. Continue rejecting all automatic/additional actions, forms, JavaScript, embedded files, file attachments, non-URI link actions, unsafe schemes, and malformed URLs before persistence. Preserve the immutable original; do not execute or rewrite links server-side.
- **Consequences:** Common exported letters become compatible without broadening the executable-content boundary. Link destinations are still untrusted user content and may be unsafe to visit; future rendering should preserve browser warnings and must not auto-follow links. Synthetic tests define the security contract, while private compatibility samples remain ignored and never enter repository history.

## ADR-023: OCR is local, page-selective, and derivative-only

- **Status:** Accepted
- **Context:** Image-only household PDFs need searchable text, but cloud OCR would add recurring cost and an external sensitive-data boundary. Replacing native extraction for every PDF would add latency and may degrade reliable embedded text.
- **Decision:** Use OCRmyPDF with Tesseract inside the API container. Run native `pypdf` extraction first and invoke OCR only when at least one page has no native non-whitespace text. Use `--skip-text`, a configured language and timeout, private temporary input/output files, and the existing text-size limit. Persist only normalized page spans and versioned extractor provenance; never replace the immutable original or retain the OCR-generated PDF.
- **Consequences:** Scanned printed documents become searchable without per-page service fees or external processing. OCR remains synchronous and CPU-intensive, output quality depends on scan and language quality, handwriting and layout coordinates are not guaranteed, and production concurrency controls remain future work.

## ADR-024: Structured facts are conservative, provenanced, and user-authoritative

- **Status:** Accepted
- **Context:** Expiration tracking and document retrieval need values more precise than a broad document type, but household records use varied layouts and incorrect dates or identifiers can be harmful.
- **Decision:** Extract only a small allowlist of explicitly labeled facts using versioned deterministic rules over persisted page spans. Reject ambiguous numeric, invalid, and conflicting dates. Store page/extraction/rule/confidence provenance without raw evidence text. Treat every user value or explicit clear as authoritative across re-extraction. Derive expiration state from a caller-supplied date rather than server-local time.
- **Consequences:** Facts are inspectable, reproducible, OCR-compatible, and correctable without an external model. Coverage is intentionally lower than probabilistic extraction; layouts without recognized labels remain blank. Notifications and retention actions require a separate design.

## ADR-025: Initial expiration reminders are opt-in and in-app only

- **Status:** Accepted
- **Context:** Structured expiration dates are useful only if surfaced before action is due, but external delivery adds credentials, privacy boundaries, retries, scheduling, and delivery guarantees.
- **Decision:** Store at most one household-owned configuration per document, require explicit enablement, and support only an `in_app` channel. Calculate the current date in the configured household timezone. Tie acknowledgement to the exact expiration date so renewal reactivates the reminder; use an explicit calendar date for snooze. Do not add a worker or external delivery integration.
- **Consequences:** The application provides deterministic, duplicate-free attention state without new processors or secrets. Users must open the application to see it; email, Slack, push, escalation, and delivery guarantees remain separate tasks.
