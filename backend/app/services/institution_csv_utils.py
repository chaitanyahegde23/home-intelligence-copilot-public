import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

DATE_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{4}$")
PLAIN_SIGNED_AMOUNT_PATTERN = re.compile(r"^-?\d+\.\d{2}$")
GROUPED_SIGNED_AMOUNT_PATTERN = re.compile(r"^-?(?:\d+|\d{1,3}(?:,\d{3})+)\.\d{2}$")


def parse_mmddyyyy(value: str) -> date | None:
    normalized = value.strip()
    if not DATE_PATTERN.fullmatch(normalized):
        return None
    try:
        return datetime.strptime(normalized, "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_signed_amount(
    value: str,
    *,
    allow_grouping: bool,
) -> tuple[Decimal | None, str | None]:
    normalized = value.strip()
    if not normalized:
        return None, "amount is required"

    pattern = GROUPED_SIGNED_AMOUNT_PATTERN if allow_grouping else PLAIN_SIGNED_AMOUNT_PATTERN
    if not pattern.fullmatch(normalized):
        expected = (
            "a signed decimal number with two decimal places and optional standard "
            "thousands separators"
            if allow_grouping
            else "a signed decimal number with exactly two decimal places"
        )
        return None, f"must be {expected}"

    try:
        amount = Decimal(normalized.replace(",", ""))
    except InvalidOperation:
        return None, "must be a finite decimal number"
    if not amount.is_finite():
        return None, "must be a finite decimal number"
    if amount == 0:
        return None, "must be nonzero"
    return amount, None


def normalize_text(value: str) -> str | None:
    normalized = " ".join(value.split())
    return normalized or None
