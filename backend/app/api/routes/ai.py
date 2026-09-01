from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.ai import QuestionRequest, QuestionResponse
from app.schemas.document_answers import DocumentQuestionRequest, DocumentQuestionResponse
from app.services.ai_orchestrator import (
    AIOrchestrationError,
    answer_question,
    current_date_in_timezone,
)
from app.services.document_answers import (
    DocumentAnswerError,
    answer_document_question,
)
from app.services.document_chunker import DeterministicCharacterChunker
from app.services.document_retrieval import get_document_chunker
from app.services.openai_provider import (
    AIProvider,
    AIProviderError,
    AIProviderTimeoutError,
    OpenAIResponsesProvider,
)

router = APIRouter(prefix="/ai", tags=["ai"])


def get_ai_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AIProvider | None:
    if not settings.ai_enabled or settings.openai_api_key is None:
        return None
    return OpenAIResponsesProvider(
        api_key=settings.openai_api_key,
        timeout_seconds=settings.openai_timeout_seconds,
    )


@router.post("/questions", response_model=QuestionResponse)
def ask_question(
    request: QuestionRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    provider: Annotated[AIProvider | None, Depends(get_ai_provider)],
) -> QuestionResponse:
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI explanations are disabled",
        )
    try:
        return answer_question(
            session,
            question=request.question,
            provider=provider,
            model=settings.openai_model,
            max_output_tokens=settings.openai_max_output_tokens,
            current_date=current_date_in_timezone(settings.household_timezone),
        )
    except AIProviderTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="AI provider request timed out",
        ) from exc
    except AIProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI provider request failed",
        ) from exc
    except AIOrchestrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The question could not be answered safely",
        ) from exc


@router.post("/document-questions", response_model=DocumentQuestionResponse)
def ask_document_question(
    request: DocumentQuestionRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    provider: Annotated[AIProvider | None, Depends(get_ai_provider)],
    chunker: Annotated[DeterministicCharacterChunker, Depends(get_document_chunker)],
) -> DocumentQuestionResponse:
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI explanations are disabled",
        )
    try:
        return answer_document_question(
            session,
            question=request.question,
            document_id=request.document_id,
            provider=provider,
            model=settings.openai_model,
            max_output_tokens=settings.openai_max_output_tokens,
            chunker=chunker,
        )
    except AIProviderTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="AI provider request timed out",
        ) from exc
    except AIProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI provider request failed",
        ) from exc
    except DocumentAnswerError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The document question could not be answered safely",
        ) from exc
