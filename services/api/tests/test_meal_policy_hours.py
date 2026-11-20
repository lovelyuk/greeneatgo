"""Company meal hours: which windows are stored, and who they restrict."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.routers.admin import _meal_policy_data, _policy_windows
from app.routers.pay import _policy_from_row
from app.schemas import MealPolicyUpdateRequest
from app.services.policy_engine import evaluate_payment_policy

KST = ZoneInfo("Asia/Seoul")


def _at(hhmm: str) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return datetime(2026, 11, 18, hour, minute, tzinfo=KST)  # a Wednesday


def _allowed(windows, hhmm):
    policy = _policy_from_row({"meal_windows": windows, "daily_limit": None, "weekend_allowed": True})
    return evaluate_payment_policy(amount=8000, spent_today=0, policy=policy, now=_at(hhmm))


def test_both_windows_restrict_company_meals_to_those_hours():
    windows = _policy_windows(MealPolicyUpdateRequest(enabled=True, lunch_start="11:30", lunch_end="13:30", dinner_start="18:00", dinner_end="19:30"))
    assert [(w["name"], w["start"], w["end"]) for w in windows] == [("중식", "11:30", "13:30"), ("석식", "18:00", "19:30")]
    assert _allowed(windows, "12:00").ok and _allowed(windows, "18:00").ok and _allowed(windows, "19:30").ok
    refused = _allowed(windows, "15:00")
    assert (refused.ok, refused.code) == (False, "OUT_OF_WINDOW")
    assert "중식 11:30~13:30, 석식 18:00~19:30" in refused.message
    assert _meal_policy_data({"meal_windows": windows}) == {
        "enabled": True, "lunch_enabled": True, "dinner_enabled": True,
        "lunch_start": "11:30", "lunch_end": "13:30", "dinner_start": "18:00", "dinner_end": "19:30"}


def test_one_window_can_be_switched_off():
    lunch_only = _policy_windows(MealPolicyUpdateRequest(enabled=True, dinner_enabled=False))
    assert [w["name"] for w in lunch_only] == ["중식"]
    assert _allowed(lunch_only, "12:00").ok
    assert _allowed(lunch_only, "18:30").code == "OUT_OF_WINDOW"
    data = _meal_policy_data({"meal_windows": lunch_only})
    assert (data["enabled"], data["lunch_enabled"], data["dinner_enabled"]) == (True, True, False)
    # The switched-off window keeps a sensible default for when it is turned on again.
    assert (data["dinner_start"], data["dinner_end"]) == ("17:30", "20:30")
    dinner_only = _policy_windows(MealPolicyUpdateRequest(enabled=True, lunch_enabled=False))
    assert _allowed(dinner_only, "12:00").code == "OUT_OF_WINDOW" and _allowed(dinner_only, "18:30").ok


def test_restriction_off_means_any_time():
    windows = _policy_windows(MealPolicyUpdateRequest(enabled=False, lunch_start="12:00", lunch_end="12:30"))
    assert [w["name"] for w in windows] == ["상시"]
    assert _allowed(windows, "03:00").ok and _allowed(windows, "23:59").ok
    data = _meal_policy_data({"meal_windows": windows})
    assert (data["enabled"], data["lunch_enabled"], data["dinner_enabled"]) == (False, True, True)
    assert _meal_policy_data(None)["enabled"] is False
    assert _allowed([], "03:00").ok  # no policy row at all


def test_invalid_hours_are_rejected_before_they_are_stored():
    for body in (
        {"enabled": True, "lunch_start": "25:00"}, {"enabled": True, "lunch_end": "12:60"}, {"enabled": True, "dinner_start": "9:00"},
        {"enabled": True, "lunch_start": "14:00", "lunch_end": "11:00"}, {"enabled": True, "dinner_start": "18:00", "dinner_end": "18:00"},
        {"enabled": True, "lunch_enabled": False, "dinner_enabled": False},
    ):
        with pytest.raises(ValidationError):
            MealPolicyUpdateRequest(**body)
    # A window that is switched off, or the whole restriction being off, is not checked for order.
    MealPolicyUpdateRequest(enabled=True, dinner_enabled=False, dinner_start="20:00", dinner_end="19:00")
    MealPolicyUpdateRequest(enabled=False, lunch_start="14:00", lunch_end="11:00")


def test_an_unreadable_stored_window_never_breaks_payment():
    windows = [{"name": "중식", "start": "99:99", "end": "14:00"}, {"name": "석식", "start": "17:30", "end": "20:30"}]
    assert _allowed(windows, "18:00").ok
    assert _allowed(windows, "12:00").code == "OUT_OF_WINDOW"
    # Nothing readable left: fall back to unrestricted rather than refusing every meal.
    assert _allowed([{"name": "중식", "start": "xx", "end": "yy"}], "03:00").ok


def test_personal_and_subsidized_vouchers_do_not_pass_through_the_hours_check():
    """consume_meal sends only company-ledger meals to pay(), where the hours are checked."""
    import inspect
    from app.routers import transactions
    source = inspect.getsource(transactions.consume_meal)
    personal = source.index('pay_source == "personal"')
    ledger_call = source.index("ledger_amount")
    assert personal < ledger_call
    assert "evaluate_payment_policy" not in source
