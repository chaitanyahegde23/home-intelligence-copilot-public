import hashlib
from contextlib import suppress
from pathlib import PurePosixPath, PureWindowsPath
from typing import BinaryIO
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import UploadFile
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import DictionaryObject
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.document import (
    PDF_MEDIA_TYPE,
    PRIVATE_FILESYSTEM_BACKEND,
    Document,
    DocumentDeletionAudit,
    DocumentSource,
    DocumentStatus,
)
from app.schemas.document import DocumentRead
from app.services.document_storage import DocumentStorageError, PrivateDocumentStorage

READ_CHUNK_SIZE = 64 * 1024
SAFE_EXTERNAL_LINK_SCHEMES = frozenset({"http", "https", "mailto"})
MAX_EXTERNAL_LINK_LENGTH = 2048


class DocumentIngestionError(ValueError):
    """Base error for safe user-facing document ingestion failures."""


class UnsupportedDocumentError(DocumentIngestionError):
    pass


class DocumentTooLargeError(DocumentIngestionError):
    pass


class InvalidPdfError(DocumentIngestionError):
    pass


class DuplicateDocumentError(DocumentIngestionError):
    def __init__(self, existing_document_id: UUID) -> None:
        super().__init__("document already exists")
        self.existing_document_id = existing_document_id


class DocumentNotFoundError(LookupError):
    pass


class DocumentPersistenceError(RuntimeError):
    pass


class DocumentDeletionError(RuntimeError):
    pass


class DocumentMetadataPersistenceError(RuntimeError):
    pass


async def store_pdf_document(
    *,
    upload: UploadFile,
    session: Session,
    storage: PrivateDocumentStorage,
    max_size_bytes: int,
    max_pages: int,
    source: DocumentSource = DocumentSource.USER_UPLOAD,
) -> DocumentRead:
    filename = _validate_upload_metadata(upload)
    staging_key = storage.new_staging_key()
    final_key: str | None = None
    promoted = False

    try:
        size_bytes, sha256 = await _stage_upload(
            upload=upload,
            storage=storage,
            staging_key=staging_key,
            max_size_bytes=max_size_bytes,
        )
        with storage.open_reader(staging_key) as stream:
            _validate_pdf(stream, max_pages=max_pages)

        existing_id = session.scalar(
            select(Document.id).where(
                Document.sha256 == sha256,
                Document.size_bytes == size_bytes,
            )
        )
        if existing_id is not None:
            raise DuplicateDocumentError(existing_id)

        document_id = uuid4()
        final_key = storage.final_key(document_id)
        document = Document(
            id=document_id,
            status=DocumentStatus.PENDING,
            original_filename=filename,
            media_type=PDF_MEDIA_TYPE,
            size_bytes=size_bytes,
            sha256=sha256,
            storage_backend=PRIVATE_FILESYSTEM_BACKEND,
            storage_key=final_key,
            source=source,
        )
        session.add(document)
        session.flush()

        storage.promote(staging_key, final_key)
        promoted = True
        document.status = DocumentStatus.STORED
        session.commit()
        return DocumentRead.model_validate(document)
    except DuplicateDocumentError:
        session.rollback()
        _best_effort_delete(storage, staging_key)
        if promoted and final_key is not None:
            _best_effort_delete(storage, final_key)
        raise
    except IntegrityError as exc:
        session.rollback()
        _best_effort_delete(storage, staging_key)
        if promoted and final_key is not None:
            _best_effort_delete(storage, final_key)
        existing_id = _find_duplicate_id(
            session, sha256=locals().get("sha256"), size_bytes=locals().get("size_bytes")
        )
        if existing_id is not None:
            raise DuplicateDocumentError(existing_id) from exc
        raise DocumentPersistenceError("document persistence failed") from exc
    except (UnsupportedDocumentError, DocumentTooLargeError, InvalidPdfError):
        session.rollback()
        _best_effort_delete(storage, staging_key)
        if promoted and final_key is not None:
            _best_effort_delete(storage, final_key)
        raise
    except (DocumentStorageError, SQLAlchemyError, OSError) as exc:
        session.rollback()
        _best_effort_delete(storage, staging_key)
        if promoted and final_key is not None:
            _best_effort_delete(storage, final_key)
        raise DocumentPersistenceError("document storage operation failed") from exc


