from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import cast

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import DuplicateCandidate, DuplicateStatus, ImportBatch, Transaction
from app.services.duplicate_detection import (
    FINGERPRINT_REASON,
    fingerprint_transaction,
)

CSV_HEADER = "transaction_date,posted_date,description,amount,account_name\n"
GROCERY_ROW = "2026-01-03,2026-01-04,Example Grocery Store,-82.45,Sample Checking\n"
EMPLOYER_ROW = "2026-01-05,2026-01-05,Example Employer,2500.00,Sample Checking\n"
UTILITY_ROW = "2026-01-08,2026-01-09,Example Utility,-125.30,Sample Checking\n"


@pytest.fixture
def client_and_session() -> Iterator[tuple[TestClient, Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as session:

        def override_get_db() -> Iterator[Session]:
            yield session

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_settings] = lambda: Settings(
            database_url="sqlite+pysqlite:///:memory:",
            max_upload_size_bytes=1024 * 1024,
        )
        with TestClient(app) as client:
            yield client, session
        app.dependency_overrides.clear()
    engine.dispose()


def upload_csv(
    client: TestClient,
    rows: str,
    *,
    filename: str = "synthetic-overlap.csv",
) -> Response:
    return cast(
        Response,
        client.post(
            "/imports/transactions",
            files={"file": (filename, (CSV_HEADER + rows).encode(), "text/csv")},
        ),
    )


def test_same_file_twice_creates_candidates_without_discarding_transactions(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session

    first = upload_csv(client, GROCERY_ROW + EMPLOYER_ROW, filename="synthetic-first.csv")
    second = upload_csv(client, GROCERY_ROW + EMPLOYER_ROW, filename="synthetic-second.csv")

    assert first.status_code == 201
    assert first.json()["duplicate_candidates_created"] == 0
    assert second.status_code == 201
    assert second.json()["duplicate_candidates_created"] == 2
    assert session.scalar(select(func.count()).select_from(Transaction)) == 4

    candidates = list(session.scalars(select(DuplicateCandidate)))
    assert len(candidates) == 2
    assert {candidate.status for candidate in candidates} == {DuplicateStatus.UNRESOLVED}
    assert {candidate.reason for candidate in candidates} == {FINGERPRINT_REASON}
    assert all(len(candidate.fingerprint) == 64 for candidate in candidates)
    assert all(
        candidate.first_transaction.import_batch_id != candidate.second_transaction.import_batch_id
        for candidate in candidates
    )


def test_overlapping_files_create_only_the_exact_overlap_candidate(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session

    upload_csv(client, GROCERY_ROW + EMPLOYER_ROW, filename="synthetic-january.csv")
    response = upload_csv(
        client,
        EMPLOYER_ROW + UTILITY_ROW,
        filename="synthetic-january-overlap.csv",
    )

    assert response.status_code == 201
    assert response.json()["duplicate_candidates_created"] == 1
    candidate = session.scalar(select(DuplicateCandidate))
    assert candidate is not None
    assert candidate.first_transaction.description == "Example Employer"
    assert candidate.second_transaction.description == "Example Employer"
    assert session.scalar(select(func.count()).select_from(Transaction)) == 4


def test_identical_rows_within_one_upload_are_retained_without_candidates(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session

    response = upload_csv(client, GROCERY_ROW * 3)

    assert response.status_code == 201
    assert response.json()["imported_rows"] == 3
    assert response.json()["duplicate_candidates_created"] == 0
    assert session.scalar(select(func.count()).select_from(Transaction)) == 3
    assert session.scalar(select(func.count()).select_from(DuplicateCandidate)) == 0


def test_normalized_whitespace_and_decimal_representation_match(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session

    first = "2026-01-03,2026-01-04,  Example   Grocery Store  ,-82.45, Sample   Checking \n"
    second = "2026-01-03,2026-01-04,Example Grocery Store,-82.450,Sample Checking\n"
    upload_csv(client, first)
    response = upload_csv(client, second)

    assert response.status_code == 201
    assert response.json()["duplicate_candidates_created"] == 1
    transactions = list(session.scalars(select(Transaction).order_by(Transaction.created_at)))
    assert fingerprint_transaction(transactions[0]) == fingerprint_transaction(transactions[1])


def test_fingerprint_canonicalizes_decimal_scale_and_signed_zero() -> None:
    positive_zero = Transaction(
        transaction_date=date(2026, 1, 3),
        posted_date=None,
        description="Synthetic zero",
        amount=Decimal("0.00"),
        account_name=None,
        merchant_name=None,
        transaction_type=None,
        category=None,
        source_file="synthetic-zero.csv",
    )
    negative_zero = Transaction(
        transaction_date=date(2026, 1, 3),
        posted_date=None,
        description="Synthetic zero",
        amount=Decimal("-0.000"),
        account_name=None,
        merchant_name=None,
        transaction_type=None,
        category=None,
        source_file="synthetic-zero-variant.csv",
    )

    assert fingerprint_transaction(positive_zero) == fingerprint_transaction(negative_zero)


def test_same_amount_at_different_merchants_has_different_fingerprint() -> None:
    first = Transaction(
        transaction_date=date(2026, 1, 3),
        posted_date=date(2026, 1, 4),
        description="Synthetic purchase",
        amount=Decimal("-25.00"),
        account_name="Sample Checking",
        merchant_name="Example Merchant One",
        transaction_type="purchase",
        category="Shopping",
        source_file="synthetic-merchant-one.csv",
    )
    second = Transaction(
        transaction_date=date(2026, 1, 3),
        posted_date=date(2026, 1, 4),
        description="Synthetic purchase",
        amount=Decimal("-25.00"),
        account_name="Sample Checking",
        merchant_name="Example Merchant Two",
        transaction_type="purchase",
        category="Shopping",
        source_file="synthetic-merchant-two.csv",
    )

    assert fingerprint_transaction(first) != fingerprint_transaction(second)


@pytest.mark.parametrize(
    "different_row",
    [
        "2026-01-03,2026-01-05,Example Grocery Store,-82.45,Sample Checking\n",
        "2026-01-03,2026-01-04,Example Grocery Market,-82.45,Sample Checking\n",
        "2026-01-03,2026-01-04,Example Grocery Store,-82.45,Sample Savings\n",
        "2026-01-04,2026-01-04,Example Grocery Store,-82.45,Sample Checking\n",
        "2026-01-03,2026-01-04,Example Grocery Store,-82.46,Sample Checking\n",
    ],
)
def test_same_value_lookalikes_are_not_flagged(
    client_and_session: tuple[TestClient, Session],
    different_row: str,
) -> None:
    client, session = client_and_session
    upload_csv(client, GROCERY_ROW)

    response = upload_csv(client, different_row)

    assert response.status_code == 201
    assert response.json()["duplicate_candidates_created"] == 0
    assert session.scalar(select(func.count()).select_from(DuplicateCandidate)) == 0


def test_candidate_creation_rolls_back_with_failed_import_persistence(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    upload_csv(client, GROCERY_ROW)

    def fail_when_candidate_is_pending(
        database_session: Session,
        *_args: object,
    ) -> None:
        if any(isinstance(item, DuplicateCandidate) for item in database_session.new):
            raise RuntimeError("synthetic duplicate persistence failure")

    event.listen(session, "before_flush", fail_when_candidate_is_pending)
    with pytest.raises(RuntimeError, match="synthetic duplicate persistence failure"):
        upload_csv(client, GROCERY_ROW)
    event.remove(session, "before_flush", fail_when_candidate_is_pending)

    assert session.scalar(select(func.count()).select_from(ImportBatch)) == 1
    assert session.scalar(select(func.count()).select_from(Transaction)) == 1
    assert session.scalar(select(func.count()).select_from(DuplicateCandidate)) == 0


def test_import_detail_reports_candidate_count_and_navigation(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, _ = client_and_session
    upload_csv(client, GROCERY_ROW, filename="synthetic-original.csv")
    duplicate = upload_csv(client, GROCERY_ROW, filename="synthetic-repeat.csv")
    batch_id = duplicate.json()["import_batch_id"]

    response = client.get(f"/imports/{batch_id}")

    assert response.status_code == 200
    assert response.json()["duplicate_candidate_count"] == 1
    assert response.json()["duplicate_candidates_url"] == (
        f"/duplicate-candidates?import_batch_id={batch_id}"
    )


def test_unresolved_candidates_remain_in_analytics_version_one(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, _ = client_and_session
    upload_csv(client, GROCERY_ROW)
    upload_csv(client, GROCERY_ROW)

    response = client.get(
        "/analytics/spending/summary",
        params={"start_date": date(2026, 1, 1), "end_date": date(2026, 1, 31)},
    )

    assert response.status_code == 200
    assert response.json()["total_spending"] == "164.90"
    assert response.json()["transaction_count"] == 2


def test_candidate_query_returns_provenance_and_supports_review(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    first = upload_csv(client, GROCERY_ROW, filename="synthetic-original.csv")
    second = upload_csv(client, GROCERY_ROW, filename="synthetic-repeat.csv")

    listed = client.get(
        "/duplicate-candidates",
        params={"import_batch_id": second.json()["import_batch_id"]},
    )

    assert listed.status_code == 200
    body = listed.json()
    assert body["pagination"] == {
        "total": 1,
        "offset": 0,
        "limit": 50,
        "returned": 1,
        "has_more": False,
    }
    item = body["items"][0]
    assert item["status"] == "unresolved"
    assert {item["first"]["import_batch"]["id"], item["second"]["import_batch"]["id"]} == {
        first.json()["import_batch_id"],
        second.json()["import_batch_id"],
    }
    assert {
        item["first"]["transaction"]["source_file"],
        item["second"]["transaction"]["source_file"],
    } == {"synthetic-original.csv", "synthetic-repeat.csv"}

    session.rollback()
    reviewed = client.patch(
        f"/duplicate-candidates/{item['id']}",
        json={
            "status": "confirmed",
            "resolution_note": "  Confirmed from synthetic overlap  ",
        },
    )

    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "confirmed"
    assert reviewed.json()["resolution_note"] == "Confirmed from synthetic overlap"
    assert reviewed.json()["resolved_at"] is not None

    session.rollback()
    confirmed = client.get("/duplicate-candidates", params={"status": "confirmed"})
    dismissed = client.get("/duplicate-candidates", params={"status": "dismissed"})
    assert confirmed.json()["pagination"]["total"] == 1
    assert dismissed.json()["pagination"]["total"] == 0


def test_candidate_api_validation_and_not_found(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, _ = client_and_session

    assert client.get("/duplicate-candidates/not-a-uuid").status_code == 422
    assert client.get("/duplicate-candidates", params={"limit": 101}).status_code == 422
    assert client.get("/duplicate-candidates", params={"status": "unknown"}).status_code == 422
    assert (
        client.get("/duplicate-candidates/00000000-0000-0000-0000-000000000001").status_code == 404
    )
    assert (
        client.patch(
            "/duplicate-candidates/00000000-0000-0000-0000-000000000001",
            json={"status": "unresolved"},
        ).status_code
        == 422
    )


def test_candidate_query_has_stable_bounded_pagination(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, _ = client_and_session
    upload_csv(client, GROCERY_ROW, filename="synthetic-one.csv")
    upload_csv(client, GROCERY_ROW, filename="synthetic-two.csv")
    upload_csv(client, GROCERY_ROW, filename="synthetic-three.csv")

    first_page = client.get("/duplicate-candidates", params={"limit": 2})
    second_page = client.get(
        "/duplicate-candidates",
        params={"limit": 2, "offset": 2},
    )

    assert first_page.status_code == 200
    assert first_page.json()["pagination"] == {
        "total": 2,
        "offset": 0,
        "limit": 2,
        "returned": 2,
        "has_more": False,
    }
    assert second_page.json()["pagination"] == {
        "total": 2,
        "offset": 2,
        "limit": 2,
        "returned": 0,
        "has_more": False,
    }
    first_ids = [item["id"] for item in first_page.json()["items"]]
    second_ids = [item["id"] for item in second_page.json()["items"]]
    assert not set(first_ids) & set(second_ids)
