from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO, Protocol
from unicodedata import category

from pypdf import PdfReader


class DocumentTextExtractionError(RuntimeError):
    """Raised when a stored document cannot be deterministically extracted."""


class ExtractedTextTooLargeError(DocumentTextExtractionError):
    pass


@dataclass(frozen=True)
class ExtractorIdentity:
    name: str
    version: str


@dataclass(frozen=True)
class ExtractedTextSpan:
    page_number: int
    section_number: int
    text: str


@dataclass(frozen=True)
class ExtractedDocumentText:
    spans: tuple[ExtractedTextSpan, ...]
    embedded_title: str | None = None


class DocumentTextExtractor(Protocol):
    identity: ExtractorIdentity

    def extract(self, stream: BinaryIO, *, max_chars: int) -> ExtractedDocumentText: ...


class LocalOcrProcessor(Protocol):
    def process(
        self,
        source: Path,
        destination: Path,
        *,
        language: str,
        timeout_seconds: int,
    ) -> None: ...


class PypdfTextExtractor:
    identity = ExtractorIdentity(name="pypdf_native", version="2")

    def extract(self, stream: BinaryIO, *, max_chars: int) -> ExtractedDocumentText:
        try:
            stream.seek(0)
            reader = PdfReader(stream, strict=True)
            if reader.is_encrypted:
                raise DocumentTextExtractionError("encrypted PDFs are not supported")
            embedded_title = _embedded_title(reader)
            spans: list[ExtractedTextSpan] = []
            total_chars = 0
            for page_number, page in enumerate(reader.pages, start=1):
                text = _normalize_extracted_text(page.extract_text() or "")
                total_chars += len(text)
                if total_chars > max_chars:
                    raise ExtractedTextTooLargeError("extracted text exceeds the configured limit")
                spans.append(
                    ExtractedTextSpan(
                        page_number=page_number,
                        section_number=1,
                        text=text,
                    )
                )
        except DocumentTextExtractionError:
            raise
        except Exception as exc:
            raise DocumentTextExtractionError("stored PDF text extraction failed") from exc
        return ExtractedDocumentText(spans=tuple(spans), embedded_title=embedded_title)


class OcrmypdfProcessor:
    def process(
        self,
        source: Path,
        destination: Path,
        *,
        language: str,
        timeout_seconds: int,
    ) -> None:
        command = [
            sys.executable,
            "-m",
            "ocrmypdf",
            "--skip-text",
            "--output-type",
            "pdf",
            "--optimize",
            "0",
            "--language",
            language,
            "--quiet",
            str(source),
            str(destination),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DocumentTextExtractionError("local OCR processing failed") from exc
        if result.returncode != 0 or not destination.is_file():
            raise DocumentTextExtractionError("local OCR processing failed")


class PypdfOcrTextExtractor:
    identity = ExtractorIdentity(name="pypdf_native_ocr", version="1")

    def __init__(
        self,
        *,
        language: str = "eng",
        timeout_seconds: int = 120,
        ocr_processor: LocalOcrProcessor | None = None,
    ) -> None:
        self._language = language
        self._timeout_seconds = timeout_seconds
        self._ocr_processor = ocr_processor or OcrmypdfProcessor()
        self._native_extractor = PypdfTextExtractor()

    def extract(self, stream: BinaryIO, *, max_chars: int) -> ExtractedDocumentText:
        native = self._native_extractor.extract(stream, max_chars=max_chars)
        if all(span.text.strip() for span in native.spans):
            return native

        try:
            with TemporaryDirectory(prefix="hic-ocr-") as temporary_directory:
                temporary_root = Path(temporary_directory)
                source = temporary_root / "source.pdf"
                destination = temporary_root / "ocr.pdf"
                stream.seek(0)
                source.write_bytes(stream.read())
                self._ocr_processor.process(
                    source,
                    destination,
                    language=self._language,
                    timeout_seconds=self._timeout_seconds,
                )
                with destination.open("rb") as ocr_stream:
                    ocr_text = self._native_extractor.extract(ocr_stream, max_chars=max_chars)
        except DocumentTextExtractionError:
            raise
        except Exception as exc:
            raise DocumentTextExtractionError("local OCR processing failed") from exc
        return ExtractedDocumentText(
            spans=ocr_text.spans,
            embedded_title=native.embedded_title or ocr_text.embedded_title,
        )


def _normalize_extracted_text(value: str) -> str:
    normalized_lines = value.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        character
        for character in normalized_lines
        if character in {"\n", "\t"} or category(character) != "Cc"
    )


def _embedded_title(reader: PdfReader) -> str | None:
    metadata = reader.metadata
    if metadata is None or metadata.title is None:
        return None
    return str(metadata.title)


def get_document_text_extractor() -> DocumentTextExtractor:
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.document_ocr_enabled:
        return PypdfTextExtractor()
    return PypdfOcrTextExtractor(
        language=settings.document_ocr_language,
        timeout_seconds=settings.document_ocr_timeout_seconds,
    )
