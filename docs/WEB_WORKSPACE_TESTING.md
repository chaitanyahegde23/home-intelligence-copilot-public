# Web workspace manual testing

Use only the committed synthetic CSV and PDF fixtures. Never upload real household data to a shared, test, or screen-recorded environment.

## Start the application

From the repository root:

```powershell
docker compose up --build -d
docker compose exec api alembic upgrade head
```

From `frontend/` in a second terminal:

```powershell
npm ci
Copy-Item .env.example .env.local
npm run dev
```

Open `http://localhost:5173`. If authentication is `secure`, log in with the local owner account. Local mode opens the workspace directly.

## Primary document flow

1. Use **Documents** to upload `sample-data/synthetic-household-document.pdf`.
2. Confirm one upload automatically stores, extracts, identifies, and indexes the document and clears the selected filename.
3. Upload the same fixture again; confirm the duplicate message links to the existing library record.
4. Confirm the card is automatically named and typed as **Warranty** with subtle confidence provenance. Edit the title/type and confirm the card changes to user-managed provenance; add a synthetic note, filter by type/title, then clear the filters.
5. Search document text for `warranty cost`; confirm results link back to the fixture and exact page.
6. Select **Open original**; confirm the PDF opens through `/api/documents/{id}/content` without a storage path in the URL.
7. Select **Copilot**, choose **Household documents**, and ask `When does the synthetic warranty expire?`.
8. Confirm the answer includes an exact citation excerpt, linked filename, page, section, and expandable technical provenance.
9. Ask `How much did I spend in June?` in document mode; confirm the response redirects financial totals to Spending analytics.
10. Return to **Documents**, select **Delete**, cancel once, then confirm deletion. Confirm the document disappears.

## Analytics Copilot flow

AI requests require `AI_ENABLED=true` and a valid backend-only `OPENAI_API_KEY`; they may consume API credit.

1. Import `sample-data/synthetic-transactions.csv` if no synthetic transactions exist.
2. Choose **Spending analytics** in **Copilot**.
3. Ask `How much did I spend from 2026-01-01 through 2026-01-31?` (adjust dates to the fixture).
4. Confirm controlled emphasis renders without literal `**` markers and the collapsed deterministic evidence exposes the allowlisted tool name, exact arguments, and backend result.
5. Ask `How much did I spend last month?`; confirm the evidence contains the exact previous-calendar-month range for `HOUSEHOLD_TIMEZONE` without asking for dates.
6. Ask a different ambiguous period; confirm clarification appears without deterministic evidence.
7. Confirm switching modes clears the draft question and never silently reuses the other mode's answer.

## Transaction workspace flow

1. Import `sample-data/synthetic-transactions.csv` if the transaction list is empty.
2. Open **Transactions** and confirm spending, income, net, and gross totals appear above the table.
3. Apply a date or account filter and confirm the totals describe every match even when results span more than one page.
4. Create a synthetic category such as `Household test`, assign it from a transaction row, and confirm the row reports a manual assignment.
5. Refresh the page and confirm both the category and filters persist through the backend and URL respectively.
6. Confirm there is no separate Analytics navigation item; use **Copilot** for explanations and the documented analytics endpoints for direct deterministic queries.

## Failure, accessibility, and responsive checks

- Stop the API and confirm health, document, and Copilot failures are understandable; restart it and retry without reloading the page.
- With AI disabled, confirm Copilot reports `AI explanations are disabled` without exposing configuration or credentials.
- Navigate every form, mode, action, details disclosure, and confirmation using Tab, Shift+Tab, Space, and Enter only; verify a visible focus indicator and logical order.
- At approximately 390 CSS pixels wide, confirm navigation wraps, forms become one column, text does not overlap, and horizontal scrolling is limited to data tables.
- At desktop width, confirm document cards, citations, evidence, and long checksums wrap without clipping.
- Check the browser console during primary and failure flows; there should be no uncaught exceptions or React accessibility warnings.

## Automated regression

From `frontend/`:

```powershell
npm test
npm run lint
npm run typecheck
npm run build
npm audit --audit-level=high
```

From `backend/` with PostgreSQL running:

```powershell
alembic upgrade head
pytest
ruff check .
ruff format --check .
mypy app
alembic check
```

## Milestone 11 validation record

Validated on 2026-08-15 using committed synthetic data only:

- Backend: 395 tests passed; Ruff lint and format checks passed; mypy passed for 120 source files; Alembic upgraded/current at `20260809_04` with no drift.
- Frontend: 53 tests passed across 15 files; ESLint, TypeScript, production build, and high-severity dependency audit passed with zero vulnerabilities.
- Integrated test: upload → extraction → indexing → search → exact cited answer → confirmed deletion passed, plus a whole-workspace automated accessibility scan.
- Browser: isolated synthetic API state passed desktop layout, the primary document lifecycle/search path, cancel/confirm deletion, disabled-AI error guidance, a 390 × 844 responsive check, keyboard focus visibility, and console review with zero warning/error entries.
- Cleanup: the temporary browser-QA database and document store were deleted, and the normal Docker API service was restored.

The backend suite reports one upstream Starlette warning about the deprecated `httpx` TestClient integration. It does not fail the suite and contains no application or household data.
