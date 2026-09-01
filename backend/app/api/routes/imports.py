from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.import_adapter import AccountLabel
from app.schemas.transaction_import import TransactionImportResponse
from app.services.import_adapter import AdapterRegistry, get_adapter_registry
from app.services.transaction_import import (
    AmbiguousCsvFormatError,
    InvalidCsvDocumentError,
    UnsupportedCsvFileError,
    UnsupportedCsvFormatError,
    UploadTooLargeError,
    import_transaction_csv,
)

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post(
    "/transactions",
    response_model=TransactionImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_transactions(
    file: Annotated[UploadFile, File()],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[AdapterRegistry, Depends(get_adapter_registry)],
    account_label: Annotated[AccountLabel | None, Form()] = None,
) -> TransactionImportResponse:
    try:
        return await import_transaction_csv(
            upload=file,
            session=session,
            max_upload_size_bytes=settings.max_upload_size_bytes,
            registry=registry,
            account_label=account_label,
        )
    except UnsupportedCsvFileError as error:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(error),
        ) from error
    except UploadTooLargeError as error:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(error),
        ) from error
    except (
        AmbiguousCsvFormatError,
        InvalidCsvDocumentError,
        UnsupportedCsvFormatError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
