# Deterministic Transaction Analytics Semantics

## Status and purpose

- **Status:** Accepted for analytics semantics version `1.0`.
- **Applies to:** HIC-005 through HIC-008.
- **Implementation status:** HIC-005 through HIC-008 are implemented and tested.
- **Does not implement:** Categorization, transfer detection, duplicate detection, or AI behavior.

This document is normative. Analytics implementations and tests must follow these rules. A future change to a material rule requires a new documented semantics version; an implementation must not silently reinterpret historical results.

## Source records and eligibility

Analytics operate on persisted `Transaction` rows. Each row retains its `ImportBatch` provenance.

- Valid rows from `completed` and `completed_with_errors` batches are eligible.
- A batch's counters are not substituted for transaction records during calculations.
- A transaction is not excluded merely because optional account, merchant, category, or transaction-type data is missing.
- Transactions remain eligible even when an associated duplicate candidate is unresolved, confirmed, or dismissed; candidate review is evidence, not an analytics-authoritative exclusion decision.
- Transfer-looking records remain eligible until a reliable transfer classification and exclusion policy exist.
- Failed imports normally contain no transactions because persistence is atomic. If a transaction does exist, analytics follow the persisted row rather than inferring intent from batch status.

These rules favor reproducibility over guesses. Exact duplicate candidates are now detected and reviewable, but totals can still overstate household consumption because version `1.0` does not choose an authoritative record or exclude candidates. Responses and user-facing explanations must retain that limitation until an explicit exclusion policy revises this contract.

## Date semantics

- Analytics use `transaction_date`, not `posted_date`, `created_at`, or `updated_at`.
- `start_date` and `end_date` are both required for spending analytics.
- Both boundaries are inclusive: `start_date <= transaction_date <= end_date`.
- `start_date` must be on or before `end_date`; reversed ranges are invalid.
- Dates are calendar dates without timezone conversion.
- A one-day range is valid.

Using `transaction_date` aligns analytics with the current query API and avoids inconsistent fallback behavior when `posted_date` is absent.

## Amount sign and spending definition

The stored amount uses the source row's sign:

- A negative amount is an outflow.
- A positive amount is an inflow or credit.
- Zero is neutral.

Version `1.0` defines **gross spending** as the positive magnitude of eligible negative amounts:

```text
gross_spending = sum(-amount for each eligible transaction where amount < 0)
```

The returned total is non-negative. `transaction_count` counts only the negative transactions included in that total. Positive and zero amounts do not contribute to the total or count.

The application must use PostgreSQL `NUMERIC` and Python `Decimal` throughout. It must never convert money to `float`. Stored cents are summed exactly; totals are returned with two decimal places and serialized as JSON strings.

## Credits, refunds, income, transfers, and zero amounts

Positive income and credits are excluded from gross spending. A positive refund is also excluded and is not automatically matched to or netted against an earlier purchase because the current data model has no reliable refund linkage.

Consequences:

- Gross spending is not net spending.
- Gross spending is not cash flow.
- A purchase followed by a refund still contributes the purchase's full negative amount.
- A future net-spending metric must have a separate name and contract.

Transfers cannot yet be excluded reliably. The initial CSV format does not populate `transaction_type`, and free-text category or description values are not authoritative. Negative transfers therefore count as gross spending in version `1.0`. This known limitation must be visible in analytics documentation and later user-facing explanations.

Zero amounts are excluded from spending totals and counts.

## Currency and precision

The transaction model does not store a per-row currency. Version `1.0` supports a single assumed household currency:

- Currency code: `USD`.
- Every analytics response includes `currency: "USD"`.
- Mixed-currency imports are unsupported and must not be combined as though they were USD.
- Adding configurable or per-transaction currency requires a schema and semantics revision.

Money values use at most 18 digits with two decimal places. No intermediate monetary rounding is needed because stored amounts are already cent-denominated. If percentages are later returned, calculate them with `Decimal` and round only the displayed percentage to `0.01` percentage points using `ROUND_HALF_UP`; reconciliation uses unrounded monetary totals.

## Filter semantics

- Account and category filters are optional exact, case-sensitive matches.
- Filter text is trimmed; a blank supplied filter is invalid.
- Missing `account_name` does not match an account filter.
- Missing `category` is represented as **Uncategorized** in grouped output.
- Filtering for a real category named `Uncategorized` is distinct from the missing-category bucket. The API contract must use an explicit null/bucket representation rather than silently conflating them.
- Multiple supplied filters combine with logical AND.
- An empty valid result returns `0.00` and a count of `0`, not an error.

## Endpoint calculation rules