def get_stored_document(session: Session, document_id: UUID) -> DocumentRead:
    document = session.get(Document, document_id)
    if document is None or document.status is not DocumentStatus.STORED:
        raise DocumentNotFoundError("document not found")
    return DocumentRead.model_validate(document)


def update_document_metadata(
    session: Session,
    *,
    document_id: UUID,
    title: str | None,
    document_type: str | None,
    notes: str | None,
    fields_set: set[str],
    collection_name: str | None = None,
    tags: list[str] | None = None,
) -> DocumentRead:
    try:
        with session.begin():
            document = session.scalar(
                select(Document)
                .where(Document.id == document_id, Document.status == DocumentStatus.STORED)
                .with_for_update()
            )
            if document is None:
                raise DocumentNotFoundError("document not found")
            if "title" in fields_set:
                document.title = title
                document.title_source = "user"
            if "document_type" in fields_set:
                document.document_type = document_type
                document.document_type_source = "user"
            if "notes" in fields_set:
                document.notes = notes
            if "collection_name" in fields_set:
                document.collection_name = collection_name
            if "tags" in fields_set:
                document.tags = tags or []
            session.flush()
        return DocumentRead.model_validate(document)
    except DocumentNotFoundError:
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise DocumentMetadataPersistenceError("document metadata update failed") from exc


def read_stored_document(
    session: Session,
    storage: PrivateDocumentStorage,
    document_id: UUID,
) -> tuple[DocumentRead, bytes]:
    document = session.get(Document, document_id)
    if document is None or document.status is not DocumentStatus.STORED:
        raise DocumentNotFoundError("document not found")
    try:
        with storage.open_reader(document.storage_key) as stream:
            content = stream.read()
    except DocumentStorageError as exc:
        raise DocumentPersistenceError("document storage operation failed") from exc
    return DocumentRead.model_validate(document), content


def delete_document(
    *,
    session: Session,
    storage: PrivateDocumentStorage,
    document_id: UUID,
) -> None:
    existing_audit = session.scalar(
        select(DocumentDeletionAudit.id).where(DocumentDeletionAudit.document_id == document_id)
    )
    if existing_audit is not None:
        return

    document = session.get(Document, document_id)
    if document is None:
        raise DocumentNotFoundError("document not found")

    if document.status is not DocumentStatus.DELETING:
        document.status = DocumentStatus.DELETING
        try:
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise DocumentDeletionError("document deletion could not start") from exc

    try:
        storage.delete(document.storage_key)
    except DocumentStorageError as exc:
        raise DocumentDeletionError("document storage deletion failed") from exc

    session.add(DocumentDeletionAudit(document_id=document.id))
    session.delete(document)
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise DocumentDeletionError("document deletion could not finish") from exc


def _validate_upload_metadata(upload: UploadFile) -> str:
    raw_filename = upload.filename or ""
    filename = " ".join(raw_filename.split())
    if (
        not filename
        or len(filename) > 255
        or "\x00" in filename
        or PurePosixPath(filename).name != filename
        or PureWindowsPath(filename).name != filename
    ):
        raise UnsupportedDocumentError("document filename is invalid")
    if not filename.lower().endswith(".pdf"):
        raise UnsupportedDocumentError("only PDF documents are supported")
    if upload.content_type != PDF_MEDIA_TYPE:
        raise UnsupportedDocumentError("document media type must be application/pdf")
    return filename


