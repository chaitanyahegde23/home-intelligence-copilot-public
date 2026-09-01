from __future__ import annotations

from typing import Any

from sqlalchemy import event, select
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.core.household import BOOTSTRAP_HOUSEHOLD_ID, get_current_household_id
from app.models.auth import Household
from app.models.mixins import HouseholdOwnedMixin

SESSION_HOUSEHOLD_KEY = "household_id"
INCLUDE_ALL_HOUSEHOLDS = "include_all_households"


class HouseholdScopeViolation(RuntimeError):
    pass


@event.listens_for(Session, "do_orm_execute")
def apply_household_scope(execute_state: ORMExecuteState) -> None:
    if execute_state.execution_options.get(INCLUDE_ALL_HOUSEHOLDS, False):
        return
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return
    household_id = execute_state.session.info.get(SESSION_HOUSEHOLD_KEY, get_current_household_id())
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            HouseholdOwnedMixin,
            lambda model: model.household_id == household_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def validate_household_writes(
    session: Session,
    flush_context: object,
    instances: object,
) -> None:
    del flush_context, instances
    household_id = session.info.get(SESSION_HOUSEHOLD_KEY, get_current_household_id())
    owned_objects = [
        item
        for collection in (session.new, session.dirty, session.deleted)
        for item in collection
        if isinstance(item, HouseholdOwnedMixin)
    ]
    if not owned_objects:
        return

    if household_id == BOOTSTRAP_HOUSEHOLD_ID and not _bootstrap_household_exists(session):
        session.add(
            Household(
                id=BOOTSTRAP_HOUSEHOLD_ID,
                display_name="Local household",
                is_active=True,
            )
        )

    for item in owned_objects:
        item_household_id = item.household_id
        if item_household_id is None and item in session.new:
            item.household_id = household_id
        elif item_household_id != household_id:
            raise HouseholdScopeViolation("cross-household write denied")
    for item in owned_objects:
        _validate_parent_households(session, item, household_id)


def _validate_parent_households(
    session: Session, item: HouseholdOwnedMixin, household_id: object
) -> None:
    from app.models.auth import AuthSession, User
    from app.models.categorization import (
        CategorizationRule,
        Category,
        TransactionCategoryAssignment,
    )
    from app.models.document import Document
    from app.models.document_chunk import DocumentChunk
    from app.models.document_extraction import DocumentExtraction, DocumentTextSpan
    from app.models.document_fact import DocumentFact
    from app.models.document_metadata import DocumentMetadataInference
    from app.models.document_reminder import DocumentExpirationReminder
    from app.models.duplicate_candidate import DuplicateCandidate
    from app.models.gmail_ingestion import GmailIngestion
    from app.models.import_batch import ImportBatch
    from app.models.transaction import Transaction

    references: tuple[tuple[type[Any], str, str, type[Any]], ...] = (
        (Transaction, "import_batch_id", "import_batch", ImportBatch),
        (CategorizationRule, "category_id", "category", Category),
        (
            TransactionCategoryAssignment,
            "transaction_id",
            "transaction",
            Transaction,
        ),
        (TransactionCategoryAssignment, "category_id", "category", Category),
        (TransactionCategoryAssignment, "rule_id", "rule", CategorizationRule),
        (
            DuplicateCandidate,
            "first_transaction_id",
            "first_transaction",
            Transaction,
        ),
        (
            DuplicateCandidate,
            "second_transaction_id",
            "second_transaction",
            Transaction,
        ),
        (DocumentExtraction, "document_id", "document", Document),
        (DocumentTextSpan, "extraction_id", "extraction", DocumentExtraction),
        (DocumentChunk, "document_id", "document", Document),
        (DocumentChunk, "extraction_id", "extraction", DocumentExtraction),
        (DocumentChunk, "text_span_id", "text_span", DocumentTextSpan),
        (DocumentMetadataInference, "document_id", "document", Document),
        (DocumentFact, "document_id", "document", Document),
        (DocumentFact, "extraction_id", "extraction", DocumentExtraction),
        (DocumentExpirationReminder, "document_id", "document", Document),
        (GmailIngestion, "document_id", "document", Document),
        (
            DocumentMetadataInference,
            "extraction_id",
            "extraction",
            DocumentExtraction,
        ),
        (AuthSession, "user_id", "user", User),
    )
    for child_type, foreign_key_name, relationship_name, parent_type in references:
        if not isinstance(item, child_type):
            continue
        parent = item.__dict__.get(relationship_name)
        if parent is not None:
            parent_household_id = parent.household_id
        else:
            parent_id = getattr(item, foreign_key_name)
            if parent_id is None:
                continue
            pending_parent = next(
                (
                    candidate
                    for candidate in session.new
                    if isinstance(candidate, parent_type) and candidate.id == parent_id
                ),
                None,
            )
            parent_household_id = (
                pending_parent.household_id
                if pending_parent is not None
                else session.scalar(
                    select(parent_type.household_id)
                    .where(parent_type.id == parent_id)
                    .execution_options(**{INCLUDE_ALL_HOUSEHOLDS: True})
                )
            )
        if parent_household_id != household_id:
            raise HouseholdScopeViolation("cross-household relationship denied")


def _bootstrap_household_exists(session: Session) -> bool:
    if any(
        isinstance(item, Household) and item.id == BOOTSTRAP_HOUSEHOLD_ID for item in session.new
    ):
        return True
    return (
        session.scalar(
            select(Household.id)
            .where(Household.id == BOOTSTRAP_HOUSEHOLD_ID)
            .execution_options(**{INCLUDE_ALL_HOUSEHOLDS: True})
        )
        is not None
    )
