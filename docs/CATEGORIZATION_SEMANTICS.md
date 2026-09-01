# Categorization semantics

Version: `1.0`

This document defines the persistence contract delivered by HIC-011 and the deterministic application behavior delivered by HIC-012.

## Category catalog

A `Category` is a reusable household classification with a unique, nonblank name, optional nonblank description, active flag, UUID, and timezone-aware timestamps. Deactivation preserves references and history. Category deletion is restricted while rules or assignments reference it.

Category names are unique exactly as stored. Case-insensitive uniqueness, aliases, hierarchy, rename propagation, and a seeded default catalog are not part of this milestone.

## Deterministic rules

A `CategorizationRule` targets one category and declares:

- a field: `description` or `merchant_name`;
- a match operation: `exact`, `prefix`, or `contains`;
- a required nonblank pattern;
- explicit case sensitivity;
- a non-negative integer priority; and
- an active flag.

Lower priority numbers take precedence. Equal priorities are ordered by rule UUID ascending, so evaluation never depends on database insertion order. Active rules whose categories are also active participate in application; inactive rules and categories do not.

Rule deletion is restricted while an assignment cites it. Multiple overlapping rules are allowed because deterministic precedence resolves their evaluation order; application responses expose every multi-rule match as a conflict.

## Current category assignment

A `TransactionCategoryAssignment` stores at most one current structured assignment per transaction. It references a category and records one source:

- `imported`: a category supplied by a reviewed source adapter;
- `rule`: a deterministic rule result and therefore requires `rule_id`;
- `manual`: a user decision and therefore prohibits `rule_id`.

Imported and manual assignments also prohibit `rule_id`. The database and Pydantic schema both enforce this source/rule invariant. Deleting a transaction cascades to its assignment. Deleting a referenced category or rule is restricted.

Manual provenance is structurally distinguishable and automatic application protects it during recategorization. There is no assignment-history ledger; replacing the current assignment is an explicit service operation.

## Deterministic matching and application

Matching collapses leading, trailing, and repeated internal whitespace in both the transaction value and rule pattern. Case-insensitive rules use Unicode `casefold`; case-sensitive rules preserve case. `exact`, `prefix`, and `contains` then operate on the normalized description or merchant name. A missing merchant never matches a merchant rule.

`POST /categorization/apply` evaluates all transactions or one explicitly selected import batch. It locks the selected transaction rows, loads active rules in precedence order, and performs one atomic unit of work. The response reconciles examined transactions into categorized, unmatched, and manual-preserved counts. If multiple rules match, the first rule wins and the response lists every matching rule ID as a visible conflict. Repeating an application with unchanged inputs is idempotent and reports no updates.

Automatic application never overwrites a manual assignment. A matching rule creates or updates a rule assignment and synchronizes `Transaction.category` to the selected category name. If a transaction's prior structured assignment was rule-owned but no active rule now matches, that assignment and its service-owned category label are removed. A transaction with no structured rule assignment keeps any imported text category when no rule matches.

Application is explicit rather than automatic during CSV import. This keeps import persistence and categorization policy separately observable; a caller may apply rules after reviewing or configuring them.

## Manual assignment and synchronization

`PUT /transactions/{transaction_id}/category-assignment` creates or replaces the current assignment with manual provenance and atomically updates `Transaction.category`. Inactive categories cannot be assigned manually. Automatic reruns preserve the manual assignment.

Renaming a category synchronizes the denormalized label of every transaction with a structured assignment to it. Moving a rule to another category synchronizes every assignment produced by that rule. These operations preserve the cross-table invariant that a rule assignment's category is the category targeted by its rule.

`Transaction.category` remains the effective denormalized label used by analytics version `1.0`. HIC-012 does not backfill existing category strings into assignment rows or silently replace unmatched imported labels.
## Explicit exclusions

The current milestone does not include automatic categorization during import, deletion APIs, a default category catalog, merchant enrichment, fuzzy/probabilistic or AI classification, background jobs, analytics semantic changes, or historical assignment audit records.
