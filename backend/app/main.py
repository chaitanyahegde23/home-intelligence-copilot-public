from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    expose_schema = settings.app_env != "production" or settings.api_docs_enabled
    application = FastAPI(
        title=settings.app_name,
        root_path=settings.api_root_path,
        docs_url="/docs" if expose_schema else None,
        redoc_url="/redoc" if expose_schema else None,
        openapi_url="/openapi.json" if expose_schema else None,
    )
    application.dependency_overrides[get_settings] = lambda: settings

    @application.middleware("http")
    async def enforce_feature_flags(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not settings.financial_features_enabled and _is_financial_path(request.url.path):
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"detail": "financial features are disabled"},
            )
        return await call_next(request)

    application.include_router(api_router)
    return application


def _is_financial_path(path: str) -> bool:
    prefixes = (
        "/imports",
        "/transactions",
        "/analytics",
        "/categories",
        "/categorization",
        "/duplicate-candidates",
    )
    return path == "/ai/questions" or path.startswith(prefixes)


app = create_app()
