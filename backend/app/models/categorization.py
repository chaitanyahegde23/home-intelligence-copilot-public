from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import HouseholdOwnedMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.transaction import Transaction


class RuleMatchField(StrEnum):
    DESCRIPTION = "description"
    MERCHANT_NAME = "merchant_name"


class RuleMatchType(StrEnum):
    EXACT = "exact"
    PREFIX = "prefix"
    CONTAINS = "contains"


class CategoryAssignmentSource(StrEnum):
    IMPORTED = "imported"
    RULE = "rule"
    MANUAL = "manual"


class Category(HouseholdOwnedMixin, TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint(
            "description IS NULL OR length(trim(description)) > 0",
            name="description_not_blank",
        ),
        UniqueConstraint("household_id", "name", name="uq_categories_household_name"),
        Index("ix_categories_is_active", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    rules: Mapped[list[CategorizationRule]] = relationship(back_populates="category")
    assignments: Mapped[list[TransactionCategoryAssignment]] = relationship(
        back_populates="category"
    )


class CategorizationRule(HouseholdOwnedMixin, TimestampMixin, Base):
    __tablename__ = "categorization_rules"
    __table_args__ = (
        CheckConstraint("length(trim(pattern)) > 0", name="pattern_not_blank"),
        CheckConstraint("priority >= 0", name="priority_non_negative"),
        Index("ix_categorization_rules_category_id", "category_id"),
        Index("ix_categorization_rules_is_active_priority", "is_active", "priority"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    category_id: Mapped[UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    match_field: Mapped[RuleMatchField] = mapped_column(
        SqlEnum(
            RuleMatchField,
            name="categorization_rule_match_field",
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        nullable=False,
    )
    match_type: Mapped[RuleMatchType] = mapped_column(
        SqlEnum(
            RuleMatchType,
            name="categorization_rule_match_type",
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        nullable=False,
    )
    pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    case_sensitive: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        default=100,
        server_default="100",
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    category: Mapped[Category] = relationship(back_populates="rules")
    assignments: Mapped[list[TransactionCategoryAssignment]] = relationship(back_populates="rule")

    @property
    def precedence_key(self) -> tuple[int, UUID]:
        return self.priority, self.id


class TransactionCategoryAssignment(HouseholdOwnedMixin, TimestampMixin, Base):
    __tablename__ = "transaction_category_assignments"
    __table_args__ = (
        CheckConstraint(
            "(source = 'rule' AND rule_id IS NOT NULL) OR "
            "(source IN ('imported', 'manual') AND rule_id IS NULL)",
            name="source_rule_consistent",
        ),
        CheckConstraint(
            "note IS NULL OR length(trim(note)) > 0",
            name="note_not_blank",
        ),
        UniqueConstraint("transaction_id"),
        Index("ix_transaction_category_assignments_category_id", "category_id"),
        Index("ix_transaction_category_assignments_rule_id", "rule_id"),
        Index("ix_transaction_category_assignments_source", "source"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "transactions.id",
            name="fk_tx_category_assignments_transaction_id_transactions",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    category_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "categories.id",
            name="fk_tx_category_assignments_category_id_categories",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    source: Mapped[CategoryAssignmentSource] = mapped_column(
        SqlEnum(
            CategoryAssignmentSource,
            name="category_assignment_source",
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        nullable=False,
    )
    rule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "categorization_rules.id",
            name="fk_tx_category_assignments_rule_id_rules",
            ondelete="RESTRICT",
        )
    )
    note: Mapped[str | None] = mapped_column(Text)

    transaction: Mapped[Transaction] = relationship(back_populates="category_assignment")
    category: Mapped[Category] = relationship(back_populates="assignments")
    rule: Mapped[CategorizationRule | None] = relationship(back_populates="assignments")
