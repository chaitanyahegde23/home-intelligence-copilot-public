from __future__ import annotations

import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from pydantic import ValidationError
from pypdf import PdfReader, PdfWriter

from app.core.config import Settings
from app.services.document_text_extractor import (
    DocumentTextExtractionError,
    ExtractedTextTooLargeError,
    OcrmypdfProcessor,
    PypdfOcrTextExtractor,
)

SAMPLE_PDF = (
    Path(__file__).resolve().parents[2] / "sample-data" / "synthetic-household-document.pdf"
)
SCANNED_PDF = Path(__file__).resolve().parents[2] / "sample-data" / "synthetic-scanned-warranty.pdf"


class RecordingOcrProcessor:
    def __init__(self, output: bytes) -> None:
        self.output = output
        self.calls: list[tuple[bytes, str, int]] = []

    def process(
        self,
        source: Path,
        destination: Path,
        *,
        language: str,
        timeout_seconds: int,
    ) -> None:
        self.calls.append((source.read_bytes(), language, timeout_seconds))
        destination.write_bytes(self.output)


class FailingOcrProcessor:
    def process(
        self,
        source: Path,
        destination: Path,
        *,
        language: str,
        timeout_seconds: int,
    ) -> None:
        raise DocumentTextExtractionError("synthetic engine detail")


def image_only_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def mixed_pdf() -> bytes:
    writer = PdfWriter()
    native_reader = PdfReader(BytesIO(SAMPLE_PDF.read_bytes()), strict=True)
    writer.add_page(native_reader.pages[0])
    writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def two_native_pages_pdf() -> bytes:
    writer = PdfWriter()
    native_reader = PdfReader(BytesIO(SAMPLE_PDF.read_bytes()), strict=True)
    writer.add_page(native_reader.pages[0])
    writer.add_page(native_reader.pages[0])
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_committed_ocr_fixture_contains_no_native_text() -> None:
    processor = RecordingOcrProcessor(SAMPLE_PDF.read_bytes())
    extractor = PypdfOcrTextExtractor(ocr_processor=processor)

    extracted = extractor.extract(BytesIO(SCANNED_PDF.read_bytes()), max_chars=100_000)

    assert len(processor.calls) == 1
    assert "Synthetic Home Warranty Summary" in extracted.spans[0].text


def test_native_text_bypasses_local_ocr() -> None:
    processor = RecordingOcrProcessor(SAMPLE_PDF.read_bytes())
    extractor = PypdfOcrTextExtractor(ocr_processor=processor)

    extracted = extractor.extract(BytesIO(SAMPLE_PDF.read_bytes()), max_chars=100_000)

    assert processor.calls == []
    assert "Synthetic Home Warranty Summary" in extracted.spans[0].text


def test_image_only_page_uses_local_ocr_with_configured_limits() -> None:
    source = image_only_pdf()
    processor = RecordingOcrProcessor(SAMPLE_PDF.read_bytes())
    extractor = PypdfOcrTextExtractor(
        language="eng+deu",
        timeout_seconds=45,
        ocr_processor=processor,
    )

    extracted = extractor.extract(BytesIO(source), max_chars=100_000)

    assert processor.calls == [(source, "eng+deu", 45)]
    assert extractor.identity.name == "pypdf_native_ocr"
    assert extractor.identity.version == "1"
    assert [span.page_number for span in extracted.spans] == [1]
    assert "Synthetic Home Warranty Summary" in extracted.spans[0].text


def test_mixed_native_and_empty_pages_use_one_ocr_pass_and_keep_page_provenance() -> None:
    source = mixed_pdf()
    processor = RecordingOcrProcessor(two_native_pages_pdf())
    extractor = PypdfOcrTextExtractor(ocr_processor=processor)

    extracted = extractor.extract(BytesIO(source), max_chars=100_000)

    assert len(processor.calls) == 1
    assert [span.page_number for span in extracted.spans] == [1, 2]
    assert all("Synthetic Home Warranty Summary" in span.text for span in extracted.spans)


def test_local_ocr_processor_failure_fails_extraction() -> None:
    extractor = PypdfOcrTextExtractor(ocr_processor=FailingOcrProcessor())

    with pytest.raises(DocumentTextExtractionError, match="synthetic engine detail"):
        extractor.extract(BytesIO(image_only_pdf()), max_chars=100_000)


def test_local_ocr_output_respects_the_existing_text_limit() -> None:
    extractor = PypdfOcrTextExtractor(ocr_processor=RecordingOcrProcessor(SAMPLE_PDF.read_bytes()))

    with pytest.raises(ExtractedTextTooLargeError):
        extractor.extract(BytesIO(image_only_pdf()), max_chars=10)


def test_ocr_language_configuration_rejects_command_like_values() -> None:
    with pytest.raises(ValidationError):
        Settings(document_ocr_language="eng;echo unsafe")


def test_ocrmypdf_runner_uses_fixed_bounded_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "ocr.pdf"
    source.write_bytes(image_only_pdf())
    captured_command: list[str] = []

    def successful_run(
        command: list[str],
        *,
        capture_output: bool,
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[bytes]:
        captured_command.extend(command)
        assert capture_output is True
        assert check is False
        assert timeout == 33
        destination.write_bytes(SAMPLE_PDF.read_bytes())
        return subprocess.CompletedProcess(command, returncode=0)

    monkeypatch.setattr(subprocess, "run", successful_run)

    OcrmypdfProcessor().process(
        source,
        destination,
        language="eng",
        timeout_seconds=33,
    )

    assert captured_command[1:4] == ["-m", "ocrmypdf", "--skip-text"]
    assert captured_command[-2:] == [str(source), str(destination)]


def test_ocrmypdf_timeout_is_reported_without_engine_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pdf"
    destination = tmp_path / "ocr.pdf"
    source.write_bytes(image_only_pdf())

    def timed_out(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd="synthetic", timeout=1, stderr=b"private OCR text")

    monkeypatch.setattr(subprocess, "run", timed_out)

    with pytest.raises(DocumentTextExtractionError, match="^local OCR processing failed$"):
        OcrmypdfProcessor().process(
            source,
            destination,
            language="eng",
            timeout_seconds=1,
        )
