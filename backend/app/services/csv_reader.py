import csv
from dataclasses import dataclass
from io import StringIO


class CsvReadError(ValueError):
    """Raised when uploaded bytes cannot be read as a supported CSV document."""


@dataclass(frozen=True)
class CsvRow:
    row_number: int
    values: list[str]


@dataclass(frozen=True)
class CsvDocument:
    headers: list[str]
    rows: list[CsvRow]


def with_header_row(document: CsvDocument, row_number: int) -> CsvDocument | None:
    """Return a document re-based at an explicitly reviewed header row."""
    if row_number == 1:
        return document
    header_row = next(
        (row for row in document.rows if row.row_number == row_number),
        None,
    )
    if header_row is None:
        return None
    return CsvDocument(
        headers=[header.strip() for header in header_row.values],
        rows=[row for row in document.rows if row.row_number > row_number],
    )


def read_csv_document(content: bytes) -> CsvDocument:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise CsvReadError("CSV file must be UTF-8 encoded") from error

    try:
        parsed_rows = list(csv.reader(StringIO(text, newline=""), strict=True))
    except csv.Error as error:
        raise CsvReadError(f"CSV parsing failed: {error}") from error

    if not parsed_rows:
        return CsvDocument(headers=[], rows=[])

    headers = [header.strip() for header in parsed_rows[0]]
    rows = [
        CsvRow(row_number=row_number, values=values)
        for row_number, values in enumerate(parsed_rows[1:], start=2)
        if values
    ]
    return CsvDocument(headers=headers, rows=rows)
