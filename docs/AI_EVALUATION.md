# Synthetic AI evaluation

HIC-018 adds a versioned, deterministic release gate for the controlled analytics explanation
layer. The committed suite at `sample-data/synthetic-ai-evaluation.json` contains only invented
questions and is evaluated against an in-memory database seeded with synthetic transactions.
Real household data must never be added to an evaluation case or report.

## What is graded

Each case declares its expected response kind, exact allowlisted tool, canonical tool arguments,
required answer terms, forbidden answer terms, and whether it is release-critical. The runner
grades response invariants, tool selection, arguments, numeric grounding against authoritative tool
evidence, and answer terms. Provider failures record only the exception type. Reports include the
provider, model, prompt version, tool-contract version, dataset ID, and dataset version.

A release passes only when its configured pass-rate threshold is met and every critical case passes.
The version 1 suite intentionally requires 100%. Human review can supplement the deterministic gate
for clarity and tone but cannot waive grounding failures.

## Run the live synthetic suite

From `backend/`, with `OPENAI_API_KEY` configured in the root `.env`:

```powershell
.\.venv\Scripts\python.exe scripts\run_ai_evaluation.py --output ai-evaluation-report.json
```

The command exits zero on release success and nonzero on failure. It sends only synthetic questions
and minimized synthetic tool results to the configured provider. Run it when the prompt, model, tool
contract, provider adapter, or evaluation dataset changes. Generated reports are ignored by Git.
