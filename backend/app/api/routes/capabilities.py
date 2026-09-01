from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.schemas.capabilities import ApplicationCapabilities

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities", response_model=ApplicationCapabilities)
def get_capabilities(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApplicationCapabilities:
    return ApplicationCapabilities(
        document_copilot=settings.ai_enabled,
        financial_features=settings.financial_features_enabled,
    )
