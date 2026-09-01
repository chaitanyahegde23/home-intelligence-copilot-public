from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    CategorizationRule,
    Category,
    CategoryAssignmentSource,
    ImportBatch,
    RuleMatchField,
    RuleMatchType,
    Transaction,
    TransactionCategoryAssignment,
)
from app.services.categorization import rule_matches


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
        with TestClient(app) as client:
            yield client, session
        app.dependency_overrides.clear()
    engine.dispose()


def make_transaction(
    batch: ImportBatch,
    *,
    description: str,
    merchant_name: str | None = None,
    category: str | None = None,
) -> Transaction:
    return Transaction(
        import_batch=batch,
        transaction_date=date(2026, 7, 1),
        description=description,
        merchant_name=merchant_name,
        amount=Decimal("-42.15"),
        category=category,
        source_file="synthetic-categorization.csv",
    )


def post_category(client: TestClient, name: str) -> dict[str, object]:
    response = client.post("/categories", json={"name": name})
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def post_rule(
    client: TestClient,
    *,
    category_id: object,
    field: str = "description",
    match_type: str = "contains",
    pattern: str,
    priority: int = 100,
    case_sensitive: bool = False,
) -> dict[str, object]:
    response = client.post(
        "/categorization-rules",
        json={
            "category_id": category_id,
            "match_field": field,
            "match_type": match_type,
            "pattern": pattern,
            "priority": priority,
            "case_sensitive": case_sensitive,
        },
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def test_rule_matcher_supports_fields_operations_case_and_whitespace() -> None:
    transaction = Transaction(
        description="  EXAMPLE   Grocery Market ",
        merchant_name="Example Foods #42",
    )
    category = Category(name="Groceries")

    exact = CategorizationRule(
        category=category,
        match_field=RuleMatchField.DESCRIPTION,
        match_type=RuleMatchType.EXACT,
        pattern="example grocery market",
        case_sensitive=False,
    )
    prefix = CategorizationRule(
        category=category,
        match_field=RuleMatchField.MERCHANT_NAME,
        match_type=RuleMatchType.PREFIX,
        pattern="Example Foods",
        case_sensitive=True,
    )
    contains = CategorizationRule(
        category=category,
        match_field=RuleMatchField.DESCRIPTION,
        match_type=RuleMatchType.CONTAINS,
        pattern="Grocery",
        case_sensitive=True,
    )

    assert rule_matches(exact, transaction)
    assert rule_matches(prefix, transaction)
    assert rule_matches(contains, transaction)
    exact.case_sensitive = True
    assert not rule_matches(exact, transaction)
    transaction.merchant_name = None
    assert not rule_matches(prefix, transaction)


def test_category_and_rule_management_api(client_and_session: tuple[TestClient, Session]) -> None:
    client, session = client_and_session
    groceries = post_category(client, "Groceries")
    duplicate = client.post("/categories", json={"name": "Groceries"})
    assert duplicate.status_code == 409

    rule = post_rule(
        client,
        category_id=groceries["id"],
        pattern="  grocery   store  ",
        priority=20,
    )
    assert rule["pattern"] == "grocery store"

    renamed = client.patch(
        f"/categories/{groceries['id']}",
        json={"name": "Food", "description": "Household food"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Food"

    changed_rule = client.patch(
        f"/categorization-rules/{rule['id']}",
        json={"priority": 5, "match_type": "prefix"},
    )
    assert changed_rule.status_code == 200
    assert changed_rule.json()["priority"] == 5

    categories = client.get("/categories")
    rules = client.get("/categorization-rules")
    assert [item["name"] for item in categories.json()] == ["Food"]
    assert [item["id"] for item in rules.json()] == [rule["id"]]
    session.rollback()


def test_apply_uses_precedence_and_reports_conflicts(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    batch = ImportBatch(filename="synthetic-rules.csv")
    transaction = make_transaction(batch, description="Example Grocery Store")
    session.add(transaction)
    session.commit()

    general = post_category(client, "Shopping")
    specific = post_category(client, "Groceries")
    broad_rule = post_rule(
        client,
        category_id=general["id"],
        pattern="store",
        priority=20,
    )
    selected_rule = post_rule(
        client,
        category_id=specific["id"],
        pattern="grocery",
        priority=10,
    )

    response = client.post("/categorization/apply", json={})

    assert response.status_code == 200
    assert response.json() == {
        "examined_count": 1,
        "categorized_count": 1,
        "updated_count": 1,
        "unmatched_count": 0,
        "manual_preserved_count": 0,
        "conflict_count": 1,
        "conflicts": [
            {
                "transaction_id": str(transaction.id),
                "selected_rule_id": selected_rule["id"],
                "matched_rule_ids": [selected_rule["id"], broad_rule["id"]],
            }
        ],
    }
    session.refresh(transaction)
    assert transaction.category == "Groceries"
    assert transaction.category_assignment is not None
    assert str(transaction.category_assignment.rule_id) == selected_rule["id"]

    session.rollback()

    rerun = client.post("/categorization/apply", json={})
    assert rerun.json()["updated_count"] == 0


def test_equal_priority_uses_uuid_order(client_and_session: tuple[TestClient, Session]) -> None:
    client, session = client_and_session
    batch = ImportBatch(filename="synthetic-tie.csv")
    transaction = make_transaction(batch, description="Coffee Shop")
    first_category = Category(name="First")
    second_category = Category(name="Second")
    first_rule = CategorizationRule(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        category=first_category,
        match_field=RuleMatchField.DESCRIPTION,
        match_type=RuleMatchType.CONTAINS,
        pattern="coffee",
        priority=10,
    )
    second_rule = CategorizationRule(
        id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        category=second_category,
        match_field=RuleMatchField.DESCRIPTION,
        match_type=RuleMatchType.CONTAINS,
        pattern="shop",
        priority=10,
    )
    session.add_all([transaction, first_rule, second_rule])
    session.commit()

    response = client.post("/categorization/apply", json={})

    assert response.status_code == 200
    assert response.json()["conflicts"][0]["selected_rule_id"] == str(first_rule.id)
    session.refresh(transaction)
    assert transaction.category == "First"


def test_manual_assignment_survives_automatic_reruns(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    transaction = make_transaction(
        ImportBatch(filename="synthetic-manual.csv"),
        description="Example Grocery Store",
    )
    session.add(transaction)
    session.commit()
    automatic = post_category(client, "Groceries")
    manual = post_category(client, "Household choice")
    post_rule(client, category_id=automatic["id"], pattern="grocery")

    assigned = client.put(
        f"/transactions/{transaction.id}/category-assignment",
        json={"category_id": manual["id"], "note": "  User correction  "},
    )
    assert assigned.status_code == 200
    assert assigned.json()["source"] == "manual"
    assert assigned.json()["note"] == "User correction"

    response = client.post("/categorization/apply", json={})

    assert response.json()["manual_preserved_count"] == 1
    assert response.json()["categorized_count"] == 0
    session.refresh(transaction)
    assert transaction.category == "Household choice"
    assert transaction.category_assignment is not None
    assert transaction.category_assignment.source is CategoryAssignmentSource.MANUAL


def test_unmatched_rule_assignment_is_removed_but_imported_label_is_retained(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    batch = ImportBatch(filename="synthetic-unmatched.csv")
    formerly_matched = make_transaction(batch, description="Old Match")
    imported = make_transaction(batch, description="No Match", category="Bank Category")
    category = Category(name="Old Category")
    inactive_rule = CategorizationRule(
        category=category,
        match_field=RuleMatchField.DESCRIPTION,
        match_type=RuleMatchType.EXACT,
        pattern="Old Match",
        is_active=False,
    )
    formerly_matched.category = category.name
    formerly_matched.category_assignment = TransactionCategoryAssignment(
        category=category,
        source=CategoryAssignmentSource.RULE,
        rule=inactive_rule,
    )
    session.add_all([formerly_matched, imported])
    session.commit()

    response = client.post("/categorization/apply", json={})

    assert response.json()["unmatched_count"] == 2
    assert response.json()["updated_count"] == 1
    session.refresh(formerly_matched)
    session.refresh(imported)
    assert formerly_matched.category is None
    assert formerly_matched.category_assignment is None
    assert imported.category == "Bank Category"


def test_apply_can_be_scoped_to_one_import_batch(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    first_batch = ImportBatch(filename="synthetic-first.csv")
    second_batch = ImportBatch(filename="synthetic-second.csv")
    first = make_transaction(first_batch, description="Example Market")
    second = make_transaction(second_batch, description="Example Market")
    session.add_all([first, second])
    session.commit()
    category = post_category(client, "Groceries")
    post_rule(client, category_id=category["id"], pattern="market")

    response = client.post(
        "/categorization/apply",
        json={"import_batch_id": str(first_batch.id)},
    )

    assert response.status_code == 200
    assert response.json()["examined_count"] == 1
    session.refresh(first)
    session.refresh(second)
    assert first.category == "Groceries"
    assert second.category is None
    session.rollback()
    missing = client.post(
        "/categorization/apply",
        json={"import_batch_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert missing.status_code == 404


def test_rule_and_category_changes_keep_assignments_synchronized(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    transaction = make_transaction(
        ImportBatch(filename="synthetic-sync.csv"),
        description="Example Market",
    )
    session.add(transaction)
    session.commit()
    first = post_category(client, "Groceries")
    second = post_category(client, "Essentials")
    rule = post_rule(client, category_id=first["id"], pattern="market")
    client.post("/categorization/apply", json={})

    moved = client.patch(
        f"/categorization-rules/{rule['id']}",
        json={"category_id": second["id"]},
    )
    assert moved.status_code == 200
    session.refresh(transaction)
    assert transaction.category == "Essentials"
    assert transaction.category_assignment is not None
    assert str(transaction.category_assignment.category_id) == second["id"]

    session.rollback()

    renamed = client.patch(f"/categories/{second['id']}", json={"name": "Needs"})
    assert renamed.status_code == 200
    session.refresh(transaction)
    assert transaction.category == "Needs"


def test_apply_rolls_back_all_category_changes_on_database_failure(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    batch = ImportBatch(filename="synthetic-rollback.csv")
    first = make_transaction(batch, description="Example Market One")
    second = make_transaction(batch, description="Example Market Two")
    category = Category(name="Groceries")
    rule = CategorizationRule(
        category=category,
        match_field=RuleMatchField.DESCRIPTION,
        match_type=RuleMatchType.CONTAINS,
        pattern="market",
    )
    session.add_all([first, second, rule])
    session.commit()

    def fail_apply(database_session: Session, *_args: object) -> None:
        if any(isinstance(item, TransactionCategoryAssignment) for item in database_session.new):
            raise RuntimeError("synthetic categorization failure")

    event.listen(session, "before_flush", fail_apply)
    with pytest.raises(RuntimeError, match="synthetic categorization failure"):
        client.post("/categorization/apply", json={})
    event.remove(session, "before_flush", fail_apply)

    assert list(session.scalars(select(TransactionCategoryAssignment))) == []
    session.refresh(first)
    session.refresh(second)
    assert first.category is None
    assert second.category is None


def test_categorization_updates_existing_analytics_grouping(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    transaction = make_transaction(
        ImportBatch(filename="synthetic-analytics.csv"),
        description="Example Market",
    )
    session.add(transaction)
    session.commit()
    category = post_category(client, "Groceries")
    post_rule(client, category_id=category["id"], pattern="market")
    client.post("/categorization/apply", json={})

    response = client.get(
        "/analytics/spending/by-category",
        params={"start_date": "2026-07-01", "end_date": "2026-07-31"},
    )

    assert response.status_code == 200
    assert response.json()["groups"][0]["category"] == "Groceries"
    assert response.json()["groups"][0]["total_spending"] == "42.15"


def test_categorization_api_validation_and_not_found(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    transaction = make_transaction(
        ImportBatch(filename="synthetic-validation.csv"),
        description="Example",
    )
    inactive = Category(name="Inactive", is_active=False)
    session.add_all([transaction, inactive])
    session.commit()
    transaction_id = str(transaction.id)
    inactive_id = str(inactive.id)

    assert client.patch(f"/categories/{inactive_id}", json={}).status_code == 422
    assert (
        client.post(
            "/categorization-rules",
            json={
                "category_id": "00000000-0000-0000-0000-000000000001",
                "match_field": "description",
                "match_type": "contains",
                "pattern": "example",
            },
        ).status_code
        == 404
    )
    session.rollback()
    assert (
        client.put(
            f"/transactions/{transaction_id}/category-assignment",
            json={"category_id": inactive_id},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            "/categorization-rules/00000000-0000-0000-0000-000000000001",
            json={"priority": 1},
        ).status_code
        == 404
    )
    missing_transaction = client.put(
        "/transactions/00000000-0000-0000-0000-000000000001/category-assignment",
        json={"category_id": inactive_id},
    )
    assert missing_transaction.status_code == 404


def test_openapi_exposes_categorization_endpoints(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, _ = client_and_session
    response = cast(Response, client.get("/openapi.json"))
    paths = response.json()["paths"]

    assert "/categories" in paths
    assert "/categorization-rules" in paths
    assert "/categorization/apply" in paths
    assert "/transactions/{transaction_id}/category-assignment" in paths
