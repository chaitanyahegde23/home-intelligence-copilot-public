# Approved Analytics Tool Contracts

## Status

Version 1 is the provider-independent, read-only boundary between future natural-language orchestration and the deterministic analytics engine. It does not integrate an AI provider or expose a new public endpoint.

The normative financial rules remain in [`ANALYTICS_SEMANTICS.md`](ANALYTICS_SEMANTICS.md). A tool returns existing typed analytics results; it does not reinterpret or recalculate them.

## Allowlist

| Tool name | Arguments | Result | Supported question |
| --- | --- | --- | --- |
| `get_spending_summary` | `SpendingFilters` | `SpendingSummaryResult` | Exact gross spending and included count for one explicit range, with optional exact account/category filters. |
| `get_spending_by_category` | `CategoryBreakdownFilters` | `CategorySpendingResult` | Reconciling category breakdown for one explicit range and optional exact account. |
| `compare_spending_periods` | `PeriodComparisonFilters` | `PeriodComparisonResult` | Exact totals and category changes between two explicit ranges. |
| `list_large_transactions` | `LargeTransactionFilters` | `LargeTransactionResult` | Bounded outflows at or above an explicit Decimal threshold, with transaction/import provenance. |

`APPROVED_ANALYTICS_TOOLS` is the complete allowlist. Names are a closed `StrEnum`, contracts and executors are held in immutable mappings, and dispatch never imports or resolves a function from user/model text.

## Read-only guarantee

Every contract declares `access = "read_only"`. Executors call only the existing select-based analytics services. There are no create, update, delete, import, categorization, duplicate-review, payment, transfer, or arbitrary SQL tools in this boundary.

The database session is supplied by application code. A future orchestrator must not expose that session, a repository object, SQL, filenames, module names, or callable identifiers to the model.

## Ambiguity and validation rules

- Date ranges are required and inclusive. Arguments use explicit ISO `YYYY-MM-DD` dates.
- Relative or incomplete phrases are not tool arguments. The orchestrator deterministically resolves the exact phrase `last month` from the configured household timezone before dispatch; phrases such as `June` or `recently` still require clarification.
- Reversed ranges, missing endpoints, blank exact-match filters, unexpected fields, floats for money, and unsupported tool names fail validation.
- Period comparison requires all four endpoints. The executor does not infer equal-length or previous periods.
- Large-transaction queries require a positive Decimal threshold and retain the existing bounded limit.
- Category breakdown does not accept a category filter because category is its grouping dimension.
- Currency and analytics semantics remain fixed to `USD` and version `1.0` until separately versioned.

## Evidence and result handling

Every result contains the applied filters, semantics version, currency, deterministic values, and included counts. Category and comparison results contain reconciliation fields. Large-transaction results additionally contain transaction IDs and import-batch provenance.

A future AI-generated explanation may summarize these fields, but numeric claims must be copied from the returned result. The model must distinguish verified values from interpretation and must not calculate totals from raw transactions.

## Failure behavior

- Unsupported names raise `UnsupportedAnalyticsToolError` before database access.
- Invalid arguments raise Pydantic `ValidationError` before analytics execution.
- Provider/network failures are outside this contract because HIC-016 has no provider integration.
- No fallback tool, guessed range, or mutation is attempted after failure.