### HIC-005: Spending summary

Implemented by `GET /analytics/spending/summary`. It returns semantics version, metric name `gross_spending`, currency, applied filters, exact non-negative `total_spending`, and the count of included negative transactions. The typed contract is `SpendingSummaryResult` in `app.schemas.analytics`; the deterministic SQL aggregation is in `app.services.spending_analytics`.

### HIC-006: Category breakdown

Implemented by `GET /analytics/spending/by-category`. It applies the same eligibility, date, account, and sign rules as the summary and does not accept a category filter because category is the grouping dimension.

- Included negative transactions are grouped by their stored category.
- Each group exposes both `category` and `bucket`. A `NULL` category is `{category: null, bucket: "uncategorized"}`; a real category named `Uncategorized` remains `{category: "Uncategorized", bucket: "category"}`.
- Each category amount is a positive magnitude, and group amounts and counts reconcile exactly to the response totals.
- Groups sort by amount descending. Equal amounts sort by exact real category name ascending, with the uncategorized bucket last.
- Percentages use the unrounded response total as denominator and `Decimal` `ROUND_HALF_UP` to `0.01` percentage points. Independently rounded percentages may sum to `99.99` or `100.01`.
- An empty result returns `0.00`, count `0`, and no groups.

### HIC-007: Period comparison

Implemented by `GET /analytics/spending/compare`. The response includes both period totals and counts, signed absolute and percentage changes, applied filters, and category deltas. Category deltas sort by absolute change magnitude descending, then exact real category name ascending, with the uncategorized bucket last.

- Each period has its own required inclusive start and end dates.
- Apply identical optional filters and version `1.0` rules to both periods.
- `absolute_change = current_total - comparison_total` using signed `Decimal`.
- A positive change means current gross spending is higher.
- A negative change means current gross spending is lower.
- Percentage change is `null` when the comparison total is zero. Otherwise calculate `(absolute_change / comparison_total) * 100` with `Decimal` and `ROUND_HALF_UP` to `0.01` percentage points.
- Category deltas must reconcile exactly to the total absolute change when category detail is returned.

### HIC-008: Large transactions

Implemented by `GET /analytics/spending/large-transactions`. The response returns exact applied filters, total and returned counts, a `has_more` flag, and full transaction records with persisted import-batch adapter provenance. The result `limit` defaults to 50 and must be between 1 and 100.

- A threshold is a required positive `Decimal` monetary magnitude.
- Include an eligible transaction when it is negative and `-amount >= threshold`; the boundary is inclusive.
- Positive and zero transactions never match this gross-outflow query.
- Preserve transaction and import-batch provenance.
- Sort by magnitude descending, then transaction date descending, then UUID descending.
- Bound the result count using the established API limit conventions.

## Synthetic worked example

Assume these synthetic USD transactions and no filters beyond `2026-01-01` through `2026-01-05`:

| Date | Description | Category | Amount | Treatment |
| --- | --- | --- | ---: | --- |
| 2026-01-01 | Example Grocery Store | Groceries | `-82.45` | Included as `82.45` gross spending |
| 2026-01-02 | Example Employer | Income | `2500.00` | Excluded positive inflow |
| 2026-01-03 | Example Grocery Refund | Groceries | `20.00` | Excluded positive refund; not netted |
| 2026-01-04 | Example Rent | Housing | `-1200.00` | Included as `1200.00` gross spending |
| 2026-01-05 | Example Account Transfer | `NULL` | `-500.00` | Included as `500.00`; transfer limitation applies |

Expected results:

- Spending summary: `1782.45`, transaction count `3`, currency `USD`.
- Category breakdown: Housing `1200.00`, Uncategorized `500.00`, Groceries `82.45`; total `1782.45`.
- Period comparison, `2026-01-04`–`2026-01-05` versus `2026-01-01`–`2026-01-03`: `1700.00` versus `82.45`, absolute change `1617.55`.
- Large transactions with threshold `500.00`: Example Rent `1200.00`, then Example Account Transfer `500.00`; the inclusive threshold includes the transfer.

## Explicit limitations and future revision triggers

Version `1.0` does not solve:

- duplicate transaction exclusion;
- transfer identification or exclusion;
- refund-to-purchase matching or net-spending calculations;
- multi-currency storage or conversion;
- configurable sign conventions for bank-specific exports;
- persisted row-level import errors;
- category normalization or manual override provenance.

Implementations must not hide these limitations with merchant-description guesses. Adding duplicate exclusion, categorization, transfer policy, refund linkage, or currency modeling requires an explicit semantics review and, where material, a new version.
