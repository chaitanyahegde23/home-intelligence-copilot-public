# Deterministic document retrieval

HIC-022 provides a local, single-household lexical retrieval baseline over completed PDF text
extractions. It is deterministic infrastructure, not an AI answer system.

## Chunk contract

`PUT /documents/{document_id}/chunks` builds the current `deterministic_chars:1` chunk set from
the newest completed extraction. Each nonempty chunk:

- belongs to exactly one document, extraction, and text span;
- retains one-based page and section numbers;
- stores Unicode character offsets relative to its source span and the exact text at those offsets;
- stores a UTF-8 SHA-256 checksum;
- is at most `DOCUMENT_CHUNK_MAX_CHARS` characters; and
- receives a stable one-based order across page, section, and span order.

Whitespace boundaries are preferred without exceeding the configured maximum. A single long token
is split at the maximum. Repeating a build with the same extractor, chunker, text, and limit returns
the same stored records. A changed limit rebuilds only that document's current chunker-version set.

## Query contract

`GET /documents/search?q=<query>&limit=<1..50>` normalizes whitespace, lowercases ASCII
alphanumeric terms, removes duplicate and documented question/stop words, and rejects a query with
no searchable terms. PostgreSQL uses the `simple` text-search configuration and OR semantics across
the remaining terms. A GIN expression index supports matching; `ts_rank_cd` supplies relevance.

Results are ordered by descending relevance, then document ID, page, chunk order, and chunk ID.
Scores are rounded to six decimal places and are useful only for ordering results from the same
query; they are not probabilities or stable measures across queries. `result_count` is the bounded
number returned, not the total possible match count.

Each result includes document ID, safe original filename, source-document checksum, extraction and
chunker versions, chunk ID and checksum, page/section, character offsets, exact chunk text, and
relevance score. This is sufficient to verify provenance but does not constitute a rendered citation.

## Security boundary

Every document, extraction, span, and chunk now has non-null household ownership. In secure mode,
the server-derived principal drives a global SQLAlchemy household predicate and cross-household
writes/relationships are denied. Local mode retains the deterministic bootstrap household and is
still limited to a trusted local/private host.

Extracted text and search results are sensitive. Do not log them or place real content in source
control. HIC-023 may send only bounded retrieved context to the configured provider after applying
the trust controls in [`DOCUMENT_ANSWERS.md`](DOCUMENT_ANSWERS.md). Uploaded document text remains
untrusted data and never becomes application instruction.

## Evaluation and exclusions

The committed JSON evaluation fixture contains only invented documents and queries. Tests cover
chunk boundaries, idempotent rebuilds, provenance, PostgreSQL index metadata, source ranking,
no-result behavior, local-scope enforcement, deletion cascades, and migration reversibility/drift.
SQLite supplies a deterministic test-only fallback; production retrieval is PostgreSQL full-text
search.

The retrieval layer itself does not add embeddings, pgvector, semantic retrieval, reranking, OCR,
or cross-household retrieval. HIC-023 consumes it through a separate cited-answer boundary.
