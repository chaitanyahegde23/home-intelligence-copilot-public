# HIC Portfolio and Demo Guide

This guide is for a technical recruiter, CIO, enterprise architect, or senior engineering interviewer. It separates demonstrated implementation from proposed extensions.

## Seven engineering contributions to highlight

### 1. A deterministic control plane around AI

HIC does not ask a model to calculate spending or access the database. Typed services perform the calculations; a provider-independent registry exposes four read-only tools; the orchestrator allows at most one validated call; and application code rejects unsupported numeric claims.

**Interview framing:** “I treated the LLM as an untrusted reasoning and explanation component behind typed contracts, not as the business-logic tier.”

### 2. End-to-end provenance for document answers

The document pipeline preserves identity from original checksum through extraction version, page span, deterministic chunk, retrieval result, and rendered citation. Citation IDs and numeric statements are validated by application code rather than trusted from model output.

**Interview framing:** “A useful enterprise answer needs an evidence chain that is inspectable after the model call.”

### 3. Privacy-aware local document processing

PDFs are validated and stored under opaque keys outside public paths. Native extraction is the fast path; image-only pages use local OCRmyPDF/Tesseract derivatives. File limits, checksums, duplicate handling, staging/compensation, retry states, and derivative-aware deletion make the pipeline operational rather than a proof-of-concept upload.

**Interview framing:** “I made privacy and failure recovery properties of the ingestion architecture, not deployment notes added later.”

### 4. Explicit, auditable financial semantics

The normalized model uses Python `Decimal` and PostgreSQL `NUMERIC`. Versioned CSV adapters isolate institution-specific layouts and sign rules. Exact totals, categories, period comparisons, and thresholds are deterministic and tested for precision, ordering, filters, and rollback.

**Interview framing:** “Models can explain financial results, but only deterministic code is allowed to produce the authoritative number.”

### 5. Evaluation as a release gate

Separate synthetic AI and RAG suites exercise tool routing, arguments, grounding, refusal, clarification, source injection, missing evidence, conflicting evidence, and citation behavior. Fixtures contain invented data, and reports carry component versions without reading the household database.

**Interview framing:** “I evaluated the failure modes created by the architecture rather than optimizing a generic answer-quality score.”

### 6. Household isolation and fail-closed security

The secure mode uses Argon2id credentials, opaque digest-only sessions, CSRF and Origin/Host controls, throttling, redacted audits, and non-null household ownership. The server derives scope from the session; a client or model cannot select a household by passing an ID.

**Interview framing:** “Identity, policy, and data scope are resolved before tools, retrieval, or models run.”

### 7. A reusable asynchronous ingestion boundary

The optional Gmail worker uses OAuth, a sender allowlist, authenticated-sender evidence, attachment constraints, idempotency keys, retries, terminal labels, and redacted history before reusing the same document pipeline as interactive upload.

**Interview framing:** “Email is an adapter into a governed ingestion service, not a second implementation of document processing.”

## 2–3 minute demo walkthrough

Use only the synthetic fixtures in `sample-data/`. Keep Gmail disabled during a public demo unless a dedicated synthetic mailbox is configured. Enable financial features only if time permits.

### 0:00–0:20 — Set the architecture context

**Show:** The README architecture diagram, then the document archive.

**Say:** “HIC is a private household information system. PostgreSQL and typed services remain authoritative. AI is optional and sits behind authorization, retrieval, deterministic tools, and evaluation rather than connecting directly to the database.”

### 0:20–0:55 — Ingest a scanned document

**Show:** Upload `sample-data/synthetic-scanned-warranty.pdf`. Open the resulting document detail.

**Say:** “This synthetic warranty is image-based. The application validates and hashes the original, stores it under an opaque key, performs local OCR, and automatically derives conservative metadata and structured facts. Notice the document type, key date, extraction status, and source provenance.”

### 0:55–1:25 — Organize and retrieve it

**Show:** Add the document to a collection or tag it. Search for the warranty expiration text and open the result.

**Say:** “The archive is not just blob storage. Search returns bounded context with filename and page provenance. Collections and tags are user-managed and remain separate from inferred metadata.”

### 1:25–1:55 — Ask for a cited answer

**Show:** Ask, “When does the synthetic warranty expire?” Open the citation/document link.

**Say:** “The model sees only bounded, untrusted excerpts. It must return structured claims tied to known source IDs. The server validates those IDs, checks numeric grounding, and renders the final citations. Missing or conflicting evidence produces an explicit state rather than an invented answer.”

### 1:55–2:25 — Demonstrate the deterministic/AI boundary

**Show:** If financial features are enabled, import `sample-data/synthetic-transactions.csv`, show a deterministic total, then ask the matching analytics question.

**Say:** “Institution adapters normalize source formats atomically using Decimal. The LLM selects from four read-only tools, but Python and SQL calculate the number. The explanation is returned with the exact validated arguments and tool evidence.”

### 2:25–2:50 — Close on enterprise readiness

**Show:** The validation commands or synthetic evaluation documentation.

**Say:** “The important artifact is the control plane: household scope, strict contracts, provenance, failure states, and repeatable synthetic evaluations. The next step is to add routing and observability without weakening those boundaries.”

## Fast, relevant enhancements

These items are proposed; none is implemented today.

### Enhancement A — Policy-based cross-domain router

Add a small application-owned router in front of the current analytics and document-answer endpoints. It would classify requests into `financial_tool`, `document_retrieval`, `clarification`, or `unsupported`; bind a policy version; and expose the route decision as structured evidence. The LLM would still have no arbitrary SQL, retrieval, or mutation capability.

**Why it matters:** It demonstrates orchestration across specialized capabilities while preserving deterministic authorization and tool boundaries.

**Small deliverable:** Typed route decision schema, deterministic high-confidence rules, bounded model fallback for ambiguous cases, audit record, synthetic routing suite, and a unified question endpoint.

### Enhancement B — Privacy-safe orchestration telemetry

Instrument question and ingestion workflows with OpenTelemetry-compatible spans and a persisted redacted run summary: correlation ID, route, tool, model/prompt/contract versions, latency, token counts, refusal/error class, citation count, and evaluation version. Do not store prompts or document text by default.

**Why it matters:** It makes cost, latency, reliability, and model behavior reviewable by operators without creating a second sensitive-data store.

**Small deliverable:** Trace context middleware, structured step spans, redaction policy, local collector/dashboard profile, tests that secrets and content never enter attributes, and an operator run view.

### Enhancement C — Human approval checkpoints for future actions

Create a generic proposed-action record and approval API before adding any mutation tool. A workflow may propose a bounded action, but only an authenticated owner can approve it; execution uses an idempotency key and records before/after evidence. Start with a harmless synthetic action rather than document deletion or financial mutation.

**Why it matters:** It demonstrates the core enterprise agent pattern of separating reasoning, authorization, execution, and audit.

**Small deliverable:** State machine (`proposed`, `approved`, `rejected`, `executed`, `failed`), policy/expiry fields, optimistic concurrency, idempotent executor, owner UI, and transition/authorization tests.

## Claims to avoid

- Do not describe HIC as multi-agent or autonomous; it currently uses bounded single-tool orchestration.
- Do not claim semantic/vector retrieval; current retrieval is PostgreSQL lexical search.
- Do not claim production-grade multi-tenancy; the implemented security boundary is owner-operated and single-household.
- Do not claim that OCR understands handwriting or every PDF layout.
- Do not show real household documents, statements, credentials, email addresses, hostnames, or infrastructure screenshots.
