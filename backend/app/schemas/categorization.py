from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.categorization import (
    CategoryAssignmentSource,
    RuleMatchField,
    RuleMatchType,
)

CategoryName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
CategoryDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]
RulePattern = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
AssignmentNote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CategoryName
    description: CategoryDescription | None = None
    is_active: bool = True


class CategoryRead(CategoryCreate):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class CategorizationRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID
    match_field: RuleMatchField
    match_type: RuleMatchType
    pattern: RulePattern
    case_sensitive: bool = False
    priority: int = Field(default=100, ge=0)
    is_active: bool = True


class CategorizationRuleRead(CategorizationRuleCreate):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class TransactionCategoryAssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: UUID
    category_id: UUID
    source: CategoryAssignmentSource
    rule_id: UUID | None = None
    note: AssignmentNote | None = None

    @model_validator(mode="after")
    def validate_source_rule(self) -> Self:
        if self.source is CategoryAssignmentSource.RULE and self.rule_id is None:
            raise ValueError("rule assignments require rule_id")
        if self.source is not CategoryAssignmentSource.RULE and self.rule_id is not None:
            raise ValueError("only rule assignments may include rule_id")
        return self


class TransactionCategoryAssignmentRead(TransactionCategoryAssignmentCreate):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class CategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CategoryName | None = None
    description: CategoryDescription | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one category field is required")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        if "is_active" in self.model_fields_set and self.is_active is None:
            raise ValueError("is_active cannot be null")
        return self


class CategorizationRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID | None = None
    match_field: RuleMatchField | None = None
    match_type: RuleMatchType | None = None
    pattern: RulePattern | None = None
    case_sensitive: bool | None = None
    priority: int | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one rule field is required")
        nullable_fields = self.model_fields_set - {"pattern"}
        if any(getattr(self, field) is None for field in nullable_fields):
            raise ValueError("rule fields cannot be null")
        if "pattern" in self.model_fields_set and self.pattern is None:
            raise ValueError("pattern cannot be null")
        return self


class ManualCategoryAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID
    note: AssignmentNote | None = None


class CategorizationApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    import_batch_id: UUID | None = None


class CategorizationConflictRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: UUID
    selected_rule_id: UUID
    matched_rule_ids: tuple[UUID, ...]


class CategorizationApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    examined_count: int = Field(ge=0)
    categorized_count: int = Field(ge=0)
    updated_count: int = Field(ge=0)
    unmatched_count: int = Field(ge=0)
    manual_preserved_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    conflicts: tuple[CategorizationConflictRead, ...]

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.conflict_count != len(self.conflicts):
            raise ValueError("conflict_count must equal conflicts length")
        if (
            self.categorized_count + self.unmatched_count + self.manual_preserved_count
            != self.examined_count
        ):
            raise ValueError("categorization outcome counts must reconcile")
        if self.updated_count > self.categorized_count + self.unmatched_count:
            raise ValueError("updated_count cannot exceed automatic outcomes")
        return self
