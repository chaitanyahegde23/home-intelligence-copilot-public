# Document Text Extraction Contract

## Scope and deployment boundary

HIC-021 adds deterministic native-text extraction for the bounded PDFs accepted by HIC-020, and
HIC-046 adds an optional local OCR fallback for pages with no native text. It uses HIC-025
authenticated non-null household ownership and request-scoped enforcement. Local mode remains
limited to a trusted local/private deployment. Extracted text is sensitive household data and must
not be logged, committed, placed in issue attachments, or exposed through a public deployment.

OCR runs inside the API container through OCRmyPDF and Tesseract. It adds no cloud OCR, external
document processor, handwriting guarantee, layout coordinates, background queue, or new API.

## Extractor identity and source integrity

The current adapter is `pypdf_native_ocr` version `1`. It first uses the existing normalized
`pypdf_native` version `2` behavior. If every page contains native non-whitespace text, OCR is not
started. If any page is empty, OCRmyPDF processes a private temporary copy with `--skip-text`, so
native-text pages remain native and empty pages receive a Tesseract text layer. The OCR output is
read into spans and discarded; the immutable original stored by HIC-020 is never rewritten.

Before extraction, the service streams the complete original and requires its byte size and SHA-256
to match the `Document` provenance record. A mismatch fails closed and stores only the code
`source_integrity_mismatch`.

Extractor name, extractor version, document ID, and source-document checksum identify one
versioned run. A completed run with the same identity is returned without reading or extracting
the PDF again. A later extractor version creates a separate derivative and never overwrites an
older version.

## Text and location provenance

The current adapter creates one text span per PDF page:

- `page_number` is one-based and maps to the original PDF page.
- `section_number` is one-based and is `1` for the current whole-page span.
- `start_offset` is `0` and `end_offset` is the number of Python Unicode code points in the
  extracted page text.
- `text_sha256` hashes the exact UTF-8 representation returned by the API and stored in
  PostgreSQL.
- CRLF and bare carriage returns from the extractor are normalized to LF, and database-unsafe
  Unicode control characters are removed while LF and tab are preserved, before hashing and
  persistence. Historical native-only runs remain unchanged.

These offsets locate text inside the versioned extracted page representation; they are not PDF
byte offsets or visual bounding boxes. HIC-022 now chunks these spans while retaining extraction,
page, section, and character-offset provenance. A future layout-aware extractor must use a new
version and may add finer spans without mutating version `1` results.

The chunk and search contract is documented in [`DOCUMENT_RETRIEVAL.md`](DOCUMENT_RETRIEVAL.md).

## Processing and retry states

Each run is exactly one of:

- `processing`: extraction started; no completion time, failure code, or committed spans.
- `completed`: all spans committed atomically with a completion time and no failure code.
- `failed`: no spans, a completion time, and one safe machine-readable failure code.

`PUT /documents/{document_id}/extraction` starts extraction, retries a failed run, or returns an
already completed run idempotently. A recent `processing` run returns HTTP 409. A processing run
older than `DOCUMENT_EXTRACTION_STALE_SECONDS` may be retried; the default is 300 seconds. The
operation is synchronous in this milestone, so the caller must keep the request open.

Failures retain no exception message or raw content. Current codes are:

- `storage_unavailable`
- `source_integrity_mismatch`
- `extraction_failed`
- `extracted_text_too_large`
- `persistence_failed`

`GET /documents/{document_id}/extraction` returns the newest run and its spans, including failed
or processing state. Deleting the parent document cascades to every extraction and span after the
original is removed; the existing privacy-safe deletion audit retains no extracted text.

## Limits and operational behavior

`MAX_DOCUMENT_TEXT_CHARS` limits total extracted Unicode code points per run and defaults to
2,000,000. The backend setting is authoritative. Exceeding it returns HTTP 422, records
`extracted_text_too_large`, and commits no spans. Storage, integrity, extractor, or persistence
failures return HTTP 503; their safe state remains inspectable through the GET endpoint.

`DOCUMENT_OCR_ENABLED` defaults to `true`. Disabling it selects the historical native-only adapter.
`DOCUMENT_OCR_LANGUAGE` defaults to `eng` and accepts installed Tesseract language identifiers
joined with `+`; invalid command-like values are rejected by configuration validation.
`DOCUMENT_OCR_TIMEOUT_SECONDS` defaults to 120 and is bounded from 1 through 900 seconds. Timeout,
missing-engine, and nonzero OCR exits fail closed as `extraction_failed` without persisting OCR
diagnostics or document content. OCR is synchronous and CPU-intensive; concurrent-work and queue
limits remain future operational hardening.

PostgreSQL stores extracted text because it is a searchable derivative with relational
provenance. Operators must use encrypted-at-rest storage, encrypted transport outside loopback,
restricted database access, and recovery sets that keep metadata, blobs, and derivatives
consistent. The application does not yet automate backup, staging cleanup, extraction recovery,
or derivative reconciliation.
