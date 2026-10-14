"""Operator-reviewed evidence is not provider lookup or an automatic no-charge claim."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class ReviewedAttempt(BaseModel):
    model_config = ConfigDict(extra='forbid')
    transaction_id: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')
    outcome: Literal['failed', 'canceled', 'pending', 'approved']


class FailedOrderReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: UUID
    amount: int = Field(strict=True, gt=0)
    outcome: Literal['failed', 'canceled']
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    source_reference: str = Field(min_length=12, max_length=500)
    attempts: list[ReviewedAttempt] = Field(max_length=1000)
    authority: Literal['attempt_only', 'no_issued_form', 'trusted_provider_irreversible_closure']
    complete_attempt_coverage: StrictBool = False
    irreversible_no_future_approval: StrictBool = False
    provider_closure_reference: str | None = Field(default=None, min_length=12, max_length=500)
    dry_run: StrictBool = True

    @model_validator(mode='after')
    def validate_attestation(self):
        if len(self.source_reference.strip()) < 12 or (self.provider_closure_reference is not None and len(self.provider_closure_reference.strip()) < 12):
            raise ValueError('substantive secured evidence reference required')
        ids = [a.transaction_id for a in self.attempts]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate attempt identity')
        if self.authority == 'trusted_provider_irreversible_closure' and not (
            self.complete_attempt_coverage and self.irreversible_no_future_approval
            and self.provider_closure_reference and all(a.outcome in {'failed','canceled'} for a in self.attempts)
        ):
            raise ValueError('complete trusted irreversible provider closure required')
        if self.authority == 'no_issued_form' and self.attempts:
            raise ValueError('attempts contradict no issued form')
        return self
