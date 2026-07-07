from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import random

from app.services.geo import gps_far_flag
from app.services.policy_engine import MealPolicy, evaluate_payment_policy

@dataclass(frozen=True)
class MerchantSnapshot:
    id: str
    name: str
    lat: float | None
    lng: float | None

@dataclass(frozen=True)
class PaymentContext:
    user_id: str
    company_id: str
    merchant: MerchantSnapshot
    amount: int
    balance: int
    spent_today: int
    policy: MealPolicy
    now: datetime
    gps_lat: float | None = None
    gps_lng: float | None = None

@dataclass(frozen=True)
class PaymentDraft:
    ok: bool
    code: str | None
    message: str | None
    meal_window: str | None = None
    tx_code: str | None = None
    flags: dict | None = None


def generate_tx_code() -> str:
    # 실제 운영에서는 DB unique retry 또는 Postgres 함수에서 발급한다.
    return f"{random.randint(0, 999999):06d}"


def prepare_payment_draft(ctx: PaymentContext) -> PaymentDraft:
    result = evaluate_payment_policy(
        amount=ctx.amount,
        balance=ctx.balance,
        spent_today=ctx.spent_today,
        policy=ctx.policy,
        now=ctx.now,
    )
    if not result.ok:
        return PaymentDraft(False, result.code, result.message, result.meal_window)

    flags = {
        "gps_far": gps_far_flag(ctx.gps_lat, ctx.gps_lng, ctx.merchant.lat, ctx.merchant.lng)
    }
    return PaymentDraft(True, None, None, result.meal_window, generate_tx_code(), flags)
