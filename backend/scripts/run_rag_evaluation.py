from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.household import LOCAL_PRINCIPAL
from app.db.base import Base
from app.db.household_scope import SESSION_HOUSEHOLD_KEY
from app.evaluations.rag import (
    SyntheticRAGDocument,
    load_rag_evaluation_suite,
    run_rag_evaluation,
)
from app.models import Document, DocumentExtraction, DocumentExtractionStatus, DocumentTextSpan
from app.models.document import DocumentStatus
from app.services.document_answers import (
    DOCUMENT_ANSWER_PROMPT_VERSION,
    answer_document_question,
)
from app.services.document_chunker import DeterministicCharacterChunker
from app.services.document_retrieval import build_document_chunks
from app.services.openai_provider import OpenAIResponsesProvider


def main() -> int:
    arguments = _parse_arguments()
    settings = Settings()
    if settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    suite = load_rag_evaluation_suite(arguments.cases)
    provider = OpenAIResponsesProvider(
        api_key=settings.openai_api_key,
        timeout_seconds=settings.openai_timeout_seconds,
    )
    chunker = DeterministicCharacterChunker()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.info[SESSION_HOUSEHOLD_KEY] = LOCAL_PRINCIPAL.household_id
            for document in suite.documents:
                _seed_document(session, document, chunker)
            report = run_rag_evaluation(
                suite,
                subject=lambda question: answer_document_question(
                    session,
                    question=question,
                    provider=provider,
                    model=settings.openai_model,
                    max_output_tokens=settings.openai_max_output_tokens,
                    chunker=chunker,
                ),
                provider="openai_responses",
                model=settings.openai_model,
                prompt_version=DOCUMENT_ANSWER_PROMPT_VERSION,
            )
    finally:
        engine.dispose()
    rendered = report.model_dump_json(indent=2)
    if arguments.output is None:
        print(rendered)
    else:
        arguments.output.write_text(f"{rendered}\n", encoding="utf-8")
        print(f"Wrote synthetic RAG evaluation report to {arguments.output}")
    return 0 if report.release_passed else 1


def _seed_document(
    session: Session,
    source: SyntheticRAGDocument,
    chunker: DeterministicCharacterChunker,
) -> None:
    digest = hashlib.sha256(source.text.encode()).hexdigest()
    now = datetime.now(UTC)
    document = Document(
        status=DocumentStatus.STORED,
        original_filename=source.filename,
        size_bytes=len(source.text.encode()),
        sha256=digest,
        storage_key=f"objects/synthetic-rag/{digest[:16]}",
    )
    extraction = DocumentExtraction(
        document=document,
        status=DocumentExtractionStatus.COMPLETED,
        extractor_name="synthetic_rag_evaluation",
        extractor_version="1",
        document_sha256=digest,
        started_at=now,
        completed_at=now,
    )
    extraction.spans.append(
        DocumentTextSpan(
            page_number=1,
            section_number=1,
            start_offset=0,
            end_offset=len(source.text),
            text=source.text,
            text_sha256=digest,
        )
    )
    session.add(document)
    session.commit()
    build_document_chunks(
        session=session,
        document_id=document.id,
        chunker=chunker,
        max_chars=1000,
    )


def _parse_arguments() -> argparse.Namespace:
    repository_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Run cited document answers against synthetic RAG cases."
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=repository_root / "sample-data" / "synthetic-rag-evaluation.json",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
