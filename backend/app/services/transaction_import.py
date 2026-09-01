from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models import ImportBatch, ImportStatus, Transaction
from app.schemas.import_adapter import (
    AccountLabel,
    AdapterIdentity,
    AdapterNormalizationResult,
    AdapterRowError,
    AmbiguousAdapterDetection,
    MatchedAdapterDetection,
    UnsupportedAdapterDetection,
)
from app.schemas.transaction_import import RowValidationError, TransactionImportResponse
from app.services.csv_reader import CsvReadError, read_csv_document
from app.services.duplicate_detection import (
    acquire_import_detection_lock,
    build_duplicate_candidates,
    load_possible_matches,
)
from app.services.import_adapter import AdapterRegistry

ALLOWED_CONTENT_TYPES = {
    "application/csv",
    "application/vnd.ms-excel",
    "text/csv",
}


class UnsupportedCsvFileError(ValueError):
    """Raised when an upload is not identified as a CSV file."""


class UploadTooLargeError(ValueError):
    """Raised when an upload exceeds the configured byte limit."""


class InvalidCsvDocumentError(ValueError):
    """Raised when CSV bytes cannot be parsed into a document."""


class UnsupportedCsvFormatError(ValueError):
    """Raised when no registered adapter matches the exact header signature."""


class AmbiguousCsvFormatError(ValueError):
    """Raised when more than one registered adapter matches the header signature."""


class AdapterContractError(RuntimeError):
    """Raised when a selected adapter violates the normalization contract."""


async def import_transaction_csv(
    *,
    upload: UploadFile,
    session: Session,
    max_upload_size_bytes: int,
    registry: AdapterRegistry,
    account_label: AccountLabel | None = None,
) -> TransactionImportResponse:
    filename = validate_upload(upload)
    content = await read_bounded_upload(upload, max_upload_size_bytes)

    try:
        document = read_csv_document(content)
    except CsvReadError as error:
        raise InvalidCsvDocumentError(str(error)) from error

    selection = registry.select(document)
    detection = selection.detection
    document = selection.document
    if isinstance(detection, UnsupportedAdapterDetection):
        raise UnsupportedCsvFormatError(detection.message)
    if isinstance(detection, AmbiguousAdapterDetection):
        raise AmbiguousCsvFormatError(detection.message)
    if not isinstance(detection, MatchedAdapterDetection):
        raise AdapterContractError("Registry returned an unknown detection result")

    adapter = registry.get(detection.adapter)
    normalized = adapter.normalize(document, account_label=account_label)
    validate_adapter_result(
        normalized,
        expected_adapter=detection.adapter,
        total_rows=len(document.rows),
    )

    total_rows = len(document.rows) - normalized.ignored_row_count
    imported_rows = len(normalized.rows)
    rejected_rows = total_rows - imported_rows
    errors = [to_response_error(error) for error in normalized.errors]
    status = determine_status(total_rows, imported_rows, rejected_rows, normalized.errors)

    duplicate_candidates_created = 0
    with session.begin():
        acquire_import_detection_lock(session)
        existing_transactions = load_possible_matches(session, normalized.rows)
        batch = ImportBatch(
            filename=filename,
            adapter_name=normalized.adapter.name,
            adapter_version=normalized.adapter.version,
            account_label=normalized.account_label,
            status=ImportStatus.PROCESSING,
            row_count=total_rows,
            imported_count=imported_rows,
            rejected_count=rejected_rows,
        )
        session.add(batch)
        new_transactions: list[Transaction] = []
        for row in normalized.rows:
            transaction = Transaction(
                id=uuid4(),
                transaction_date=row.transaction_date,
                posted_date=row.posted_date,
                description=row.description,
                amount=row.amount,
                account_name=row.account_name,
                merchant_name=row.merchant_name,
                transaction_type=row.transaction_type,
                category=row.category,
                source_file=filename,
            )
            batch.transactions.append(transaction)
            new_transactions.append(transaction)
        duplicate_candidates = build_duplicate_candidates(
            new_transactions=new_transactions,
            existing_transactions=existing_transactions,
        )
        session.add_all(duplicate_candidates)
        duplicate_candidates_created = len(duplicate_candidates)
        batch.status = status
        session.flush()
        batch_id = batch.id

    return TransactionImportResponse(
        import_batch_id=batch_id,
        filename=filename,
        adapter_name=normalized.adapter.name,
        adapter_version=normalized.adapter.version,
        account_label=normalized.account_label,
        status=status,
        total_rows=total_rows,
        imported_rows=imported_rows,
        rejected_rows=rejected_rows,
        duplicate_candidates_created=duplicate_candidates_created,
        errors=errors,
    )


def validate_adapter_result(
    result: AdapterNormalizationResult,
    *,
    expected_adapter: AdapterIdentity,
    total_rows: int,
) -> None:
    if result.adapter != expected_adapter:
        raise AdapterContractError("Adapter result identity does not match the selected adapter")
    if result.ignored_row_count > total_rows:
        raise AdapterContractError("Adapter ignored more rows than the source document")
    importable_rows = total_rows - result.ignored_row_count
    if len(result.rows) > importable_rows:
        raise AdapterContractError("Adapter returned more rows than the importable document")


def to_response_error(error: AdapterRowError) -> RowValidationError:
    return RowValidationError(
        row_number=error.row_number,
        field=error.field,
        message=error.message,
    )


def validate_upload(upload: UploadFile) -> str:
    original_filename = upload.filename or ""
    filename = PurePosixPath(original_filename.replace("\\", "/")).name.strip()
    content_type = (upload.content_type or "").split(";", maxsplit=1)[0].lower()

    if not filename or not filename.lower().endswith(".csv"):
        raise UnsupportedCsvFileError("Only .csv files are supported")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedCsvFileError("Only CSV content types are supported")
    if len(filename) > 512:
        raise UnsupportedCsvFileError("CSV filename must be 512 characters or fewer")
    return filename


async def read_bounded_upload(upload: UploadFile, max_size_bytes: int) -> bytes:
    content = bytearray()
    while chunk := await upload.read(64 * 1024):
        content.extend(chunk)
        if len(content) > max_size_bytes:
            raise UploadTooLargeError(
                f"CSV file exceeds the configured {max_size_bytes}-byte limit"
            )
    return bytes(content)


def determine_status(
    total_rows: int,
    imported_rows: int,
    rejected_rows: int,
    errors: list[AdapterRowError],
) -> ImportStatus:
    if errors and imported_rows == 0:
        return ImportStatus.FAILED
    if total_rows > 0 and rejected_rows == 0:
        return ImportStatus.COMPLETED
    if imported_rows > 0 and rejected_rows > 0:
        return ImportStatus.COMPLETED_WITH_ERRORS
    return ImportStatus.FAILED