async def _stage_upload(
    *,
    upload: UploadFile,
    storage: PrivateDocumentStorage,
    staging_key: str,
    max_size_bytes: int,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    size_bytes = 0
    with storage.open_staging_writer(staging_key) as destination:
        while chunk := await upload.read(READ_CHUNK_SIZE):
            size_bytes += len(chunk)
            if size_bytes > max_size_bytes:
                raise DocumentTooLargeError(
                    f"document exceeds the {max_size_bytes}-byte upload limit"
                )
            digest.update(chunk)
            destination.write(chunk)
    if size_bytes == 0:
        raise InvalidPdfError("PDF document is empty")
    return size_bytes, digest.hexdigest()


def _validate_pdf(stream: BinaryIO, *, max_pages: int) -> None:
    try:
        stream.seek(0)
        if stream.read(5) != b"%PDF-":
            raise InvalidPdfError("PDF signature is invalid")
        stream.seek(0, 2)
        file_size = stream.tell()
        stream.seek(max(0, file_size - 1024))
        tail = stream.read()
        eof_position = tail.rfind(b"%%EOF")
        if eof_position < 0 or tail[eof_position + 5 :].strip():
            raise InvalidPdfError("PDF terminal marker is invalid")
        stream.seek(0)

        reader = PdfReader(stream, strict=True)
        if reader.is_encrypted:
            raise InvalidPdfError("encrypted PDF documents are not supported")
        root = reader.root_object
        if "/AcroForm" in root:
            raise InvalidPdfError("PDF document contains unsupported form fields")
        if any(key in root for key in ("/OpenAction", "/AA")):
            raise InvalidPdfError("PDF document contains unsupported automatic actions")
        names = root.get("/Names")
        if names is not None:
            names_object = names.get_object()
            if "/JavaScript" in names_object:
                raise InvalidPdfError("PDF document contains unsupported JavaScript")
            if "/EmbeddedFiles" in names_object:
                raise InvalidPdfError("PDF document contains unsupported embedded files")
        for page in reader.pages:
            if "/AA" in page:
                raise InvalidPdfError("PDF document contains unsupported automatic page actions")
            annotations = page.get("/Annots")
            if annotations is None:
                continue
            for annotation_reference in annotations:
                annotation = annotation_reference.get_object()
                if not isinstance(annotation, DictionaryObject):
                    raise InvalidPdfError("PDF document contains a malformed annotation")
                _validate_pdf_annotation(annotation)
        page_count = len(reader.pages)
    except InvalidPdfError:
        raise
    except (PdfReadError, OSError, ValueError, TypeError) as exc:
        raise InvalidPdfError("PDF document is malformed") from exc
    if page_count == 0:
        raise InvalidPdfError("PDF document must contain at least one page")
    if page_count > max_pages:
        raise InvalidPdfError(f"PDF document exceeds the {max_pages}-page limit")


def _validate_pdf_annotation(annotation: DictionaryObject) -> None:
    if annotation.get("/Subtype") == "/FileAttachment":
        raise InvalidPdfError("PDF document contains unsupported file attachments")
    if "/AA" in annotation:
        raise InvalidPdfError("PDF document contains unsupported automatic annotation actions")

    action_reference = annotation.get("/A")
    if action_reference is None:
        return
    if annotation.get("/Subtype") != "/Link":
        raise InvalidPdfError("PDF document contains unsupported annotation actions")

    action = action_reference.get_object()
    if action.get("/S") != "/URI":
        raise InvalidPdfError("PDF document contains an unsupported link action")
    uri = action.get("/URI")
    if not _is_safe_external_link(uri):
        raise InvalidPdfError("PDF document contains an unsafe or malformed external link")


def _is_safe_external_link(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > MAX_EXTERNAL_LINK_LENGTH:
        return False
    if value != value.strip() or any(
        character.isspace() or ord(character) == 127 for character in value
    ):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    scheme = parsed.scheme.casefold()
    if scheme not in SAFE_EXTERNAL_LINK_SCHEMES:
        return False
    if scheme in {"http", "https"}:
        return bool(parsed.netloc)
    return bool(parsed.path)


def _find_duplicate_id(
    session: Session,
    *,
    sha256: object,
    size_bytes: object,
) -> UUID | None:
    if not isinstance(sha256, str) or not isinstance(size_bytes, int):
        return None
    return session.scalar(
        select(Document.id).where(
            Document.sha256 == sha256,
            Document.size_bytes == size_bytes,
        )
    )


def _best_effort_delete(storage: PrivateDocumentStorage, key: str) -> None:
    with suppress(DocumentStorageError):
        storage.delete(key)
