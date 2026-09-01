# AGENTS.md

## Project

Home Intelligence Copilot is a personal AI application for understanding household financial data and, later, household documents, bills, projects, utilities, travel expenses, and other home-related information.

## Current Milestone

Build an MVP that imports transaction CSV files, stores normalized transactions in PostgreSQL, and provides deterministic spending analytics.

The initial milestone is focused only on transaction ingestion and analytics. Do not add document retrieval, Slack, email, calendar, or autonomous financial actions unless explicitly requested.

## Technology

* Python 3.12
* FastAPI
* PostgreSQL
* SQLAlchemy 2
* Alembic
* Pydantic
* Pytest
* Ruff
* mypy
* Docker Compose

## Architecture Principles

* Keep API route handlers thin.
* Keep business logic in service modules.
* Keep database logic separate from business logic.
* Use dependency injection where it improves testability.
* Prefer small, focused modules over large files.
* Prefer deterministic calculations over LLM-generated calculations.
* Design features so that AI is optional around the core analytics engine.
* Add clear error handling and useful validation messages.

## Engineering Rules

* Use `Decimal` for monetary values; never use `float`.
* Store monetary values using an appropriate PostgreSQL `NUMERIC` type.
* Add type hints to application code.
* Add tests for parsing, validation, calculations, and API behavior.
* Never commit secrets.
* Never commit real financial or household data.
* Use synthetic data in examples and tests.
* Do not log account numbers, raw statements, access tokens, or secrets.
* Keep commits and pull requests small and focused.
* Update documentation when commands or behavior change.
* Run formatting, linting, type checking, and tests before completing a task.

## AI Rules

* The LLM must not calculate financial totals directly from raw transaction text.
* Financial calculations must be performed by deterministic application code.
* LLM responses must be grounded in results returned by approved application tools.
* AI-generated answers must distinguish verified results from interpretations.
* Do not provide investment, tax, legal, insurance, or lending advice.
* Do not make autonomous purchases, transfers, payments, or account changes.

## Initial Data Models

### ImportBatch

* id
* filename
* status
* row_count
* imported_count
* rejected_count
* created_at
* updated_at

### Transaction

* id
* import_batch_id
* account_name
* transaction_date
* posted_date
* description
* merchant_name
* amount
* transaction_type
* category
* source_file
* created_at
* updated_at

## Suggested Commands

* Start services: `docker compose up --build`
* Stop services: `docker compose down`
* Run tests: `pytest`
* Run linting: `ruff check .`
* Run formatting check: `ruff format --check .`
* Run type checking: `mypy .`
* Run migrations: `alembic upgrade head`

Update these commands if the implemented repository structure requires different paths.

## Current Scope Exclusions

Unless explicitly requested, do not add:

* OpenAI integration
* Slack integration
* Email integration
* Calendar integration
* Bank-account connections
* Plaid or similar aggregators
* PDF parsing
* OCR
* RAG
* Embeddings
* pgvector
* Authentication
* Multiple households
* Investment recommendations
* Autonomous financial actions
