import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Annotated, BinaryIO
from uuid import UUID, uuid4

from fastapi import Depends

from app.core.config import Settings, get_settings


class DocumentStorageError(RuntimeError):
    """Raised when the private storage boundary cannot complete an operation."""


class UnsafeStorageKeyError(DocumentStorageError):
    """Raised when an opaque storage key could escape the configured root."""


class PrivateDocumentStorage:
    backend_name = "private_filesystem_v1"

    def __init__(self, root: Path) -> None:
        if root.exists() and root.is_symlink():
            raise DocumentStorageError("document storage root cannot be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        self._root = root.resolve(strict=True)
        self._ensure_directory(self._root / "staging")
        self._ensure_directory(self._root / "objects")

    @property
    def root(self) -> Path:
        return self._root

    def new_staging_key(self) -> str:
        return f"staging/{uuid4()}.upload"

    def final_key(self, document_id: UUID) -> str:
        value = document_id.hex
        return f"objects/{value[:2]}/{value[2:4]}/{document_id}"

    @contextmanager
    def open_staging_writer(self, key: str) -> Iterator[BinaryIO]:
        path = self._path_for(key)
        if path.parent != self._root / "staging":
            raise UnsafeStorageKeyError("staging key is outside the staging directory")
        try:
            with path.open("xb") as stream:
                yield stream
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise DocumentStorageError("unable to write staged document") from exc

    @contextmanager
    def open_reader(self, key: str) -> Iterator[BinaryIO]:
        path = self._path_for(key)
        if path.is_symlink():
            raise UnsafeStorageKeyError("document storage object cannot be a symlink")
        try:
            with path.open("rb") as stream:
                yield stream
        except OSError as exc:
            raise DocumentStorageError("unable to read stored document") from exc

    def promote(self, staging_key: str, final_key: str) -> None:
        source = self._path_for(staging_key)
        destination = self._path_for(final_key)
        if source.parent != self._root / "staging" or source.is_symlink():
            raise UnsafeStorageKeyError("invalid staged document key")
        self._ensure_directory(destination.parent)
        if destination.exists():
            raise DocumentStorageError("document storage object already exists")
        try:
            os.replace(source, destination)
        except OSError as exc:
            raise DocumentStorageError("unable to promote staged document") from exc

    def delete(self, key: str) -> None:
        path = self._path_for(key)
        if path.is_symlink():
            raise UnsafeStorageKeyError("document storage object cannot be a symlink")
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise DocumentStorageError("unable to delete stored document") from exc

    def exists(self, key: str) -> bool:
        path = self._path_for(key)
        return path.exists() and not path.is_symlink()

    def _path_for(self, key: str) -> Path:
        if not key or "\\" in key:
            raise UnsafeStorageKeyError("invalid document storage key")
        pure_key = PurePosixPath(key)
        if pure_key.is_absolute() or any(part in {"", ".", ".."} for part in pure_key.parts):
            raise UnsafeStorageKeyError("invalid document storage key")
        candidate = self._root.joinpath(*pure_key.parts)
        self._reject_symlink_ancestors(candidate.parent)
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self._root):
            raise UnsafeStorageKeyError("document storage key escapes configured root")
        return resolved

    def _ensure_directory(self, directory: Path) -> None:
        self._reject_symlink_ancestors(directory.parent)
        if directory.exists() and directory.is_symlink():
            raise UnsafeStorageKeyError("document storage directory cannot be a symlink")
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DocumentStorageError("unable to initialize document storage") from exc

    def _reject_symlink_ancestors(self, path: Path) -> None:
        current = path
        while current != self._root:
            if current.exists() and current.is_symlink():
                raise UnsafeStorageKeyError("document storage path contains a symlink")
            if not current.is_relative_to(self._root):
                raise UnsafeStorageKeyError("document storage path escapes configured root")
            current = current.parent


@lru_cache
def _storage_for_root(root: str) -> PrivateDocumentStorage:
    return PrivateDocumentStorage(Path(root))


def get_document_storage(
    settings: Annotated[Settings, Depends(get_settings)],
) -> PrivateDocumentStorage:
    return _storage_for_root(str(settings.document_storage_root))
