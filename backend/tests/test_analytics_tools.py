from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import ImportBatch, Transaction
from app.services.analytics_tools import (
    ANALYTICS_TOOL_CONTRACTS,
    APPROVED_ANALYTICS_TOOLS,
    AnalyticsToolName,
    UnsupportedAnalyticsToolError,
    execute_analytics_tool,
)


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


def seed_transactions(session: Session) -> None:
    batch = ImportBatch(
        filename="synthetic-tool-contracts.csv",
        adapter_name="synthetic_adapter",
        adapter_version="1",
        account_label="Sample Checking",
        row_count=3,
        imported_count=3,
    )
    session.add_all(
        [
            Transaction(
                id=UUID(int=1),
                import_batch=batch,
                transaction_date=date(2026, 1, 5),
                description="Synthetic Grocery",
                merchant_name="Synthetic Market",
                amount=Decimal("-100.00"),
                account_name="Sample Checking",
                category="Groceries",
                source_file=batch.filename,
            ),
            Transaction(
                id=UUID(int=2),
                import_batch=batch,
                transaction_date=date(2026, 1, 10),
                description="Synthetic Housing",
                merchant_name="Synthetic Housing Provider",
                amount=Decimal("-250.45"),
                account_name="Sample Checking",
                category="Housing",
                source_file=batch.filename,
            ),
            Transaction(
                id=UUID(int=3),
                import_batch=batch,
                transaction_date=date(2025, 12, 15),
                description="Synthetic Prior Grocery",
                merchant_name="Synthetic Market",
                amount=Decimal("-50.00"),
                account_name="Sample Checking",
                category="Groceries",
                source_file=batch.filename,
            ),
        ]
    )
    session.commit()


def test_allowlist_exposes_read_only_typed_contracts() -> None:
    assert tuple(contract.name for contract in APPROVED_ANALYTICS_TOOLS) == tuple(AnalyticsToolName)
    assert set(ANALYTICS_TOOL_CONTRACTS) == set(AnalyticsToolName)

    for contract in APPROVED_ANALYTICS_TOOLS:
        assert contract.access == "read_only"
        assert contract.description
        assert contract.arguments_json_schema()["additionalProperties"] is False
        assert contract.result_json_schema()["additionalProperties"] is False

    with pytest.raises(TypeError):
        cast(Any, ANALYTICS_TOOL_CONTRACTS)["delete_transactions"] = object()


@pytest.mark.parametrize(
    ("arguments", "expected_field"),
    [
        ({"end_date": "2026-01-31"}, "start_date"),
        (
            {"start_date": "2026-02-01", "end_date": "2026-01-31"},
            "start_date",
        ),
        (
            {"start_date": "June 2026", "end_date": "2026-06-30"},
            "start_date",
        ),
        (
            {
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "unapproved_filter": "value",
            },
            "unapproved_filter",
        ),
    ],
)
def test_tool_arguments_require_explicit_unambiguous_ranges_and_forbid_extras(
    client_and_session: tuple[TestClient, Session],
    arguments: dict[str, object],
    expected_field: str,
) -> None:
    _, session = client_and_session

    with pytest.raises(ValidationError) as exc_info:
        execute_analytics_tool(
            session,
            tool_name=AnalyticsToolName.GET_SPENDING_SUMMARY,
            arguments=arguments,
        )

    assert expected_field in str(exc_info.value)


def test_unsupported_tool_is_rejected_without_database_changes(
    client_and_session: tuple[TestClient, Session],
) -> None:
    _, session = client_and_session

    with pytest.raises(UnsupportedAnalyticsToolError, match="unsupported analytics tool"):
        execute_analytics_tool(
            session,
            tool_name="delete_transactions",
            arguments={},
        )

    assert not session.new
    assert not session.dirty
    assert not session.deleted


def test_summary_tool_passes_through_the_exact_api_result(
    client_and_session: tuple[TestClient, Session],
) -> None:
    client, session = client_and_session
    seed_transactions(session)
    arguments = {
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "account_name": "Sample Checking",
    }

    tool_result = execute_analytics_tool(
        session,
        tool_name=AnalyticsToolName.GET_SPENDING_SUMMARY,
        arguments=arguments,
    )
    api_result = client.get(
        "/analytics/spending/summary",
        params=arguments,
    )

    assert api_result.status_code == 200
    assert tool_result.model_dump(mode="json") == api_result.json()
    assert api_result.json()["total_spending"] == "350.45"


def test_every_approved_tool_is_read_only_and_returns_applied_evidence(
    client_and_session: tuple[TestClient, Session],
) -> None:
    _, session = client_and_session
    seed_transactions(session)
    calls: dict[AnalyticsToolName, dict[str, object]] = {
        AnalyticsToolName.GET_SPENDING_SUMMARY: {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        },
        AnalyticsToolName.GET_SPENDING_BY_CATEGORY: {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        },
        AnalyticsToolName.COMPARE_SPENDING_PERIODS: {
            "current_start_date": "2026-01-01",
            "current_end_date": "2026-01-31",
            "comparison_start_date": "2025-12-01",
            "comparison_end_date": "2025-12-31",
        },
        AnalyticsToolName.LIST_LARGE_TRANSACTIONS: {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "threshold": Decimal("100.00"),
            "limit": 10,
        },
    }

    results = {
        name: execute_analytics_tool(session, tool_name=name, arguments=arguments)
        for name, arguments in calls.items()
    }

    assert set(results) == set(AnalyticsToolName)
    for result in results.values():
        assert result.applied_filters
        assert result.semantics_version == "1.0"
        assert result.currency == "USD"
    large_result = results[AnalyticsToolName.LIST_LARGE_TRANSACTIONS]
    assert large_result.model_dump(mode="json")["items"][0]["import_provenance"]
    assert not session.new
    assert not session.dirty
    assert not session.deleted


def test_large_transaction_tool_rejects_floating_point_threshold(
    client_and_session: tuple[TestClient, Session],
) -> None:
    _, session = client_and_session

    with pytest.raises(ValidationError, match="Decimal, not float"):
        execute_analytics_tool(
            session,
            tool_name=AnalyticsToolName.LIST_LARGE_TRANSACTIONS,
            arguments={
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "threshold": 100.0,
            },
        )
