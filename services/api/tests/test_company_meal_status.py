"""Home-card status for ledger employees: can the company allowance be used now?"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.repositories.supabase_http import SupabaseHttpError
from app.routers import me
from app.routers.pay import _policy_from_row
from app.services.company_meal_status import company_meal_status
from app.services.policy_engine import evaluate_payment_policy

KST = ZoneInfo("Asia/Seoul")
LUNCH_DINNER = [{"name": "중식", "start": "11:30", "end": "13:30"}, {"name": "석식", "start": "18:00", "end": "19:30"}]


def _at(hhmm, day=18):  # 2026-11-18 is a Wednesday, 21 a Saturday
    hour, minute = map(int, hhmm.split(":"))
    return datetime(2026, 11, day, hour, minute, tzinfo=KST)


def _status(windows=None, hhmm="12:00", day=18, weekend_allowed=True, daily_limit=None, **kw):
    policy = _policy_from_row({"meal_windows": windows if windows is not None else LUNCH_DINNER,
                               "daily_limit": daily_limit, "weekend_allowed": weekend_allowed})
    args = {"spent_today": 0, "spent_month": 0, "monthly_limit": 200000, **kw}
    return company_meal_status(policy=policy, now=_at(hhmm, day), **args), policy


def test_inside_and_outside_meal_hours():
    inside, _ = _status(hhmm="12:00")
    assert (inside["available"], inside["code"], inside["current_window"], inside["restricted"]) == (True, None, "중식", True)
    assert inside["windows"] == LUNCH_DINNER
    outside, _ = _status(hhmm="15:00")
    assert (outside["available"], outside["code"], outside["limit_block"]) == (False, "OUT_OF_WINDOW", None)
    assert _status(hhmm="18:30")[0]["current_window"] == "석식"


def test_no_restriction_means_any_time_and_lists_no_hours():
    for windows in ([{"name": "상시", "start": "00:00", "end": "23:59"}], []):
        status, _ = _status(windows=windows, hhmm="03:00")
        assert (status["available"], status["restricted"], status["windows"], status["current_window"]) == (True, False, [], None)
    assert company_meal_status(policy=_policy_from_row(None), now=_at("03:00"), spent_today=0, spent_month=0, monthly_limit=200000)["available"] is True


def test_reasons_other_than_time_and_their_priority():
    weekend, _ = _status(day=21, weekend_allowed=False)
    assert (weekend["available"], weekend["code"], weekend["weekend_allowed"]) == (False, "WEEKEND_BLOCKED", False)
    assert _status(day=21, weekend_allowed=True)[0]["available"] is True
    month, _ = _status(spent_month=200000)
    assert month["limit_block"] == {"code": "MONTHLY_LIMIT", "message": "이번 달 한도 200,000원을 모두 썼어요"}
    assert _status(spent_month=199999)[0]["available"] is True
    assert _status(monthly_limit=0)[0]["limit_block"]["message"] == "회사 식대 한도가 0원으로 설정돼 있어요"
    day, _ = _status(daily_limit=10000, spent_today=10000)
    assert day["limit_block"] == {"code": "DAILY_LIMIT", "message": "오늘 한도 10,000원을 모두 썼어요"}
    assert _status(daily_limit=10000, spent_today=9000)[0]["available"] is True
    inactive, _ = _status(company_active=False, spent_month=999999)
    assert inactive["code"] == "COMPANY_NOT_ACTIVE"
    # A used-up limit is reported even outside meal hours: it will not clear at the next window.
    assert _status(hhmm="15:00", spent_month=200000)[0]["code"] == "MONTHLY_LIMIT"


def test_time_judgement_always_matches_the_payment_rule():
    for hhmm in ("11:29", "11:30", "13:30", "13:31", "17:59", "18:00", "19:30", "19:31", "00:00", "23:59"):
        for day, weekend_allowed in ((18, False), (21, False), (21, True)):
            status, policy = _status(hhmm=hhmm, day=day, weekend_allowed=weekend_allowed)
            pay = evaluate_payment_policy(amount=8000, spent_today=0, policy=policy, now=_at(hhmm, day))
            assert status["available"] == pay.ok, (hhmm, day, weekend_allowed)
            assert status["code"] == pay.code


def _repo(tables, fail=None):
    def rest_get(table, params):
        if table == fail:
            raise SupabaseHttpError(500, "boom")
        return tables.get(table, [])
    return SimpleNamespace(client=SimpleNamespace(rest_get=rest_get))


def test_employee_gets_only_the_company_name_and_the_status():
    tables = {"companies": [{"id": "c1", "name": "합성테크", "status": "active", "biz_reg_no": "1234567890"}],
              "meal_policies": [{"meal_windows": LUNCH_DINNER, "daily_limit": None, "weekend_allowed": True}]}
    with patch("app.routers.me.datetime") as clock:
        clock.now.return_value = _at("15:00")
        company, status = me._employee_company(_repo(tables), "c1", {"today_used": 0, "month_used": 8000, "monthly_limit": 200000})
    assert company == {"id": "c1", "name": "합성테크"}
    assert (status["available"], status["code"]) == (False, "OUT_OF_WINDOW")


def test_a_failed_read_never_breaks_me():
    usage = {"today_used": 0, "month_used": 0, "monthly_limit": 200000}
    assert me._employee_company(_repo({}, fail="companies"), "c1", usage) == (None, None)
    assert me._employee_company(_repo({"companies": [{"id": "c1", "name": "합성테크", "status": "active"}]}, fail="meal_policies"), "c1", usage) == (None, None)
    assert me._employee_company(_repo({}), "c1", usage) == (None, None)
    assert me._employee_company(_repo({}), None, usage) == (None, None)
    # No policy row at all = unrestricted.
    company, status = me._employee_company(_repo({"companies": [{"id": "c1", "name": "합성테크", "status": "active"}]}), "c1", usage)
    assert company["name"] == "합성테크" and status["available"] is True and status["restricted"] is False
