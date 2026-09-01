# Home Intelligence Copilot Product Definition

## Product vision

Home Intelligence Copilot is a private, household-centered application that turns scattered financial records and, later, household documents into reliable answers and useful explanations. It should help a person understand what happened, find supporting evidence, and make ordinary household decisions without surrendering accuracy to an AI model.

The product starts with structured transaction data because it supports deterministic, testable calculations. AI is a later explanatory and conversational layer around trusted application tools; it is not the calculator or system of record.

## Intended users

- Individuals or families who want a clearer view of household spending without maintaining complex spreadsheets.
- Privacy-conscious users who prefer a self-hosted or tightly controlled personal application.
- Homeowners and renters who need to organize recurring expenses, bills, repairs, projects, subscriptions, and related records.
- A primary household operator who imports and reviews data; multi-household administration is not an initial requirement.

## Problems the product should solve

- Transaction exports are inconsistent, difficult to inspect, and disconnected from useful summaries.
- It is hard to answer simple questions such as how much was spent in a category or why one period cost more than another.
- Duplicate exports and inconsistent merchant descriptions can undermine confidence in totals.
- Bills, receipts, policies, warranties, and project documents are scattered across folders and inboxes.
- Generic chat tools may produce plausible answers without doing exact calculations or citing household evidence.
- Sensitive household information requires stricter handling than ordinary application data.

## Initial financial-data use cases

The initial product should support:

- Importing a documented canonical CSV transaction format with row-level validation.
- Uploading explicitly reviewed Citi, Chase, and Bank of America CSV layouts through versioned institution adapters, with unsupported layouts rejected rather than guessed.
- Reviewing import history and the outcome of each import.
- Listing and filtering normalized transactions by date, account, category, merchant, and import batch.
- Calculating spending totals for explicit date ranges with `Decimal`-based deterministic code.
- Grouping spending by category, merchant, account, and time period.
- Comparing two periods and identifying the transactions responsible for changes.
- Finding large transactions and likely recurring expenses.
- Detecting likely duplicate transactions before they distort analytics.
- Applying transparent categorization rules that users can inspect and correct.

## Longer-term household-document use cases

Later milestones may support:

- Ingesting bills, receipts, insurance documents, warranties, utility statements, and home-project records.
- Extracting searchable text and structured metadata while preserving the original source.
- Finding clauses, dates, amounts, providers, coverage details, and renewal information.
- Connecting documents to household projects, expenses, vendors, or recurring services.
- Answering natural-language questions with citations to the exact source document and location.
- Comparing current and historical documents, such as policy renewals or utility bills.
- Presenting uncertain extraction or interpretation as uncertain rather than as fact.

## Explicit non-goals

The project does not aim to:

- Provide investment, tax, legal, insurance, lending, or other regulated professional advice.
- Initiate purchases, payments, transfers, account changes, or other autonomous financial actions.
- Connect directly to banks or financial aggregators in the initial milestones.
- Automatically accept every institution or product layout. Only explicitly reviewed, versioned, and tested CSV formats are supported.
- Use an LLM to calculate financial totals from raw transaction text.
- Treat Slack, email, or another third-party chat product as the primary interface.
- Become a multi-tenant financial platform in the near term.
- Commit real financial records, account identifiers, documents, passwords, or tokens to the repository.
- Add document retrieval, embeddings, or RAG before structured financial analytics are tested.

## Privacy and security principles

- Collect and retain only data needed for an explicit household use case.
- Keep secrets in ignored environment files or an appropriate secret store, never in source control.
- Use synthetic data in source, samples, tests, demonstrations, and evaluations.
- Keep real institution statements outside the repository; inspect them locally, extract only structural rules, and create sanitized synthetic fixtures with no member names, account identifiers, merchants, dates, or amounts copied from the source.
- Do not log raw statements, account numbers, document contents, tokens, or credentials.
- Validate file type, size, encoding, shape, and field values before persistence.
- Keep imports atomic so failures do not create unexplained partial records.
- Separate households and enforce authorization before supporting multiple users or remote access.
- Prefer local or private infrastructure where practical and document every external data processor.
- Make deletion, retention, backup, and recovery behavior explicit before storing irreplaceable documents.
- Preserve provenance so a result can be traced to imported records or cited documents.
- Treat prompt injection and malicious document content as untrusted input in future AI features.

## Deterministic results and AI explanations

Financial facts must come from deterministic application code:

1. PostgreSQL stores normalized source records.
2. SQLAlchemy queries select the relevant records.
3. Typed analytics services calculate totals, groupings, comparisons, and flags using exact numeric types.
4. Tests verify those calculations against known synthetic inputs.
5. Structured tool results identify filters, assumptions, and evidence.

An AI model may later:

- Select an approved read-only tool.
- Ask for clarification when a date range or term is ambiguous.
- Summarize a structured analytics result in plain language.
- Explain patterns while distinguishing facts from interpretations.
- Cite the records or documents supporting an answer.

An AI model must not independently calculate totals from raw text, invent missing categories, hide uncertainty, or present an interpretation as a verified result.

## Current product state

As of 2026-09-01, the application has a working backend, PostgreSQL schema, atomic multi-format CSV import, transaction/import APIs, deterministic analytics, duplicate review, categorization, owner authentication and household isolation, Docker development environment, synthetic data, and automated tests. The React client provides protected document, CSV, import, transaction, analytics, and controlled Copilot views. Bounded PDFs can be privately stored, extracted with a local OCR fallback, classified conservatively, organized, chunked with provenance, searched lexically, and answered through an optional controlled model boundary with server-rendered citations and synthetic release gates. An optional allowlisted Gmail worker delivers PDF attachments into the same governed ingestion pipeline. Additional unreviewed bank layouts, non-PDF documents, semantic retrieval, autonomous actions, and broader production operations remain future work.

A provider-independent allowlist exposes the four deterministic analytics capabilities as validated
read-only tool contracts. An optional controlled OpenAI Responses API endpoint now selects at most
one of those tools, executes it through application code, and returns a verified explanation,
clarification, or refusal with authoritative local evidence. AI is disabled by default, has no
database session or mutation tools, and rejects unsupported numeric claims. A versioned synthetic
evaluation gate detects response-kind, tool-selection, argument, numeric-grounding, and safety
regressions without using household data. Household-scoped cited document answers now use bounded
lexical context, strict structured claims, server-rendered exact provenance, and a synthetic RAG
release suite while keeping transaction totals in deterministic analytics.

Private document ingestion, lexical retrieval, and cited answers implement private blob/metadata separation, checksum provenance, compensation, native-first extraction with local OCR for image-only pages, provenance-preserving chunks, ranked search, derivative-aware deletion, bounded model context, and exact citations. They intentionally provide no cloud OCR, guaranteed handwriting understanding, semantic retrieval, or autonomous document actions.

The security threat model and authentication/household-isolation architecture are implemented in
the optional secure mode. Local mode remains a trusted-development convenience. The product is
owner-operated and single-household; multi-tenant SaaS use remains unsupported.
