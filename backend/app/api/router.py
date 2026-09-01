from fastapi import APIRouter, Depends

from app.api.dependencies.auth import enforce_csrf, require_request_principal
from app.api.routes.ai import router as ai_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.auth import router as auth_router
from app.api.routes.capabilities import router as capabilities_router
from app.api.routes.categorization import router as categorization_router
from app.api.routes.document_retrieval import router as document_retrieval_router
from app.api.routes.documents import router as documents_router
from app.api.routes.duplicate_candidates import router as duplicate_candidates_router
from app.api.routes.gmail_ingestions import router as gmail_ingestions_router
from app.api.routes.health import router as health_router
from app.api.routes.import_history import router as import_history_router
from app.api.routes.imports import router as imports_router
from app.api.routes.transactions import router as transactions_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(capabilities_router)
protected_router = APIRouter(
    dependencies=[Depends(require_request_principal), Depends(enforce_csrf)]
)
protected_router.include_router(document_retrieval_router)
protected_router.include_router(documents_router)
protected_router.include_router(gmail_ingestions_router)
protected_router.include_router(imports_router)
protected_router.include_router(import_history_router)
protected_router.include_router(transactions_router)
protected_router.include_router(analytics_router)
protected_router.include_router(ai_router)
protected_router.include_router(categorization_router)
protected_router.include_router(duplicate_candidates_router)
api_router.include_router(protected_router)
