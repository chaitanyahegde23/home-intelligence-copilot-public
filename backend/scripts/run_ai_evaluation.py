from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.household import LOCAL_PRINCIPAL
from app.db.base import Base
from app.db.household_scope import SESSION_HOUSEHOLD_KEY
from app.evaluations.ai import load_ai_evaluation_suite, run_ai_evaluation
from app.models import ImportBatch, Transaction
from app.services.ai_orchestrator import AI_PROMPT_VERSION, answer_question
from app.services.openai_provider import OpenAIResponsesProvider


def main() -> int:
    arguments = _parse_arguments()
    settings = Settings()
    if settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    suite = load_ai_evaluation_suite(arguments.cases)
    provider = OpenAIResponsesProvider(
        api_key=settings.openai_api_key,
        timeout_seconds=settings.openai_timeout_seconds,
    )
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.info[SESSION_HOUSEHOLD_KEY] = LOCAL_PRINCIPAL.household_id
            _seed_synthetic_transactions(session)
            report = run_ai_evaluation(
                suite,
                subject=lambda question: answer_question(
                    session,
                    question=question,
                    provider=provider,
                    model=settings.openai_model,
                    max_output_tokens=settings.openai_max_output_tokens,
                ),
                provider="openai_responses",
                model=settings.openai_model,
                prompt_version=AI_PROMPT_VERSION,
            )
    finally:
        engine.dispose()

    rendered = report.model_dump_json(indent=2)
    if arguments.output is None:
        print(rendered)
    else:
        arguments.output.write_text(f"{rendered}\n", encoding="utf-8")
        print(f"Wrote synthetic AI evaluation report to {arguments.output}")
    return 0 if report.release_passed else 1


def _parse_arguments() -> argparse.Namespace:
    repository_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Run the bounded OpenAI orchestrator against synthetic evaluation cases."
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=repository_root / "sample-data" / "synthetic-ai-evaluation.json",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _seed_synthetic_transactions(session: Session) -> None:
    batch = ImportBatch(
        filename="synthetic-ai-evaluation.csv",
        adapter_name="synthetic_evaluation",
        adapter_version="1",
        account_label="Synthetic Checking",
        row_count=3,
        imported_count=3,
    )
    session.add_all(
        [
            Transaction(
                id=UUID(int=201),
                import_batch=batch,
                transaction_date=date(2026, 1, 5),
                description="Synthetic Grocery",
                merchant_name="Synthetic Market",
                amount=Decimal("-100.00"),
                account_name="Synthetic Checking",
                category="Groceries",
                source_file=batch.filename,
            ),
            Transaction(
                id=UUID(int=202),
                import_batch=batch,
                transaction_date=date(2026, 1, 10),
                description="Synthetic Housing",
                merchant_name="Synthetic Housing Provider",
                amount=Decimal("-250.45"),
                account_name="Synthetic Checking",
                category="Housing",
                source_file=batch.filename,
            ),
            Transaction(
                id=UUID(int=203),
                import_batch=batch,
                transaction_date=date(2025, 12, 15),
                description="Synthetic Prior Grocery",
                merchant_name="Synthetic Market",
                amount=Decimal("-50.00"),
                account_name="Synthetic Checking",
                category="Groceries",
                source_file=batch.filename,
            ),
        ]
    )
    session.commit()


if __name__ == "__main__":
    raise SystemExit(main())
