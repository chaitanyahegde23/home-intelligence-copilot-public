from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

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


class CategoryNotFoundError(Exception):
    pass


class CategoryNameConflictError(Exception):
    pass


class CategorizationRuleNotFoundError(Exception):
    pass


class TransactionNotFoundError(Exception):
    pass


class ImportBatchNotFoundError(Exception):
    pass


class InactiveCategoryError(Exception):
    pass


@dataclass(frozen=True)
class RuleConflict:
    transaction_id: UUID
    selected_rule_id: UUID
    matched_rule_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class CategorizationApplyResult:
    examined_count: int
    categorized_count: int
    updated_count: int
    unmatched_count: int
    manual_preserved_count: int
    conflicts: tuple[RuleConflict, ...]


def normalize_match_text(value: str) -> str:
    """Collapse surrounding/internal whitespace without changing case."""
    return " ".join(value.split())


def rule_matches(rule: CategorizationRule, transaction: Transaction) -> bool:
    raw_value = (
        transaction.description
        if rule.match_field is RuleMatchField.DESCRIPTION
        else transaction.merchant_name
    )
    if raw_value is None:
        return False

    value = normalize_match_text(raw_value)
    pattern = normalize_match_text(rule.pattern)
    if not rule.case_sensitive:
        value = value.casefold()
        pattern = pattern.casefold()

    if rule.match_type is RuleMatchType.EXACT:
        return value == pattern
    if rule.match_type is RuleMatchType.PREFIX:
        return value.startswith(pattern)
    return pattern in value


def list_categories(session: Session, *, include_inactive: bool) -> list[Category]:
    statement = select(Category)
    if not include_inactive:
        statement = statement.where(Category.is_active.is_(True))
    return list(session.scalars(statement.order_by(Category.name, Category.id)))


def create_category(
    session: Session,
    *,
    name: str,
    description: str | None,
    is_active: bool,
) -> Category:
    with session.begin():
        _ensure_category_name_available(session, name=name)
        category = Category(name=name, description=description, is_active=is_active)
        session.add(category)
        session.flush()
    return category


def update_category(
    session: Session,
    *,
    category_id: UUID,
    name: str | None,
    description: str | None,
    is_active: bool | None,
    fields_set: set[str],
) -> Category:
    with session.begin():
        category = session.scalar(
            select(Category)
            .options(
                selectinload(Category.assignments).selectinload(
                    TransactionCategoryAssignment.transaction
                )
            )
            .where(Category.id == category_id)
            .with_for_update()
        )
        if category is None:
            raise CategoryNotFoundError
        if "name" in fields_set:
            assert name is not None
            _ensure_category_name_available(session, name=name, excluded_category_id=category.id)
            category.name = name
            for assignment in category.assignments:
                assignment.transaction.category = name
        if "description" in fields_set:
            category.description = description
        if "is_active" in fields_set:
            assert is_active is not None
            category.is_active = is_active
        session.flush()
    return category


def list_rules(session: Session, *, include_inactive: bool) -> list[CategorizationRule]:
    statement = select(CategorizationRule).options(selectinload(CategorizationRule.category))
    if not include_inactive:
        statement = statement.where(CategorizationRule.is_active.is_(True))
    return list(
        session.scalars(statement.order_by(CategorizationRule.priority, CategorizationRule.id))
    )


def create_rule(
    session: Session,
    *,
    category_id: UUID,
    match_field: RuleMatchField,
    match_type: RuleMatchType,
    pattern: str,
    case_sensitive: bool,
    priority: int,
    is_active: bool,
) -> CategorizationRule:
    with session.begin():
        category = session.get(Category, category_id)
        if category is None:
            raise CategoryNotFoundError
        rule = CategorizationRule(
            category=category,
            match_field=match_field,
            match_type=match_type,
            pattern=normalize_match_text(pattern),
            case_sensitive=case_sensitive,
            priority=priority,
            is_active=is_active,
        )
        session.add(rule)
        session.flush()
    return rule


def update_rule(
    session: Session,
    *,
    rule_id: UUID,
    category_id: UUID | None,
    match_field: RuleMatchField | None,
    match_type: RuleMatchType | None,
    pattern: str | None,
    case_sensitive: bool | None,
    priority: int | None,
    is_active: bool | None,
    fields_set: set[str],
) -> CategorizationRule:
    with session.begin():
        rule = session.scalar(
            select(CategorizationRule)
            .options(
                selectinload(CategorizationRule.category),
                selectinload(CategorizationRule.assignments).selectinload(
                    TransactionCategoryAssignment.transaction
                ),
            )
            .where(CategorizationRule.id == rule_id)
            .with_for_update()
        )
        if rule is None:
            raise CategorizationRuleNotFoundError
        if "category_id" in fields_set:
            assert category_id is not None
            category = session.get(Category, category_id)
            if category is None:
                raise CategoryNotFoundError
            rule.category = category
            for assignment in rule.assignments:
                assignment.category = category
                assignment.transaction.category = category.name
        if "match_field" in fields_set:
            assert match_field is not None
            rule.match_field = match_field
        if "match_type" in fields_set:
            assert match_type is not None
            rule.match_type = match_type
        if "pattern" in fields_set:
            assert pattern is not None
            rule.pattern = normalize_match_text(pattern)
        if "case_sensitive" in fields_set:
            assert case_sensitive is not None
            rule.case_sensitive = case_sensitive
        if "priority" in fields_set:
            assert priority is not None
            rule.priority = priority
        if "is_active" in fields_set:
            assert is_active is not None
            rule.is_active = is_active
        session.flush()
    return rule


