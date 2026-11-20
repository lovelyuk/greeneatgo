"""Restaurant-side correction of a disputed settlement: cancel single meals (migration 0079)."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.repositories.settlements import SettlementRepository
from app.repositories.supabase_http import SupabaseHttpError
from tests.test_settlement_api import SETTLEMENT_ID, FakeSettlements, client_factory  # noqa: F401  (fixture)

MIGRATIONS = Path(__file__).parents[3] / "supabase/migrations"
PATH = f"/v1/admin/merchant/settlements/{SETTLEMENT_ID}/transactions/42/cancel"


def _with_cancel(repo, result=None, error=None):
    def cancel_transaction(actor, settlement_id, transaction_id, reason):
        repo.calls.append(("cancel_transaction", actor.merchant_id, str(settlement_id), transaction_id, reason))
        if error is not None:
            raise error
        return result or {"settlement": {"id": SETTLEMENT_ID, "total_amount": 17600}, "cancel_transaction_id": 99, "idempotent": False}
    repo.cancel_transaction = cancel_transaction


def test_merchant_cancels_one_meal_with_a_reason(client_factory):
    client, repo = client_factory("merchant_admin")
    _with_cancel(repo)
    response = client.post(PATH, json={"reason": "  그날 식사하지 않음 "})
    assert response.status_code == 200
    assert response.json()["data"]["settlement"]["total_amount"] == 17600
    # Tenant comes from the session; the settlement is looked up as an ordinary (non-demo) one first.
    assert repo.calls[-2][0] == "merchant_detail"
    assert repo.calls[-1] == ("cancel_transaction", "merchant-own", SETTLEMENT_ID, 42, "그날 식사하지 않음")


def test_reason_is_required_and_bounded(client_factory):
    client, repo = client_factory("merchant_admin")
    _with_cancel(repo)
    for body in ({}, {"reason": ""}, {"reason": "   "}, {"reason": "가" * 301}):
        assert client.post(PATH, json=body).status_code == 422
    assert client.post(PATH.replace("/42/", "/abc/"), json={"reason": "사유"}).status_code == 422
    assert not [call for call in repo.calls if call[0] == "cancel_transaction"]


def test_only_a_merchant_admin_session_is_accepted_and_demo_settlements_are_refused(client_factory):
    import pytest
    client, repo = client_factory("company_admin")
    _with_cancel(repo)
    # The route asks for a merchant_admin actor (the fake asserts the requested role).
    with pytest.raises(AssertionError):
        client.post(PATH, json={"reason": "사유"})
    assert not [call for call in repo.calls if call[0] == "cancel_transaction"]
    client, repo = client_factory("merchant_admin")
    _with_cancel(repo)
    repo.demo = True
    assert client.post(PATH, json={"reason": "사유"}).status_code == 404
    assert not [call for call in repo.calls if call[0] == "cancel_transaction"]


def test_database_refusals_are_mapped(client_factory):
    for body, status, code in (
        ("SETTLEMENT_STATE_CONFLICT", 409, "SETTLEMENT_STATE_CONFLICT"),
        ("SETTLEMENT_TRANSACTION_NOT_FOUND", 404, "SETTLEMENT_TRANSACTION_NOT_FOUND"),
        ("SETTLEMENT_TRANSACTION_NOT_CANCELLABLE", 422, "SETTLEMENT_TRANSACTION_NOT_CANCELLABLE"),
        ("SETTLEMENT_FORBIDDEN", 403, "FORBIDDEN"),
    ):
        client, repo = client_factory("merchant_admin")
        _with_cancel(repo, error=SupabaseHttpError(400, body))
        response = client.post(PATH, json={"reason": "사유"})
        assert (response.status_code, response.json()["detail"]["code"]) == (status, code)


def test_transaction_list_pairs_a_cancelled_meal_with_its_reversal():
    repo = SettlementRepository.__new__(SettlementRepository)
    client = MagicMock()
    object.__setattr__(repo, "client", client)
    base = {"user_id": "u1", "tx_code": "A", "meal_window": "중식", "product_name": None, "pay_type": "ledger",
            "is_demo": False, "settlement_tax_type": "taxable", "settlement_supply_amount": 8000,
            "settlement_vat_amount": 800, "settlement_total_amount": 8800, "created_at": "2031-03-15T03:00:00+00:00"}
    rows = [
        {**base, "id": 1, "amount": -8800, "kind": "spend", "original_transaction_id": None, "flags": {}},
        {**base, "id": 2, "amount": -8800, "kind": "spend", "original_transaction_id": None, "flags": {"cancel_reason": "not a reversal"}},
        {**base, "id": 3, "amount": 8800, "kind": "cancel", "original_transaction_id": 1,
         "flags": {"cancel_reason": "그날 식사하지 않음", "cancelled_by": "actor"}},
    ]
    client.rest_get.side_effect = lambda table, params: (
        [{"id": "u1", "display_name": "김직원", "employee_no": "E1", "department": "개발"}] if table == "app_users" else rows)
    items = repo._settlement_transactions({"merchant_id": "m", "company_id": "c", "period_from": "2031-03-01", "period_to": "2031-03-31"})
    assert [(i["id"], i["kind"], i["cancelled"], i["original_transaction_id"], i["cancel_reason"], i["total_amount"]) for i in items] == [
        (1, "spend", True, None, None, 8800),
        (2, "spend", False, None, None, 8800),
        (3, "cancel", False, 1, "그날 식사하지 않음", -8800),
    ]
    # Who cancelled stays server-side.
    assert all("cancelled_by" not in item and "flags" not in item for item in items)


def test_0079_changes_only_the_limit_sum_of_process_meal_pay():
    old = (MIGRATIONS / "0077_personal_vouchers_outside_company_limits.sql").read_text(encoding="utf-8")
    new = (MIGRATIONS / "0079_settlement_transaction_cancel.sql").read_text(encoding="utf-8")

    def body(sql):
        start = sql.index("create or replace function public.process_meal_pay")
        return sql[start:sql.index("end $$;", start)].splitlines()

    removed = [line for line in body(old) if line not in body(new)]
    added = [line for line in body(new) if line not in body(old)]
    assert len(removed) == 2 and len(added) == 3
    assert "kind='spend' and pay_type<>'voucher'" in removed[1]
    assert "kind in ('spend','cancel','refund') and pay_type<>'voucher'" in added[2]
    assert all("case when kind='spend' then abs(amount) else -abs(amount) end" in line for line in added[:2])


def test_limit_precheck_and_month_usage_give_a_cancelled_meal_back():
    from datetime import datetime, timezone
    from app.routers.me import _employee_usage

    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {"id": 1, "amount": -8000, "kind": "spend", "pay_type": "ledger", "created_at": now, "merchant_id": "m"},
        {"id": 2, "amount": -8000, "kind": "spend", "pay_type": "ledger", "created_at": now, "merchant_id": "m"},
        {"id": 3, "amount": 8000, "kind": "cancel", "pay_type": "ledger", "created_at": now, "merchant_id": "m"},
    ]
    repo = SimpleNamespace(client=MagicMock())
    repo.client.rest_get.side_effect = lambda table, params: {
        "normal_meal_transactions": rows, "vouchers": [], "app_users": [{"monthly_limit": 20000}],
        "merchants": [{"id": "m", "name": "식당"}],
    }.get(table, [])
    usage = _employee_usage(repo, "user-1")
    assert (usage["month_used"], usage["remaining_limit"]) == (8000, 12000)
