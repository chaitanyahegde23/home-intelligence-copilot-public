from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
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
from app.schemas import (
    CategorizationRuleCreate,
    CategoryCreate,
    TransactionCategoryAssignmentCreate,
)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(Engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session
    engine.dispose()


def make_transaction() -> Transaction:
    return Transaction(
        import_batch=ImportBatch(filename="synthetic-transactions.csv"),
        transaction_date=date(2026, 7, 1),
        description="Synthetic grocery purchase",
        merchant_name="Example Market",
        amount=Decimal("42.15"),
        source_file="synthetic-transactions.csv",
    )


def test_create_category_with_defaults_and_timestamps(session: Session) -> None:
    category = Category(name="Groceries", description="Household food purchases")
    session.add(category)
    session.flush()

    assert isinstance(category.id, UUID)
    assert category.is_active is True
    assert category.created_at.tzinfo is not None
    assert category.updated_at.tzinfo is not None


def test_category_database_constraints(session: Session) -> None:
    session.add(Category(name="   "))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    session.add_all([Category(name="Utilities"), Category(name="Utilities")])
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_rule_relationship_defaults_and_precedence(session: Session) -> None:
    category = Category(name="Dining")
    later_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    earlier_id = UUID("00000000-0000-0000-0000-000000000001")
    rules = [
        CategorizationRule(
            id=later_id,
            category=category,
            match_field=RuleMatchField.DESCRIPTION,
            match_type=RuleMatchType.CONTAINS,
            pattern="restaurant",
            priority=20,
        ),
        CategorizationRule(
            id=earlier_id,
            category=category,
            match_field=RuleMatchField.MERCHANT_NAME,
            match_type=RuleMatchType.PREFIX,
            pattern="Example",
            priority=20,
        ),
        CategorizationRule(
            category=category,
            match_field=RuleMatchField.DESCRIPTION,
            match_type=RuleMatchType.EXACT,
            pattern="Coffee",
            priority=10,
        ),
    ]
    session.add_all(rules)
    session.flush()

    ordered = sorted(rules, key=lambda rule: rule.precedence_key)
    assert ordered[0].priority == 10
    assert ordered[1].id == earlier_id
    assert rules[0] in category.rules
    assert all(rule.case_sensitive is False and rule.is_active is True for rule in rules)


def test_manual_assignment_relationship_and_one_current_assignment(session: Session) -> None:
    transaction = make_transaction()
    category = Category(name="Groceries")
    assignment = TransactionCategoryAssignment(
        transaction=transaction,
        category=category,
        source=CategoryAssignmentSource.MANUAL,
        note="Household correction",
    )
    session.add(assignment)
    session.flush()

    assert transaction.category_assignment is assignment
    assert assignment in category.assignments
    assert assignment.rule is None
    assert assignment.created_at.tzinfo is not None

    session.add(
        TransactionCategoryAssignment(
            transaction=transaction,
            category=category,
            source=CategoryAssignmentSource.IMPORTED,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_rule_assignment_requires_rule_and_relationships(session: Session) -> None:
    transaction = make_transaction()
    category = Category(name="Travel")
    rule = CategorizationRule(
        category=category,
        match_field=RuleMatchField.DESCRIPTION,
        match_type=RuleMatchType.CONTAINS,
        pattern="airline",
    )
    assignment = TransactionCategoryAssignment(
        transaction=transaction,
        category=category,
        source=CategoryAssignmentSource.RULE,
        rule=rule,
    )
    session.add(assignment)
    session.flush()

    assert assignment.rule is rule
    assert assignment in rule.assignments


def test_database_rejects_inconsistent_assignment_source(session: Session) -> None:
    session.add(
        TransactionCategoryAssignment(
            transaction=make_transaction(),
            category=Category(name="Other"),
            source=CategoryAssignmentSource.RULE,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_transaction_delete_cascades_assignment(session: Session) -> None:
    transaction = make_transaction()
    assignment = TransactionCategoryAssignment(
        transaction=transaction,
        category=Category(name="Bills"),
        source=CategoryAssignmentSource.MANUAL,
    )
    session.add(assignment)
    session.flush()
    assignment_id = assignment.id

    session.delete(transaction)
    session.flush()

    assert (
        session.scalar(
            select(TransactionCategoryAssignment).where(
                TransactionCategoryAssignment.id == assignment_id
            )
        )
        is None
    )


def test_categorization_schemas_normalize_and_validate() -> None:
    category = CategoryCreate.model_validate(
        {"name": "  Groceries  ", "description": "  Food purchases  "}
    )
    assert category.name == "Groceries"
    assert category.description == "Food purchases"

    rule = CategorizationRuleCreate.model_validate(
        {
            "category_id": uuid4(),
            "match_field": "description",
            "match_type": "contains",
            "pattern": "  market  ",
        }
    )
    assert rule.pattern == "market"
    assert rule.priority == 100

    with pytest.raises(ValidationError):
        CategoryCreate.model_validate({"name": " "})
    with pytest.raises(ValidationError):
        CategorizationRuleCreate.model_validate(
            {
                "category_id": uuid4(),
                "match_field": "description",
                "match_type": "contains",
                "pattern": " ",
                "priority": -1,
            }
        )
    with pytest.raises(ValidationError):
        TransactionCategoryAssignmentCreate.model_validate(
            {
                "transaction_id": uuid4(),
                "category_id": uuid4(),
                "source": "rule",
            }
        )
    with pytest.raises(ValidationError):
        TransactionCategoryAssignmentCreate.model_validate(
            {
                "transaction_id": uuid4(),
                "category_id": uuid4(),
                "source": "manual",
                "rule_id": uuid4(),
            }
        )
