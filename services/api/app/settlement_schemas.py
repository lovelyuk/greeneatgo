from datetime import date, datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator


class ConfirmTaxInvoiceRequest(BaseModel):
    business_info_accurate: Literal[True] = Field(
        validation_alias=AliasChoices("business_info_accurate", "business_information_accurate")
    )
    email_accurate: Literal[True] = Field(
        validation_alias=AliasChoices("email_accurate", "tax_email_accurate")
    )
    amount_checked: Literal[True]


class SettlementDisputeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("reason", "idempotency_key")
    @classmethod
    def non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class SettlementPeriodUpdateRequest(BaseModel):
    period_from: date
    period_to: date
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_idempotency_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class SettlementPaymentRequest(BaseModel):
    amount: int = Field(gt=0)
    depositor_name: str = Field(min_length=1, max_length=100)
    deposited_at: datetime
    memo: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("depositor_name", "idempotency_key")
    @classmethod
    def required_non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("memo")
    @classmethod
    def normalize_memo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None
