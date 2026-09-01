# Home Intelligence Copilot frontend

React and TypeScript client for the import-to-insight, document, and controlled Copilot workflows: API health, CSV upload/results, import history/detail, filtered transaction browsing, deterministic analytics, private PDF lifecycle/search controls, and inspectable AI explanations.

```powershell
npm ci
Copy-Item .env.example .env.local
npm run dev
```

The Vite development server runs at `http://localhost:5173` and proxies `/api` to FastAPI at `http://localhost:8000`. `VITE_MAX_UPLOAD_SIZE_BYTES` defaults to 5 MiB and `VITE_MAX_DOCUMENT_SIZE_BYTES` defaults to 20 MiB for early client guidance; FastAPI remains authoritative. Use only synthetic CSV and PDF files in development and tests.

Transaction, import-history, and analytics filters are persisted in the URL query string. Opening a saved URL restores valid filters, pagination offsets, selected import detail, and complete analytics date ranges. All financial calculations come from FastAPI; the client formats exact string values without recalculating them.

The Documents section uploads PDFs, automatically extracts and indexes native or locally OCRed text, searches indexed passages with filename/page provenance, opens authorized originals, and confirms deletion inline. PDF rendering, cloud OCR, embeddings, and guaranteed handwriting/layout understanding remain unavailable.

The Copilot section keeps Spending analytics and Household documents as explicit modes. Analytics answers expose the allowlisted tool arguments/results; document answers expose exact excerpts plus page and checksum provenance. The client does not save question history. Set `AI_ENABLED=true` and configure `OPENAI_API_KEY` only in the backend `.env` to use model-backed explanations.

Validation:

```powershell
npm test
npm run lint
npm run typecheck
npm run build
npm audit --audit-level=high
```
