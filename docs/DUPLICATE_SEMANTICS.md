# Duplicate Transaction Semantics

## Status and scope

- **Status:** Accepted and implemented by HIC-009 and HIC-010.
- **Implemented:** Persistent candidate/review state, versioned exact fingerprinting, cross-import detection, atomic candidate creation, query/review APIs, and import outcome counts.
- **Not implemented:** Fuzzy matching, automatic deletion/merging, or analytics exclusion.

This model records evidence that two source transactions may represent the same real-world event. It never deletes, merges, edits, rejects, or silently excludes either transaction.

## Candidate identity

A `DuplicateCandidate` references two persisted `Transaction` rows:

- `first_transaction_id` is the lower UUID.
- `second_transaction_id` is the higher UUID.
- The IDs must be distinct and remain in canonical order.
- One ordered transaction pair may have at most one candidate row.
- Both foreign keys use `ON DELETE CASCADE`, because a candidate cannot retain valid provenance after either source transaction is deleted.

UUID ordering is an implementation normalization rule, not a claim that the first transaction is older, original, or authoritative.

## Detection evidence and exact-match version 1

- `fingerprint` is a lowercase 64-character SHA-256 hexadecimal digest supplied by the deterministic detector.
- `reason` is the version identifier `exact_normalized_transaction_v1`.
- The unambiguous UTF-8 JSON fingerprint payload contains, in order: the reason/version, `transaction_date`, `posted_date`, normalized `description`, canonical two-decimal `amount`, normalized `account_name`, `merchant_name`, `transaction_type`, and `category`.
- Dates use ISO 8601 calendar-date strings; missing optional values use JSON `null`; positive and negative zero share `0.00`; text remains exact and case-sensitive after adapter whitespace normalization.
- Source filename, import-batch ID, transaction UUID, timestamps, and adapter identity are excluded so the same normalized activity can match across overlapping files.
- A changed fingerprint algorithm must use a new explicit reason/version and must not silently reinterpret existing candidates.

All version-1 fields must match. A changed posted date, transaction date, amount, description, account, merchant, type, or category is not flagged. This intentionally favors false negatives over broad false positives.

## Import-time matching

- Detection compares a new upload only with transactions committed by earlier imports. Identical rows within one upload are retained without candidates.
- Existing transactions are prefetched for the new upload's bounded transaction-date window and grouped by the full normalized identity in application code.
- When more than one older transaction has the same identity, the oldest `created_at`/UUID record is the deterministic representative. Each matching new row receives at most one candidate, bounding candidate creation by imported row count.
- PostgreSQL imports acquire one transaction-scoped advisory lock before reading possible matches. Candidate detection, batch creation, transactions, counts, and final status then commit or roll back as one unit.
- Detection flags evidence only. It never rejects, deletes, edits, merges, or chooses an analytics-authoritative transaction.

## Review states and APIs

A candidate has exactly one state:

- `unresolved`: the default; `resolved_at` must be null.
- `confirmed`: a reviewer accepted that the pair represents a duplicate; `resolved_at` is required.
- `dismissed`: a reviewer determined the pair is not a duplicate; `resolved_at` is required.

`resolution_note` is optional supporting context. `GET /duplicate-candidates` exposes stable bounded pages and optional status/import filters; detail results include both transactions and import provenance. `PATCH /duplicate-candidates/{candidate_id}` records a confirmed or dismissed review. User identity is not stored until authentication and ownership provide a reliable reviewer identity.

## Analytics behavior

HIC-010 does not change analytics. Every persisted transaction remains eligible under analytics semantics version `1.0`, including transactions in unresolved, confirmed, or dismissed candidate pairs. A future exclusion policy must identify the authoritative record, be deterministic and provenance-preserving, revise the analytics contract explicitly, and be separately tested before totals change.

## Non-goals

Duplicate handling does not:

- choose which transaction to retain for analytics;
- delete or merge transactions;
- perform fuzzy, probabilistic, or AI matching;
- compare transactions across households;
- store reviewer identity before authentication exists;
- detect repeated rows solely within one upload.