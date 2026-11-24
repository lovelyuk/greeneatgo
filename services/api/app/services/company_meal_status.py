"""Whether a ledger employee can use the company's meal allowance right now.

Shown on the app home card before the employee walks to the counter. It applies the
same rules as the payment path (`routers/pay.py` + `process_meal_pay`): monthly and
daily limits, weekend rule, meal hours. The meal price is unknown here, so a limit
blocks only when nothing is left.

Time-dependent parts (`weekend_allowed`, `windows`) are returned as data too, so the
app can keep the card correct while it stays open across a window boundary.
"""
from __future__ import annotations

from datetime import datetime

from app.services.policy_engine import MealPolicy, evaluate_payment_policy

_FULL_DAY = ("00:00", "23:59")


def company_meal_status(
    *,
    policy: MealPolicy,
    now: datetime,
    spent_today: int,
    spent_month: int,
    monthly_limit: int,
    company_active: bool = True,
) -> dict:
    windows = [
        {"name": window.name, "start": window.start, "end": window.end}
        for window in policy.meal_windows
        if (window.start, window.end) != _FULL_DAY
    ]
    # A full-day window next to others means "any time": nothing to list.
    if len(windows) != len(policy.meal_windows):
        windows = []

    limit_block = None
    if not company_active:
        limit_block = {"code": "COMPANY_NOT_ACTIVE", "message": "회사 계정이 아직 활성화되지 않았어요"}
    elif spent_month >= monthly_limit:
        limit_block = {"code": "MONTHLY_LIMIT", "message": (
            f"이번 달 한도 {monthly_limit:,}원을 모두 썼어요" if monthly_limit > 0 else "회사 식대 한도가 0원으로 설정돼 있어요")}
    elif policy.daily_limit is not None and spent_today >= policy.daily_limit:
        limit_block = {"code": "DAILY_LIMIT", "message": f"오늘 한도 {policy.daily_limit:,}원을 모두 썼어요"}

    timing = evaluate_payment_policy(amount=0, spent_today=0, policy=policy, now=now)
    code = limit_block["code"] if limit_block else (None if timing.ok else timing.code)
    return {
        "available": code is None,
        "code": code,
        "limit_block": limit_block,
        "restricted": bool(windows),
        "windows": windows,
        "weekend_allowed": bool(policy.weekend_allowed),
        "current_window": timing.meal_window if timing.ok and windows else None,
    }
