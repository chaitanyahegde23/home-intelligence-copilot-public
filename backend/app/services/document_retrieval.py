from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, literal_column, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.sql import Select

from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_extraction import (
    DocumentExtraction,
    DocumentExtractionStatus,
    DocumentTextSpan,
)
from app.schemas.document_retrieval import (
    DocumentChunkBuildResponse,
    DocumentChunkRead,
    DocumentSearchResponse,
    DocumentSearchResult,
    RetrievalScope,
)
from app.services.document_chunker import DeterministicCharacterChunker, TextChunk

SEARCH_CONFIG = "simple"
SCORE_QUANTUM = Decimal("0.000001")
TERM_PATTERN = re.compile(r"[a-z0-9]+")
QUERY_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "did",
        "do",
        "does",
        "for",
        "how",
        "in",
        "is",
        "many",
        "much",
        "my",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
    }
)


class DocumentRetrievalNotFoundError(LookupError):
    pass


class DocumentRetrievalValidationError(ValueError):
    pass


class UnsupportedRetrievalScopeError(PermissionError):
    pass


class DocumentRetrievalPersistenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExpectedChunk:
    text_span_id: UUID
    chunk_index: int
    page_number: int
    section_number: int
    start_offset: int
    end_offset: int
    text: str
    text_sha256: str


def build_document_chunks(
    *,
    session: Session,
    document_id: UUID,
    chunker: DeterministicCharacterChunker,
    max_chars: int,
) -> DocumentChunkBuildResponse:
    extraction = session.scalar(
        select(DocumentExtraction)
        .join(Document)
        .where(
            Document.id == document_id,
            Document.status == DocumentStatus.STORED,
            DocumentExtraction.status == DocumentExtractionStatus.COMPLETED,
        )
        .options(selectinload(DocumentExtraction.spans))
        .order_by(DocumentExtraction.created_at.desc(), DocumentExtraction.id.desc())
        .limit(1)
    )
    if extraction is None:
        raise DocumentRetrievalNotFoundError("completed document extraction not found")

    expected = _expected_chunks(extraction.spans, chunker=chunker, max_chars=max_chars)
    identity = chunker.identity
    existing = list(
        session.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.chunker_name == identity.name,
                DocumentChunk.chunker_version == identity.version,
            )
            .order_by(DocumentChunk.chunk_index)
        )
    )
    if _chunks_match(existing, expected, extraction.id):
        return _build_response(
            document_id, extraction.id, identity.name, identity.version, existing
        )

    session.execute(
        delete(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.chunker_name == identity.name,
            DocumentChunk.chunker_version == identity.version,
        )
    )
    for expected_chunk in expected:
        session.add(
            DocumentChunk(
                document_id=document_id,
                extraction_id=extraction.id,
                text_span_id=expected_chunk.text_span_id,
                chunker_name=identity.name,
                chunker_version=identity.version,
                chunk_index=expected_chunk.chunk_index,
                page_number=expected_chunk.page_number,
                section_number=expected_chunk.section_number,
                start_offset=expected_chunk.start_offset,
                end_offset=expected_chunk.end_offset,
                text=expected_chunk.text,
                text_sha256=expected_chunk.text_sha256,
            )
        )
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise DocumentRetrievalPersistenceError("document chunks could not be persisted") from exc

    stored = list(
        session.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.extraction_id == extraction.id,
                DocumentChunk.chunker_name == identity.name,
                DocumentChunk.chunker_version == identity.version,
            )
            .order_by(DocumentChunk.chunk_index)
        )
    )
    return _build_response(document_id, extraction.id, identity.name, identity.version, stored)


def search_document_chunks(
    *,
    session: Session,
    query: str,
    limit: int,
    scope: RetrievalScope,
    chunker: DeterministicCharacterChunker,
    document_id: UUID | None = None,
) -> DocumentSearchResponse:
    if scope is not RetrievalScope.LOCAL_SINGLE_HOUSEHOLD:
        raise UnsupportedRetrievalScopeError("only local single-household retrieval is available")
    normalized_query = " ".join(query.split())
    terms = _query_terms(normalized_query)
    if not terms:
        raise DocumentRetrievalValidationError("query has no searchable terms")

    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        ranked = _search_postgresql(
            session, terms=terms, limit=limit, chunker=chunker, document_id=document_id
        )
    else:
        ranked = _search_fallback(
            session, terms=terms, limit=limit, chunker=chunker, document_id=document_id
        )

    results = [_search_result(chunk, score) for chunk, score in ranked]
    return DocumentSearchResponse(
        query=normalized_query,
        terms=list(terms),
        scope=RetrievalScope.LOCAL_SINGLE_HOUSEHOLD,
        result_count=len(results),
        limit=limit,
        results=results,
    )


def _expected_chunks(
    spans: list[DocumentTextSpan],
    *,
    chunker: DeterministicCharacterChunker,
    max_chars: int,
) -> tuple[ExpectedChunk, ...]:
    expected: list[ExpectedChunk] = []
    chunk_index = 1
    for span in sorted(spans, key=lambda item: (item.page_number, item.section_number, item.id)):
        for piece in chunker.chunk(span.text, max_chars=max_chars):
            expected.append(_expected_chunk(span, piece, chunk_index))
            chunk_index += 1
    return tuple(expected)


