from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import (
    CategorizationApplyRequest,
    CategorizationApplyResponse,
    CategorizationConflictRead,
    CategorizationRuleCreate,
    CategorizationRuleRead,
    CategorizationRuleUpdate,
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    ManualCategoryAssignmentRequest,
    TransactionCategoryAssignmentRead,
)
from app.services.categorization import (
    CategorizationRuleNotFoundError,
    CategoryNameConflictError,
    CategoryNotFoundError,
    ImportBatchNotFoundError,
    InactiveCategoryError,
    TransactionNotFoundError,
    apply_categorization,
    create_category,
    create_rule,
    list_categories,
    list_rules,
    set_manual_category,
    update_category,
    update_rule,
)

router = APIRouter(tags=["categorization"])


@router.get("/categories", response_model=list[CategoryRead])
def retrieve_categories(
    session: Annotated[Session, Depends(get_db)],
    include_inactive: Annotated[bool, Query()] = False,
) -> list[CategoryRead]:
    return [
        CategoryRead.model_validate(category)
        for category in list_categories(session, include_inactive=include_inactive)
    ]


@router.post(
    "/categories",
    response_model=CategoryRead,
    status_code=status.HTTP_201_CREATED,
)
def add_category(
    payload: CategoryCreate,
    session: Annotated[Session, Depends(get_db)],
) -> CategoryRead:
    try:
        category = create_category(session, **payload.model_dump())
    except CategoryNameConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Category name already exists",
        ) from error
    return CategoryRead.model_validate(category)


@router.patch("/categories/{category_id}", response_model=CategoryRead)
def change_category(
    category_id: UUID,
    payload: CategoryUpdate,
    session: Annotated[Session, Depends(get_db)],
) -> CategoryRead:
    try:
        category = update_category(
            session,
            category_id=category_id,
            name=payload.name,
            description=payload.description,
            is_active=payload.is_active,
            fields_set=set(payload.model_fields_set),
        )
    except CategoryNotFoundError as error:
        raise category_not_found() from error
    except CategoryNameConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Category name already exists",
        ) from error
    return CategoryRead.model_validate(category)


@router.get("/categorization-rules", response_model=list[CategorizationRuleRead])
def retrieve_rules(
    session: Annotated[Session, Depends(get_db)],
    include_inactive: Annotated[bool, Query()] = False,
) -> list[CategorizationRuleRead]:
    return [
        CategorizationRuleRead.model_validate(rule)
        for rule in list_rules(session, include_inactive=include_inactive)
    ]


@router.post(
    "/categorization-rules",
    response_model=CategorizationRuleRead,
    status_code=status.HTTP_201_CREATED,
)
def add_rule(
    payload: CategorizationRuleCreate,
    session: Annotated[Session, Depends(get_db)],
) -> CategorizationRuleRead:
    try:
        rule = create_rule(session, **payload.model_dump())
    except CategoryNotFoundError as error:
        raise category_not_found() from error
    return CategorizationRuleRead.model_validate(rule)


@router.patch(
    "/categorization-rules/{rule_id}",
    response_model=CategorizationRuleRead,
)
def change_rule(
    rule_id: UUID,
    payload: CategorizationRuleUpdate,
    session: Annotated[Session, Depends(get_db)],
) -> CategorizationRuleRead:
    try:
        rule = update_rule(
            session,
            rule_id=rule_id,
            category_id=payload.category_id,
            match_field=payload.match_field,
            match_type=payload.match_type,
            pattern=payload.pattern,
            case_sensitive=payload.case_sensitive,
            priority=payload.priority,
            is_active=payload.is_active,
            fields_set=set(payload.model_fields_set),
        )
    except CategorizationRuleNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Categorization rule not found",
        ) from error
    except CategoryNotFoundError as error:
        raise category_not_found() from error
    return CategorizationRuleRead.model_validate(rule)


@router.put(
    "/transactions/{transaction_id}/category-assignment",
    response_model=TransactionCategoryAssignmentRead,
)
def assign_manual_category(
    transaction_id: UUID,
    payload: ManualCategoryAssignmentRequest,
    session: Annotated[Session, Depends(get_db)],
) -> TransactionCategoryAssignmentRead:
    try:
        assignment = set_manual_category(
            session,
            transaction_id=transaction_id,
            category_id=payload.category_id,
            note=payload.note,
        )
    except TransactionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        ) from error
    except CategoryNotFoundError as error:
        raise category_not_found() from error
    except InactiveCategoryError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Inactive categories cannot be assigned manually",
        ) from error
    return TransactionCategoryAssignmentRead.model_validate(assignment)


@router.post("/categorization/apply", response_model=CategorizationApplyResponse)
def apply_rules(
    payload: CategorizationApplyRequest,
    session: Annotated[Session, Depends(get_db)],
) -> CategorizationApplyResponse:
    try:
        result = apply_categorization(
            session,
            import_batch_id=payload.import_batch_id,
        )
    except ImportBatchNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import batch not found",
        ) from error
    conflicts = tuple(
        CategorizationConflictRead(
            transaction_id=conflict.transaction_id,
            selected_rule_id=conflict.selected_rule_id,
            matched_rule_ids=conflict.matched_rule_ids,
        )
        for conflict in result.conflicts
    )
    return CategorizationApplyResponse(
        examined_count=result.examined_count,
        categorized_count=result.categorized_count,
        updated_count=result.updated_count,
        unmatched_count=result.unmatched_count,
        manual_preserved_count=result.manual_preserved_count,
        conflict_count=len(conflicts),
        conflicts=conflicts,
    )


def category_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Category not found",
    )
