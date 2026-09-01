from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

AdapterName = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
]
AdapterVersion = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=50,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]
AccountLabel = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=255),
]
CanonicalText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1),
]
OptionalCanonicalText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1),
]
StrictDate = Annotated[date, Field(strict=True)]
StrictMoney = Annotated[Decimal, Field(strict=True, max_digits=18, decimal_places=2)]


class StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdapterIdentity(StrictContractModel):
    name: AdapterName
    version: AdapterVersion


class CanonicalTransactionRow(StrictContractModel):
    transaction_date: StrictDate
    posted_date: StrictDate | None = None
    description: CanonicalText
    amount: StrictMoney
    account_name: OptionalCanonicalText | None = None
    merchant_name: OptionalCanonicalText | None = None
    transaction_type: OptionalCanonicalText | None = None
    category: OptionalCanonicalText | None = None


class AdapterRowError(StrictContractModel):
    row_number: int | None = Field(default=None, ge=2)
    field: str | None = None
    message: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]


class AdapterNormalizationResult(StrictContractModel):
    adapter: AdapterIdentity
    account_label: AccountLabel | None = None
    rows: list[CanonicalTransactionRow] = Field(default_factory=list)
    errors: list[AdapterRowError] = Field(default_factory=list)
    ignored_row_count: int = Field(default=0, ge=0)


class MatchedAdapterDetection(StrictContractModel):
    status: Literal["matched"] = "matched"
    adapter: AdapterIdentity


class UnsupportedAdapterDetection(StrictContractModel):
    status: Literal["unsupported"] = "unsupported"
    message: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]


class AmbiguousAdapterDetection(StrictContractModel):
    status: Literal["ambiguous"] = "ambiguous"
    candidates: list[AdapterIdentity] = Field(min_length=2)
    message: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]

    @field_validator("candidates")
    @classmethod
    def require_unique_candidates(
        cls,
        candidates: list[AdapterIdentity],
    ) -> list[AdapterIdentity]:
        identities = {(candidate.name, candidate.version) for candidate in candidates}
        if len(identities) != len(candidates):
            raise ValueError("ambiguous candidates must be unique")
        return candidates


AdapterDetectionResult = Annotated[
    MatchedAdapterDetection | UnsupportedAdapterDetection | AmbiguousAdapterDetection,
    Field(discriminator="status"),
]