def _expected_chunk(
    span: DocumentTextSpan,
    piece: TextChunk,
    chunk_index: int,
) -> ExpectedChunk:
    text_sha256 = hashlib.sha256(piece.text.encode("utf-8")).hexdigest()
    return ExpectedChunk(
        text_span_id=span.id,
        chunk_index=chunk_index,
        page_number=span.page_number,
        section_number=span.section_number,
        start_offset=span.start_offset + piece.start_offset,
        end_offset=span.start_offset + piece.end_offset,
        text=piece.text,
        text_sha256=text_sha256,
    )


def _chunks_match(
    existing: list[DocumentChunk],
    expected: tuple[ExpectedChunk, ...],
    extraction_id: UUID,
) -> bool:
    if len(existing) != len(expected):
        return False
    return all(
        chunk.extraction_id == extraction_id
        and chunk.text_span_id == wanted.text_span_id
        and chunk.chunk_index == wanted.chunk_index
        and chunk.page_number == wanted.page_number
        and chunk.section_number == wanted.section_number
        and chunk.start_offset == wanted.start_offset
        and chunk.end_offset == wanted.end_offset
        and chunk.text == wanted.text
        and chunk.text_sha256 == wanted.text_sha256
        for chunk, wanted in zip(existing, expected, strict=True)
    )


def _build_response(
    document_id: UUID,
    extraction_id: UUID,
    chunker_name: str,
    chunker_version: str,
    chunks: list[DocumentChunk],
) -> DocumentChunkBuildResponse:
    return DocumentChunkBuildResponse(
        document_id=document_id,
        extraction_id=extraction_id,
        chunker_name=chunker_name,
        chunker_version=chunker_version,
        chunk_count=len(chunks),
        chunks=[DocumentChunkRead.model_validate(chunk) for chunk in chunks],
    )


def _query_terms(query: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            term
            for term in TERM_PATTERN.findall(query.casefold())
            if len(term) > 1 and term not in QUERY_STOP_WORDS
        )
    )


def _base_search_statement(
    chunker: DeterministicCharacterChunker,
) -> Select[tuple[DocumentChunk]]:
    identity = chunker.identity
    return (
        select(DocumentChunk)
        .join(DocumentChunk.document)
        .join(DocumentChunk.extraction)
        .where(
            Document.status == DocumentStatus.STORED,
            DocumentExtraction.status == DocumentExtractionStatus.COMPLETED,
            DocumentChunk.chunker_name == identity.name,
            DocumentChunk.chunker_version == identity.version,
        )
        .options(
            joinedload(DocumentChunk.document),
            joinedload(DocumentChunk.extraction),
        )
    )


def _search_postgresql(
    session: Session,
    *,
    terms: tuple[str, ...],
    limit: int,
    chunker: DeterministicCharacterChunker,
    document_id: UUID | None,
) -> list[tuple[DocumentChunk, Decimal]]:
    vector = func.to_tsvector(literal_column("'simple'"), DocumentChunk.text)
    tsquery = func.to_tsquery(literal_column("'simple'"), " | ".join(terms))
    rank = func.ts_rank_cd(vector, tsquery, 32)
    statement = _base_search_statement(chunker).add_columns(rank.label("relevance"))
    if document_id is not None:
        statement = statement.where(DocumentChunk.document_id == document_id)
    statement = (
        statement.where(vector.op("@@")(tsquery))
        .order_by(
            rank.desc(),
            DocumentChunk.document_id,
            DocumentChunk.page_number,
            DocumentChunk.chunk_index,
            DocumentChunk.id,
        )
        .limit(limit)
    )
    return [
        (cast(DocumentChunk, row[0]), _score(row[1])) for row in session.execute(statement).unique()
    ]


def _search_fallback(
    session: Session,
    *,
    terms: tuple[str, ...],
    limit: int,
    chunker: DeterministicCharacterChunker,
    document_id: UUID | None,
) -> list[tuple[DocumentChunk, Decimal]]:
    statement = _base_search_statement(chunker)
    if document_id is not None:
        statement = statement.where(DocumentChunk.document_id == document_id)
    chunks = list(session.scalars(statement))
    ranked: list[tuple[DocumentChunk, Decimal]] = []
    for chunk in chunks:
        lowered = chunk.text.casefold()
        occurrences = [lowered.count(term) for term in terms]
        matched = sum(count > 0 for count in occurrences)
        if matched == 0:
            continue
        score = Decimal(matched) + (Decimal(sum(occurrences)) / Decimal("1000"))
        ranked.append((chunk, _score(score)))
    ranked.sort(
        key=lambda item: (
            -item[1],
            str(item[0].document_id),
            item[0].page_number,
            item[0].chunk_index,
            str(item[0].id),
        )
    )
    return ranked[:limit]


def _score(value: object) -> Decimal:
    return Decimal(str(value)).quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP)


def _search_result(chunk: DocumentChunk, score: Decimal) -> DocumentSearchResult:
    return DocumentSearchResult(
        **DocumentChunkRead.model_validate(chunk).model_dump(),
        original_filename=chunk.document.original_filename,
        document_sha256=chunk.document.sha256,
        extractor_name=chunk.extraction.extractor_name,
        extractor_version=chunk.extraction.extractor_version,
        relevance_score=score,
    )


@lru_cache
def get_document_chunker() -> DeterministicCharacterChunker:
    return DeterministicCharacterChunker()
