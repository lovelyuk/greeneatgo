"""Several meals in one scan, and the company's daily meal-count limit."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.repositories.supabase_http import SupabaseHttpError
from app.routers import pay as pay_router
from app.routers.admin import _meal_policy_data
from app.routers.pay import charge_ledger_meal, daily_count_limit_of, ledger_meals_today, meal_policy_row
from app.routers.transactions import member_qr, redeem_member_qr, scan
from app.schemas import MealPolicyUpdateRequest, MemberQrRedeemRequest, TransactionScanRequest
from app.services import meal_qr
from app.services.company_meal_status import company_meal_status
from app.services.policy_engine import UNRESTRICTED_WINDOWS, MealPolicy

SECRET = "test-meal-qr-secret"
USER = "11111111-2222-4333-8444-555555555555"
SETTINGS = SimpleNamespace(meal_qr_secret=SECRET, pilot_merchant_id=None)
MERCHANT = {"id": "merchant-1", "name": "돈토식당", "qr_token": "QR-DONTO", "lat": None, "lng": None, "status": "active"}
DRAFT = SimpleNamespace(ok=True, code=None, message=None, tx_code="ABC", meal_window="중식", flags={})


# ------------------------------------------------------------------ the QR carries the quantity
def test_one_meal_keeps_the_original_code_and_several_use_the_quantity_versions():
    single, _ = meal_qr.issue(USER, SECRET)
    assert single[:2] == "81" and meal_qr.verify(single, SECRET).quantity == 1
    assert meal_qr.issue(USER, SECRET, personal=True)[0][:2] == "82"
    for quantity in (2, 3, 10):
        code, _ = meal_qr.issue(USER, SECRET, quantity=quantity)
        claim = meal_qr.verify(code, SECRET)
        assert (len(code), code[:2], claim.quantity, claim.pay_source, claim.user_id) == (81, "83", quantity, "company", USER)
    personal = meal_qr.verify(meal_qr.issue(USER, SECRET, personal=True, quantity=4)[0], SECRET)
    assert (personal.quantity, personal.pay_source) == (4, "personal")
    for bad in (0, 11):
        with pytest.raises(ValueError):
            meal_qr.issue(USER, SECRET, quantity=bad)


def test_the_quantity_is_signed_and_cannot_be_raised():
    code, _ = meal_qr.issue(USER, SECRET, quantity=2)
    forged = code[:51] + "09" + code[53:]                # 2 -> 9 without re-signing
    with pytest.raises(meal_qr.MealQrError) as caught:
        meal_qr.verify(forged, SECRET)
    assert caught.value.code == "INVALID_MEAL_QR"
    # Turning a one-meal code into a several-meal version fails the same way.
    single, _ = meal_qr.issue(USER, SECRET)
    with pytest.raises(meal_qr.MealQrError):
        meal_qr.verify("83" + single[2:], SECRET)


def test_issuing_a_code_for_several_meals_and_refusing_a_bad_quantity():
    with patch("app.routers.transactions.get_settings", return_value=SETTINGS), \
            patch("app.routers.transactions.JoinRepository") as repo_class:
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id=USER, email=None)
        repo.get_profile.return_value = SimpleNamespace(id=USER, role="customer", status="active", company_id=None)
        data = member_qr(quantity=3, token="bearer")["data"]
        assert (data["quantity"], meal_qr.verify(data["code"], SECRET).quantity) == (3, 3)
        assert member_qr(token="bearer")["data"]["quantity"] == 1
        for bad in (0, 11):
            with pytest.raises(HTTPException) as caught:
                member_qr(quantity=bad, token="bearer")
            assert (caught.value.status_code, caught.value.detail["code"]) == (422, "INVALID_QUANTITY")


# ------------------------------------------------------------------ the counter redeems that many
def _counter(repo_class, *, member_role="customer", subsidy=False, tables=None):
    repo = repo_class.return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id="admin", email="m@example.com")
    admin = SimpleNamespace(id="admin", role="merchant_admin", status="active", merchant_id="merchant-1")
    member = SimpleNamespace(id=USER, role=member_role, status="active", display_name="김구매",
                             company_id="company-1" if member_role == "employee" else None)
    repo.get_profile.side_effect = lambda uid, email=None: admin if uid == "admin" else member
    data = {
        "merchants": [MERCHANT], "companies": [{"name": "합성테크"}], "app_users": [{"monthly_limit": 200000}],
        "merchant_companies": [{"unit_price": 8000, "status": "active", "subsidy_enabled": subsidy}],
        "meal_policies": [], "normal_meal_transactions": [], **(tables or {}),
    }
    repo.client.rest_get.side_effect = lambda table, params: data[table]
    return repo


@patch("app.routers.transactions.get_settings", return_value=SETTINGS)
@patch("app.routers.transactions.JoinRepository")
def test_three_vouchers_are_used_by_one_scan(repo_class, _settings):
    repo = _counter(repo_class)
    repo.client.rpc.return_value = {"id": 1, "remaining": 2, "duplicate": False, "total_amount": 24000, "quantity": 3}
    code, _ = meal_qr.issue(USER, SECRET, quantity=3)
    out = redeem_member_qr(MemberQrRedeemRequest(code=code), "bearer")["data"]
    name, args = repo.client.rpc.call_args.args
    assert (name, args["p_quantity"], args["p_idempotency_key"]) == ("consume_vouchers_many", 3, meal_qr.verify(code, SECRET).idempotency_key)
    assert (out["quantity"], out["remaining"], out["amount"], out["pay_type"]) == (3, 2, 24000, "voucher")
    # One voucher still goes through the original function.
    repo.client.rpc.return_value = {"id": 2, "remaining": 1, "duplicate": False, "total_amount": 8000}
    out = redeem_member_qr(MemberQrRedeemRequest(code=meal_qr.issue(USER, SECRET)[0]), "bearer")["data"]
    assert (repo.client.rpc.call_args.args[0], "p_quantity" in repo.client.rpc.call_args.args[1], out["quantity"]) == ("consume_voucher", False, 1)


@patch("app.routers.transactions.get_settings", return_value=SETTINGS)
@patch("app.routers.transactions.JoinRepository")
def test_subsidized_and_ledger_meals_take_the_quantity_too(repo_class, _settings):
    repo = _counter(repo_class, member_role="employee", subsidy=True)
    repo.client.rpc.return_value = {"id": 1, "remaining": 0, "duplicate": False, "total_amount": 16000}
    out = redeem_member_qr(MemberQrRedeemRequest(code=meal_qr.issue(USER, SECRET, quantity=2)[0]), "bearer")["data"]
    assert (repo.client.rpc.call_args.args[0], repo.client.rpc.call_args.args[1]["p_quantity"], out["quantity"]) == ("consume_subsidized_vouchers_many", 2, 2)

    repo = _counter(repo_class, member_role="employee")
    repo.client.rpc.reset_mock()
    repo.client.rpc.return_value = {"id": 9, "amount": 16000, "duplicate": False, "quantity": 2, "created_at": "2026-11-24T03:00:00Z"}
    with patch("app.routers.pay.prepare_payment_draft", return_value=DRAFT) as prepare:
        out = redeem_member_qr(MemberQrRedeemRequest(code=meal_qr.issue(USER, SECRET, quantity=2)[0]), "bearer")["data"]
    name, args = repo.client.rpc.call_args.args
    assert (name, args["p_quantity"], args["p_amount"]) == ("process_meal_pay_many", 2, 8000)
    assert (out["pay_type"], out["quantity"], out["amount"], out["company_name"]) == ("ledger", 2, 16000, "합성테크")
    # The daily amount rule is judged on both meals: the second is passed as already spent.
    assert (prepare.call_args.args[0].amount, prepare.call_args.args[0].spent_today) == (8000, 8000)


@patch("app.routers.transactions.get_settings", return_value=SETTINGS)
@patch("app.routers.transactions.JoinRepository")
def test_a_refusal_by_the_database_reaches_the_counter_as_the_company_reason(repo_class, _settings):
    repo = _counter(repo_class, member_role="employee")
    repo.client.rpc.side_effect = SupabaseHttpError(400, '{"code":"P0001","message":"DAILY_COUNT_LIMIT"}')
    with patch("app.routers.pay.prepare_payment_draft", return_value=DRAFT), pytest.raises(HTTPException) as caught:
        redeem_member_qr(MemberQrRedeemRequest(code=meal_qr.issue(USER, SECRET)[0]), "bearer")
    assert (caught.value.status_code, caught.value.detail["code"]) == (400, "DAILY_COUNT_LIMIT")
    repo.client.rpc.side_effect = SupabaseHttpError(400, '{"code":"P0001","message":"NOT_AFFILIATED"}')
    with patch("app.routers.pay.prepare_payment_draft", return_value=DRAFT), pytest.raises(HTTPException) as caught:
        redeem_member_qr(MemberQrRedeemRequest(code=meal_qr.issue(USER, SECRET)[0]), "bearer")
    assert caught.value.detail["code"] == "NOT_AFFILIATED"


@patch("app.routers.transactions.get_settings")
@patch("app.routers.transactions.JoinRepository")
def test_scanning_the_store_qr_sends_the_quantity(repo_class, settings):
    settings.return_value = SimpleNamespace(meal_qr_secret=SECRET, pilot_merchant_id="merchant-1")
    repo = repo_class.return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id=USER, email=None)
    repo.get_profile.return_value = SimpleNamespace(id=USER, role="customer", status="active", company_id=None)
    repo.client.rest_get.return_value = [MERCHANT]
    repo.client.rpc.return_value = {"id": 1, "remaining": 0, "duplicate": False}
    out = scan(TransactionScanRequest(qr_data="QR-DONTO", idempotency_key="key-12345678", quantity=2), "bearer")
    assert (repo.client.rpc.call_args.args[0], repo.client.rpc.call_args.args[1]["p_quantity"], out["quantity"]) == ("consume_vouchers_many", 2, 2)
    assert TransactionScanRequest(qr_data="x", idempotency_key="key-12345678").quantity == 1
    for bad in (0, 11):
        with pytest.raises(ValueError):
            TransactionScanRequest(qr_data="x", idempotency_key="key-12345678", quantity=bad)


# ------------------------------------------------------------------ company ledger limits
def _ledger_repo(*, policy=None, meals=(), monthly=200000, missing_many=False, missing_column=False):
    repo = SimpleNamespace(client=SimpleNamespace())
    calls = []

    def rest_get(table, params):
        if table == "meal_policies":
            if missing_column and "daily_count_limit" in params["select"]:
                raise SupabaseHttpError(400, '{"code":"42703","message":"column meal_policies.daily_count_limit does not exist"}')
            return [policy] if policy else []
        if table == "normal_meal_transactions":
            return list(meals)
        return [{"monthly_limit": monthly}]

    def rpc(name, args):
        calls.append((name, args))
        if name == "process_meal_pay_many" and missing_many:
            raise SupabaseHttpError(404, '{"code":"PGRST202","message":"Could not find the function public.process_meal_pay_many"}')
        return {"id": 1, "duplicate": False}

    repo.client.rest_get, repo.client.rpc = rest_get, rpc
    return repo, calls


EMPLOYEE = SimpleNamespace(id=USER, role="employee", status="active", company_id="company-1")
OPEN = {"meal_windows": [{"name": "상시", "start": "00:00", "end": "23:59", "per_meal_limit": 10000000}], "weekend_allowed": True}


def _meal(kind="spend", pay_type="ledger", hours_ago=0.01):
    at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {"amount": -8000 if kind == "spend" else 8000, "kind": kind, "pay_type": pay_type, "created_at": at.isoformat()}


def test_the_daily_count_limit_refuses_before_any_charge():
    repo, calls = _ledger_repo(policy={**OPEN, "daily_count_limit": 2}, meals=[_meal()])
    with pytest.raises(HTTPException) as caught:
        charge_ledger_meal(repo, EMPLOYEE, MERCHANT, 8000, None, "key", quantity=2)
    assert caught.value.detail == {"code": "DAILY_COUNT_LIMIT", "message": "회사 식대는 하루 2번까지예요. 오늘은 1번 더 쓸 수 있어요"}
    assert calls == []
    # One more fits; a third does not.
    charge_ledger_meal(repo, EMPLOYEE, MERCHANT, 8000, None, "key", quantity=1)
    assert (calls[0][0], calls[0][1]["p_quantity"]) == ("process_meal_pay_many", 1)
    repo, calls = _ledger_repo(policy={**OPEN, "daily_count_limit": 2}, meals=[_meal(), _meal()])
    with pytest.raises(HTTPException) as caught:
        charge_ledger_meal(repo, EMPLOYEE, MERCHANT, 8000, None, "key")
    assert caught.value.detail["message"] == "오늘 회사 식대 사용 횟수 2번을 모두 썼어요"


def test_counting_todays_company_meals():
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    rows = [_meal(), _meal(), _meal("cancel"), _meal(pay_type="subsidized"), _meal(pay_type="voucher"), _meal(hours_ago=30)]
    assert ledger_meals_today(rows, start) == 1            # two meals, one cancelled; others are not company ledger
    assert ledger_meals_today([_meal("cancel")], start) == 0
    assert [daily_count_limit_of(row) for row in (None, {}, {"daily_count_limit": None}, {"daily_count_limit": 0},
                                                  {"daily_count_limit": 3}, {"daily_count_limit": True})] == [None, None, None, None, 3, None]


def test_the_monthly_limit_is_judged_on_all_the_meals():
    repo, calls = _ledger_repo(policy=OPEN, monthly=20000)
    with pytest.raises(HTTPException) as caught:
        charge_ledger_meal(repo, EMPLOYEE, MERCHANT, 8000, None, "key", quantity=3)
    assert caught.value.detail["code"] == "MONTHLY_LIMIT" and calls == []
    charge_ledger_meal(repo, EMPLOYEE, MERCHANT, 8000, None, "key", quantity=2)
    assert calls[0][1]["p_quantity"] == 2
    with pytest.raises(HTTPException) as caught:
        charge_ledger_meal(repo, EMPLOYEE, MERCHANT, 8000, None, "key", quantity=11)
    assert caught.value.detail["code"] == "INVALID_QUANTITY"


def test_before_the_migration_one_meal_still_works_and_several_say_so():
    repo, calls = _ledger_repo(policy=OPEN, missing_many=True, missing_column=True)
    assert charge_ledger_meal(repo, EMPLOYEE, MERCHANT, 8000, None, "key") == {"id": 1, "duplicate": False}
    assert [name for name, _ in calls] == ["process_meal_pay_many", "process_meal_pay"]
    assert calls[1][1]["p_product_id"] is None and "p_quantity" not in calls[1][1]
    with pytest.raises(HTTPException) as caught:
        charge_ledger_meal(repo, EMPLOYEE, MERCHANT, 8000, None, "key", quantity=2)
    assert caught.value.detail["code"] == "MIGRATION_REQUIRED"
    # The policy row is still read when the new column does not exist yet.
    assert meal_policy_row(repo, "company-1") == OPEN
    # Any other database error is not swallowed.
    broken = SimpleNamespace(client=SimpleNamespace(rest_get=lambda table, params: (_ for _ in ()).throw(SupabaseHttpError(500, "boom"))))
    with pytest.raises(SupabaseHttpError):
        meal_policy_row(broken, "company-1")
    assert pay_router._map_rpc_error(SupabaseHttpError(400, "DAILY_COUNT_LIMIT")).detail["code"] == "DAILY_COUNT_LIMIT"


# ------------------------------------------------------------------ what the app and the admin see
def test_home_card_status_reports_the_count_and_blocks_when_used_up():
    policy = MealPolicy(meal_windows=UNRESTRICTED_WINDOWS, weekend_allowed=True)
    noon = datetime(2026, 11, 25, 3, tzinfo=timezone.utc)
    common = dict(policy=policy, now=noon, spent_today=0, spent_month=0, monthly_limit=200000)
    free = company_meal_status(**common)
    assert (free["available"], free["daily_count_limit"], free["remaining_today_count"]) == (True, None, None)
    some = company_meal_status(**common, count_today=1, daily_count_limit=3)
    assert (some["available"], some["count_today"], some["remaining_today_count"]) == (True, 1, 2)
    done = company_meal_status(**common, count_today=3, daily_count_limit=3)
    assert (done["available"], done["code"], done["remaining_today_count"]) == (False, "DAILY_COUNT_LIMIT", 0)
    assert done["limit_block"]["message"] == "오늘 사용 횟수 3번을 모두 썼어요"


def test_admin_meal_policy_carries_the_count():
    assert MealPolicyUpdateRequest().daily_count_limit is None
    assert MealPolicyUpdateRequest(daily_count_limit=2).daily_count_limit == 2
    for bad in (0, 21):
        with pytest.raises(ValueError):
            MealPolicyUpdateRequest(daily_count_limit=bad)
    assert _meal_policy_data(None)["daily_count_limit"] is None
    assert _meal_policy_data({"meal_windows": None, "daily_count_limit": 2})["daily_count_limit"] == 2
    assert _meal_policy_data({**OPEN, "daily_count_limit": 1})["daily_count_limit"] == 1


@patch("app.routers.transactions.get_settings", return_value=SETTINGS)
@patch("app.routers.transactions.JoinRepository")
def test_too_few_vouchers_for_the_chosen_quantity_uses_none_and_says_so(repo_class, _settings):
    repo = _counter(repo_class)
    repo.client.rpc.side_effect = SupabaseHttpError(400, '{"code":"P0001","message":"NO_VOUCHER"}')
    with pytest.raises(HTTPException) as caught:
        redeem_member_qr(MemberQrRedeemRequest(code=meal_qr.issue(USER, SECRET, quantity=3)[0]), "bearer")
    assert (caught.value.status_code, caught.value.detail["code"]) == (402, "NOT_ENOUGH_VOUCHERS")
    assert "3장" in caught.value.detail["message"]
    with pytest.raises(HTTPException) as caught:
        redeem_member_qr(MemberQrRedeemRequest(code=meal_qr.issue(USER, SECRET)[0]), "bearer")
    assert caught.value.detail["code"] == "NO_VOUCHER"
