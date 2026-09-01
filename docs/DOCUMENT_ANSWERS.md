# Cited document answers

HIC-023 adds `POST /ai/document-questions`, a household-scoped cited-answer endpoint over the
existing PostgreSQL lexical retrieval baseline. It is optional and returns 503 when AI is disabled.

## Trust and grounding contract

The application retrieves at most five current `deterministic_chars:1` chunks before any provider
call. Recognized instruction-like sentences are removed from provider context, and the remaining
source text is explicitly labeled untrusted data. The provider receives no database or mutation
tool. Strict structured output requires atomic claim objects with one or more source IDs.

Application code—not the model—renders citation markers and returns citation objects containing the
document/chunk IDs, safe filename, page and section, exact offsets, source and chunk checksums, and
the exact indexed excerpt. Unknown, repeated, or fabricated citations fail closed. Every rendered
claim has a citation, and numeric claims must occur in the cited excerpts.

No retrieval result returns an explicit `no_results` response without calling the provider.
Conflicting answers must cite at least two documents and explicitly state the conflict. Questions
for transaction totals or spending comparisons return `analytics_required`; structured financial
answers continue through deterministic analytics.

## Evaluation and current limits

Run the versioned, synthetic release suite from `backend/`:

```powershell
.\.venv\Scripts\python.exe scripts\run_rag_evaluation.py --output rag-evaluation-report.json
```

The suite covers supported evidence, conflicting sources, source prompt injection, missing
evidence, and structured-analytics routing. It uses an in-memory database and invented documents.
Generated reports are ignored by Git.

Lexical retrieval passed the committed relevance cases, so HIC-023 does not add embeddings,
pgvector, reranking, OCR, or semantic search. Runtime checks prove citation identity, provenance,
and numeric grounding; semantic completeness remains model-dependent and must be monitored with the
versioned suite. Never add real household content to fixtures or reports.