def set_manual_category(
    session: Session,
    *,
    transaction_id: UUID,
    category_id: UUID,
    note: str | None,
) -> TransactionCategoryAssignment:
    with session.begin():
        transaction = session.scalar(
            select(Transaction)
            .options(selectinload(Transaction.category_assignment))
            .where(Transaction.id == transaction_id)
            .with_for_update()
        )
        if transaction is None:
            raise TransactionNotFoundError
        category = session.get(Category, category_id)
        if category is None:
            raise CategoryNotFoundError
        if not category.is_active:
            raise InactiveCategoryError

        assignment = transaction.category_assignment
        if assignment is None:
            assignment = TransactionCategoryAssignment(
                transaction=transaction,
                category=category,
                source=CategoryAssignmentSource.MANUAL,
                note=note,
            )
            session.add(assignment)
        else:
            assignment.category = category
            assignment.source = CategoryAssignmentSource.MANUAL
            assignment.rule = None
            assignment.note = note
        transaction.category = category.name
        session.flush()
    return assignment


def apply_categorization(
    session: Session,
    *,
    import_batch_id: UUID | None,
) -> CategorizationApplyResult:
    with session.begin():
        if import_batch_id is not None and session.get(ImportBatch, import_batch_id) is None:
            raise ImportBatchNotFoundError

        rules = list(
            session.scalars(
                select(CategorizationRule)
                .join(CategorizationRule.category)
                .options(selectinload(CategorizationRule.category))
                .where(
                    CategorizationRule.is_active.is_(True),
                    Category.is_active.is_(True),
                )
                .order_by(CategorizationRule.priority, CategorizationRule.id)
            )
        )
        transaction_statement = (
            select(Transaction)
            .options(selectinload(Transaction.category_assignment))
            .order_by(Transaction.id)
            .with_for_update()
        )
        if import_batch_id is not None:
            transaction_statement = transaction_statement.where(
                Transaction.import_batch_id == import_batch_id
            )
        transactions = list(session.scalars(transaction_statement))

        categorized_count = 0
        updated_count = 0
        unmatched_count = 0
        manual_preserved_count = 0
        conflicts: list[RuleConflict] = []

        for transaction in transactions:
            assignment = transaction.category_assignment
            if assignment is not None and assignment.source is CategoryAssignmentSource.MANUAL:
                manual_preserved_count += 1
                continue

            matching_rules = [rule for rule in rules if rule_matches(rule, transaction)]
            if not matching_rules:
                unmatched_count += 1
                if assignment is not None and assignment.source is CategoryAssignmentSource.RULE:
                    session.delete(assignment)
                    transaction.category = None
                    updated_count += 1
                continue

            categorized_count += 1
            selected_rule = matching_rules[0]
            if len(matching_rules) > 1:
                conflicts.append(
                    RuleConflict(
                        transaction_id=transaction.id,
                        selected_rule_id=selected_rule.id,
                        matched_rule_ids=tuple(rule.id for rule in matching_rules),
                    )
                )

            changed = (
                assignment is None
                or assignment.source is not CategoryAssignmentSource.RULE
                or assignment.rule_id != selected_rule.id
                or assignment.category_id != selected_rule.category_id
                or transaction.category != selected_rule.category.name
            )
            if assignment is None:
                assignment = TransactionCategoryAssignment(
                    transaction=transaction,
                    category=selected_rule.category,
                    source=CategoryAssignmentSource.RULE,
                    rule=selected_rule,
                )
                session.add(assignment)
            else:
                assignment.category = selected_rule.category
                assignment.source = CategoryAssignmentSource.RULE
                assignment.rule = selected_rule
                assignment.note = None
            transaction.category = selected_rule.category.name
            if changed:
                updated_count += 1

        session.flush()

    return CategorizationApplyResult(
        examined_count=len(transactions),
        categorized_count=categorized_count,
        updated_count=updated_count,
        unmatched_count=unmatched_count,
        manual_preserved_count=manual_preserved_count,
        conflicts=tuple(conflicts),
    )


def _ensure_category_name_available(
    session: Session,
    *,
    name: str,
    excluded_category_id: UUID | None = None,
) -> None:
    statement = select(Category.id).where(Category.name == name)
    if excluded_category_id is not None:
        statement = statement.where(Category.id != excluded_category_id)
    if session.scalar(statement) is not None:
        raise CategoryNameConflictError
