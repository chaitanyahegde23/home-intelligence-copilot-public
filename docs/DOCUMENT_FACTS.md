# Structured document facts

HIC-047 extracts a small, deterministic set of useful facts from persisted PDF text: expiration date, document date, issuer, reference number, and document subtype. Native text and local OCR use the same rules.

## Trust contract

- Dates are accepted only from an explicit nearby label and an unambiguous ISO or named-month value. Ambiguous numeric dates such as `06/07/2028`, invalid dates, and conflicting values are ignored.
- Every automatic fact records the extraction run, rule/version, evidence code, confidence, and one-based source page. Raw evidence text is not copied into provenance.
- User corrections and explicit clears are authoritative. Re-extraction may refresh automatic facts but never replaces a user-managed value.
- Fact rows are household-scoped and deleted with their document. Reference values are private document metadata and must not be logged.

## API

- `GET /documents/{document_id}/facts` lists current facts.
- `PATCH /documents/{document_id}/facts/{fact_type}` sets a user value or `{ "is_cleared": true }`.
- `GET /documents/expirations?as_of=2028-06-01&within_days=90` returns expired, due-today, and upcoming documents. The caller supplies `as_of`, so status and day counts are reproducible and timezone-independent.

The document library displays non-cleared facts and lets a user correct them through **Edit details**. This milestone tracks expiration state only; scheduled reminders, notifications, retention policy, and model-inferred facts remain separate work.
