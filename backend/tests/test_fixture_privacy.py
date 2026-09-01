import re
from pathlib import Path

from pypdf import PdfReader

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA = REPOSITORY_ROOT / "sample-data"
PRIVATE_LOCAL_DATA = SAMPLE_DATA / "actual_docs"
SENSITIVE_PATTERNS = {
    "email address": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    "SSN-like value": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "long identifier": re.compile(r"(?<!\d)\d{8,}(?!\d)"),
    "grouped card-like value": re.compile(r"\b(?:\d[ -]?){12,19}\b"),
    "local user path": re.compile(r"[A-Z]:\\Users\\", re.IGNORECASE),
}


def repository_fixtures(pattern: str) -> list[Path]:
    return sorted(
        fixture
        for fixture in SAMPLE_DATA.rglob(pattern)
        if not fixture.is_relative_to(PRIVATE_LOCAL_DATA)
    )


def test_private_local_validation_directory_is_gitignored() -> None:
    ignored_entries = {
        line.strip()
        for line in (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "sample-data/actual_docs/" in ignored_entries


def test_repository_fixtures_are_named_synthetic_and_scan_clean() -> None:
    fixtures = repository_fixtures("*.csv")
    assert fixtures, "At least one synthetic CSV fixture is expected"

    for fixture in fixtures:
        assert fixture.name.startswith("synthetic-")
        content = fixture.read_text(encoding="utf-8-sig")
        for label, pattern in SENSITIVE_PATTERNS.items():
            assert pattern.search(content) is None, f"{fixture.name} contains a {label}"

    pdf_fixtures = repository_fixtures("*.pdf")
    assert pdf_fixtures, "At least one synthetic PDF fixture is expected"

    for fixture in pdf_fixtures:
        assert fixture.name.startswith("synthetic-")
        reader = PdfReader(fixture, strict=True)
        content = "\n".join(page.extract_text() or "" for page in reader.pages)
        for label, pattern in SENSITIVE_PATTERNS.items():
            assert pattern.search(content) is None, f"{fixture.name} contains a {label}"

    json_fixtures = repository_fixtures("*.json")
    assert json_fixtures, "At least one synthetic JSON fixture is expected"

    for fixture in json_fixtures:
        assert fixture.name.startswith("synthetic-")
        content = fixture.read_text(encoding="utf-8")
        for label, pattern in SENSITIVE_PATTERNS.items():
            assert pattern.search(content) is None, f"{fixture.name} contains a {label}"
