from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RequiredDescription = Annotated[str, Field(min_length=1)]
RequiredSourceFile = Annotated[str, Field(min_length=1, max_length=512)]
Money = Annotated[Decimal, Field(max_digits=18, decimal_places=2)]


class TransactionCreate(BaseModel):
    import_batch_id: UUID
    account_name: str | None = None
    transaction_date: date
    posted_date: date | None = None
    description: RequiredDescription
    merchant_name: str | None = None
    amount: Money
    transaction_type: str | None = None
    category: str | None = None
    source_file: RequiredSourceFile


class TransactionRead(TransactionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
