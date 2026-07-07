from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

@dataclass(frozen=True)
class MealWindow:
    name: str
    start: str
    end: str
    per_meal_limit: int

@dataclass(frozen=True)
class MealPolicy:
    meal_windows: tuple[MealWindow, ...]
    daily_limit: int | None = None
    weekend_allowed: bool = False

@dataclass(frozen=True)
class PolicyResult:
    ok: bool
    code: str | None = None
    message: str | None = None
    meal_window: str | None = None

DEFAULT_WINDOWS = (
    MealWindow("중식", "11:00", "14:00", 10_000),
    MealWindow("석식", "17:30", "20:30", 12_000),
)

ERROR_MESSAGES = {
    "OUT_OF_WINDOW": "지금은 식대 사용 시간이 아니에요",
    "MEAL_LIMIT": "1식 한도를 초과했어요. 초과분은 개인 결제해 주세요",
    "DAILY_LIMIT": "오늘 식대 한도를 초과했어요",
    "WEEKEND_BLOCKED": "주말에는 식대 사용이 제한되어 있어요",
    "INSUFFICIENT": "잔액이 부족해요",
}

def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))

def _in_window(now_t: time, start: str, end: str) -> bool:
    start_t = _parse_hhmm(start)
    end_t = _parse_hhmm(end)
    if start_t <= end_t:
        return start_t <= now_t <= end_t
    return now_t >= start_t or now_t <= end_t

def evaluate_payment_policy(*, amount: int, balance: int, spent_today: int, policy: MealPolicy, now: datetime) -> PolicyResult:
    """Pure policy judgment for payment. DB/API layers must call this before writing ledger rows."""
    local_now = now.astimezone(KST) if now.tzinfo else now.replace(tzinfo=KST)

    if local_now.weekday() >= 5 and not policy.weekend_allowed:
        return PolicyResult(False, "WEEKEND_BLOCKED", ERROR_MESSAGES["WEEKEND_BLOCKED"])

    matched = next((w for w in policy.meal_windows if _in_window(local_now.time(), w.start, w.end)), None)
    if matched is None:
        ranges = ", ".join(f"{w.name} {w.start}~{w.end}" for w in policy.meal_windows)
        return PolicyResult(False, "OUT_OF_WINDOW", f"지금은 식대 사용 시간이 아니에요 ({ranges})")

    if amount > matched.per_meal_limit:
        return PolicyResult(False, "MEAL_LIMIT", f"1식 한도는 {matched.per_meal_limit:,}원이에요. 초과분은 개인 결제해 주세요", matched.name)

    if policy.daily_limit is not None and spent_today + amount > policy.daily_limit:
        return PolicyResult(False, "DAILY_LIMIT", ERROR_MESSAGES["DAILY_LIMIT"], matched.name)

    if balance < amount:
        shortage = amount - balance
        return PolicyResult(False, "INSUFFICIENT", f"잔액이 부족해요. 현재 잔액 {balance:,}원, 부족액 {shortage:,}원", matched.name)

    return PolicyResult(True, meal_window=matched.name)
