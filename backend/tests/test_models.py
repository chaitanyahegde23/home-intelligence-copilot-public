from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import ImportBatch, ImportStatus, Transaction
from app.schemas import ImportBatchCreate, TransactionCreate


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session
    engine.dispose()


def make_transaction(batch: ImportBatch, amount: Decimal = Decimal("42.15")) -> Transaction:
    return Transaction(
        import_batch=batch,
        transaction_date=date(2026, 7, 1),
        description="Synthetic grocery purchase",
        merchant_name="Example Market",
        amount=amount,
        category="Groceries",
        source_file="synthetic-transactions.csv",
    )


def test_create_import_batch(session: Session) -> None:
    batch = ImportBatch(filename="synthetic-transactions.csv")
    session.add(batch)
    session.flush()

    assert isinstance(batch.id, UUID)
    assert batch.status is ImportStatus.PENDING
    assert batch.row_count == 0
    assert batch.imported_count == 0
    assert batch.rejected_count == 0


def test_import_batch_provenance_defaults_and_schema_constraints(session: Session) -> None:
    batch = ImportBatch(filename="synthetic-transactions.csv")
    session.add(batch)
    session.flush()

    assert batch.adapter_name == "canonical_csv"
    assert batch.adapter_version == "1"
    assert batch.account_label is None

    validated = ImportBatchCreate.model_validate(
        {
            "filename": "synthetic-transactions.csv",
            "account_label": "  Sample Household Card  ",
        }
    )
    assert validated.adapter_name == "canonical_csv"
    assert validated.adapter_version == "1"
    assert validated.account_label == "Sample Household Card"

    for invalid in (
        {"adapter_name": "Invalid Name"},
        {"adapter_version": ""},
        {"account_label": "   "},
    ):
        with pytest.raises(ValidationError):
            ImportBatchCreate.model_validate({"filename": "synthetic-transactions.csv", **invalid})


def test_import_batch_database_rejects_blank_provenance(session: Session) -> None:
    session.add(
        ImportBatch(
            filename="synthetic-transactions.csv",
            adapter_name=" ",
            adapter_version="1",
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_create_transaction(session: Session) -> None:
    batch = ImportBatch(filename="synthetic-transactions.csv")
    transaction = make_transaction(batch)
    session.add(transaction)
    session.flush()

    stored = session.scalar(select(Transaction).where(Transaction.id == transaction.id))

    assert stored is not None
    assert isinstance(stored.id, UUID)
    assert stored.description == "Synthetic grocery purchase"
    assert stored.import_batch_id == batch.id


def test_decimal_precision_is_preserved(session: Session) -> None:
    transaction = make_transaction(
        ImportBatch(filename="synthetic-transactions.csv"),
        Decimal("1234567890.12"),
    )
    session.add(transaction)
    session.flush()
    session.expire(transaction, ["amount"])

    assert transaction.amount == Decimal("1234567890.12")

    with pytest.raises(ValidationError):
        TransactionCreate.model_validate(
            {
                "import_batch_id": uuid4(),
                "transaction_date": "2026-07-01",
                "description": "Too many decimal places",
                "amount": "1.234",
                "source_file": "synthetic-transactions.csv",
            }
        )


def test_required_fields_and_non_negative_counts_are_validated() -> None:
    with pytest.raises(ValidationError):
        ImportBatchCreate.model_validate({"filename": "", "row_count": -1})

    with pytest.raises(ValidationError):
        TransactionCreate.model_validate(
            {
                "import_batch_id": uuid4(),
                "amount": "10.00",
                "source_file": "synthetic-transactions.csv",
            }
        )


def test_import_batch_transaction_relationship(session: Session) -> None:
    batch = ImportBatch(filename="synthetic-transactions.csv")
    transaction = make_transaction(batch)
    session.add(batch)
    session.flush()

    assert transaction in batch.transactions
    assert transaction.import_batch is batch
    assert transaction.import_batch_id == batch.id


def test_timestamps_are_created_as_timezone_aware_values(session: Session) -> None:
    batch = ImportBatch(filename="synthetic-transactions.csv")
    transaction = make_transaction(batch)
    session.add(batch)
    session.flush()

    assert batch.created_at.tzinfo is not None
    assert batch.updated_at.tzinfo is not None
    assert transaction.created_at.tzinfo is not None
    assert transaction.updated_at.tzinfo is not None
