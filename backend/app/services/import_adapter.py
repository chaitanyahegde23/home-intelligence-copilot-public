from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.schemas.import_adapter import (
    AccountLabel,
    AdapterDetectionResult,
    AdapterIdentity,
    AdapterNormalizationResult,
    AmbiguousAdapterDetection,
    MatchedAdapterDetection,
    UnsupportedAdapterDetection,
)
from app.services.csv_reader import CsvDocument, with_header_row

HeaderSignature = frozenset[str]


class TransactionCsvAdapter(Protocol):
    """Contract implemented by each explicitly supported CSV layout."""

    @property
    def identity(self) -> AdapterIdentity: ...

    @property
    def header_signatures(self) -> tuple[HeaderSignature, ...]: ...

    @property
    def header_row_numbers(self) -> tuple[int, ...]: ...

    def normalize(
        self,
        document: CsvDocument,
        *,
        account_label: AccountLabel | None,
    ) -> AdapterNormalizationResult: ...


@dataclass(frozen=True)
class AdapterSelection:
    detection: AdapterDetectionResult
    document: CsvDocument


class AdapterRegistry:
    """Select one adapter using an exact header signature and reviewed row location."""

    def __init__(self, adapters: tuple[TransactionCsvAdapter, ...]) -> None:
        identities = [(adapter.identity.name, adapter.identity.version) for adapter in adapters]
        if len(identities) != len(set(identities)):
            raise ValueError("Registered adapter identities must be unique")
        for adapter in adapters:
            locations = adapter.header_row_numbers
            if (
                not locations
                or len(locations) != len(set(locations))
                or any(location < 1 for location in locations)
            ):
                raise ValueError("Adapter header row numbers must be unique positive integers")
        self._adapters = adapters

    def detect(
        self,
        headers: list[str],
        *,
        header_row_number: int = 1,
    ) -> AdapterDetectionResult:
        if not headers:
            return UnsupportedAdapterDetection(message="CSV file has no header row")
        if len(headers) != len(set(headers)):
            return UnsupportedAdapterDetection(message="CSV contains duplicate column names")

        signature = frozenset(headers)
        matches = [
            adapter
            for adapter in self._adapters
            if header_row_number in adapter.header_row_numbers
            and signature in adapter.header_signatures
        ]
        if not matches:
            return UnsupportedAdapterDetection(
                message="CSV headers do not match a supported format"
            )
        if len(matches) > 1:
            return AmbiguousAdapterDetection(
                candidates=[adapter.identity for adapter in matches],
                message="CSV headers match more than one supported format",
            )
        return MatchedAdapterDetection(adapter=matches[0].identity)

    def select(self, document: CsvDocument) -> AdapterSelection:
        matched_documents: list[tuple[AdapterIdentity, CsvDocument]] = []
        ambiguous_identities: list[AdapterIdentity] = []

        row_numbers = sorted(
            {row_number for adapter in self._adapters for row_number in adapter.header_row_numbers}
        )
        for row_number in row_numbers:
            candidate = with_header_row(document, row_number)
            if candidate is None:
                continue
            detection = self.detect(
                candidate.headers,
                header_row_number=row_number,
            )
            if isinstance(detection, MatchedAdapterDetection):
                matched_documents.append((detection.adapter, candidate))
            elif isinstance(detection, AmbiguousAdapterDetection):
                ambiguous_identities.extend(detection.candidates)

        identities = [identity for identity, _ in matched_documents] + ambiguous_identities
        unique_identities = list(
            {(identity.name, identity.version): identity for identity in identities}.values()
        )
        if len(unique_identities) > 1:
            return AdapterSelection(
                detection=AmbiguousAdapterDetection(
                    candidates=unique_identities,
                    message="CSV headers match more than one supported format",
                ),
                document=document,
            )
        if len(matched_documents) == 1 and not ambiguous_identities:
            identity, selected_document = matched_documents[0]
            return AdapterSelection(
                detection=MatchedAdapterDetection(adapter=identity),
                document=selected_document,
            )
        if len(matched_documents) > 1:
            return AdapterSelection(
                detection=UnsupportedAdapterDetection(
                    message="CSV contains more than one reviewed header row"
                ),
                document=document,
            )

        return AdapterSelection(
            detection=self.detect(document.headers),
            document=document,
        )

    def get(self, identity: AdapterIdentity) -> TransactionCsvAdapter:
        matches = [adapter for adapter in self._adapters if adapter.identity == identity]
        if len(matches) != 1:
            raise LookupError(
                f"Expected one registered adapter for {identity.name} {identity.version}"
            )
        return matches[0]


@lru_cache
def get_adapter_registry() -> AdapterRegistry:
    from app.services.bank_of_america_account_adapter import (
        BankOfAmericaAccountAdapter,
    )
    from app.services.canonical_csv_adapter import CanonicalCsvAdapter
    from app.services.chase_credit_card_adapter import ChaseCreditCardAdapter
    from app.services.citi_credit_card_adapter import CitiCreditCardAdapter

    return AdapterRegistry(
        (
            CanonicalCsvAdapter(),
            CitiCreditCardAdapter(),
            ChaseCreditCardAdapter(),
            BankOfAmericaAccountAdapter(),
        )
    )
