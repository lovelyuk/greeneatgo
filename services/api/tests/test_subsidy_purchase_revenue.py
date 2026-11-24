"""A company subsidy is revenue when the voucher is bought (migration 0080)."""
from types import SimpleNamespace
from unittest.mock import patch

from app.routers import admin as admin_router
from app.routers import me as me_router
from app.services.subsidy_charge import company_charge, is_charged_at_purchase, is_subsidy_charge, without_subsidy_charges
from tests.test_merchant_revenue import ACME, AUTH, BETA, PERIOD, harness  # noqa: F401  (fixture)

CHARGE = {"subsidized": True, "subsidy_charge": True}


def _charge(id_, at, amount=1000, company=BETA, user="u2"):
    return {"id": id_, "user_id": user, "company_id": company, "amount": -amount, "kind": "spend", "pay_type": "subsidized",
            "company_subsidy_amount": amount, "settlement_total_amount": amount, "meal_window": "보조금",
            "product_name": "보조금 식권 구매", "flags": dict(CHARGE), "created_at": at}


def _reversal(id_, created_at, refunded_at, amount=1000, company=BETA, user="u2"):
    return {"id": id_, "user_id": user, "company_id": company, "amount": amount, "kind": "refund", "pay_type": "subsidized",
            "company_subsidy_amount": amount, "settlement_total_amount": amount, "meal_window": "보조금",
            "product_name": "보조금 식권 환불", "created_at": created_at,
            "flags": {**CHARGE, "subsidy_charge_reversal": True, "refunded_at": refunded_at}}


def _meal(id_, at, charged=True, company=BETA, user="u2"):
    return {"id": id_, "user_id": user, "company_id": company, "amount": -8000, "kind": "spend", "pay_type": "subsidized",
            "company_subsidy_amount": 1000, "settlement_total_amount": 0 if charged else 1000, "meal_window": "보조금",
            "product_name": "보조금 식권 사용", "created_at": at,
            "flags": {"subsidized": True, "charged_at_purchase": True} if charged else {"subsidized": True}}


def _party(data, name):
    return next(row for row in data["parties"] if row["name"] == name)


def _summary(client):
    return client.get(f"/v1/admin/merchant/revenue/summary{PERIOD}", headers=AUTH).json()["data"]


def test_helpers_tell_charges_from_meals():
    charge, meal, old = _charge(1, "x"), _meal(2, "x"), _meal(3, "x", charged=False)
    assert [is_subsidy_charge(row) for row in (charge, meal, old, {"flags": None}, {})] == [True, False, False, False, False]
    assert [is_charged_at_purchase(row) for row in (charge, meal, old)] == [False, True, False]
    assert without_subsidy_charges([charge, meal, old]) == [meal, old]
    # What the company is billed: the charge, nothing for the meal, the subsidy for an old-style meal.
    assert [company_charge(row) for row in (charge, meal, old)] == [1000, 0, 1000]
    assert company_charge({"company_subsidy_amount": 700, "settlement_total_amount": None}) == 700


def test_the_subsidy_is_revenue_on_the_purchase_day_and_the_meal_adds_nothing(harness):  # noqa: F811
    client, tables, _, _, _ = harness
    before = _summary(client)
    tables["meal_transactions"] += [
        _charge(101, "2026-11-10T03:00:00+00:00"), _charge(102, "2026-11-10T03:00:00+00:00"),
        _meal(103, "2026-11-12T03:00:00+00:00"),
    ]
    data = _summary(client)
    paid, beta, was = data["paid_basis"], _party(data, "가온상사"), _party(before, "가온상사")
    assert (paid["subsidy_amount"], paid["subsidy_count"]) == (2000, 2)
    assert paid["revenue_amount"] == before["paid_basis"]["revenue_amount"] + 2000
    assert (beta["subsidy_amount"], beta["revenue_amount"]) == (2000, was["revenue_amount"] + 2000)
    # Usage basis: the purchases are not meals; the one meal is worth the subsidy as before.
    assert (beta["usage_count"], beta["usage_amount"]) == (was["usage_count"] + 1, was["usage_amount"] + 1000)
    assert data["usage_basis"]["count"] == before["usage_basis"]["count"] + 1
    # Other parties are untouched.
    for name in ("합성테크", "개인 고객"):
        assert _party(data, name) == _party(before, name)


def test_a_refund_takes_the_subsidy_back_on_the_refund_day(harness):  # noqa: F811
    client, tables, _, _, _ = harness
    base = _party(_summary(client), "가온상사")["revenue_amount"]
    # Bought in October, refunded in November: November only sees the refund.
    tables["meal_transactions"] += [
        _charge(201, "2026-10-20T03:00:00+00:00"),
        _reversal(202, "2026-10-20T03:00:00+00:00", "2026-11-05T04:00:00.123456+00:00"),
    ]
    data = _summary(client)
    assert (data["paid_basis"]["subsidy_amount"], data["paid_basis"]["subsidy_count"]) == (-1000, -1)
    assert _party(data, "가온상사")["revenue_amount"] == base - 1000
    october = client.get("/v1/admin/merchant/revenue/summary?from=2026-10-01&to=2026-10-31", headers=AUTH).json()["data"]
    assert october["paid_basis"]["subsidy_amount"] == 1000


def test_the_tax_invoice_does_not_count_purchase_charges_a_second_time(harness):  # noqa: F811
    client, tables, _, _, _ = harness
    # ACME's October settlement (176,000, invoiced in November) bills 6,000 of purchase charges
    # (7 bought, 1 refunded) on top of ledger meals.
    for row in tables["normal_settlements"]:
        row.update({"period_from": f"{row['period_ym']}-01", "period_to": f"{row['period_ym']}-28"})
    tables["meal_transactions"] += [_charge(300 + n, "2026-10-10T03:00:00+00:00", company=ACME, user="u1") for n in range(7)]
    tables["meal_transactions"].append(_reversal(310, "2026-10-10T03:00:00+00:00", "2026-10-11T03:00:00+00:00", company=ACME, user="u1"))
    data = _summary(client)
    acme = _party(data, "합성테크")
    assert acme["invoice_amount"] == 176000 - 6000
    assert acme["subsidy_amount"] == 0                    # the charges were October revenue
    assert acme["revenue_amount"] == 170000
    detail = client.get(f"/v1/admin/merchant/revenue/detail{PERIOD}&party={ACME}", headers=AUTH).json()["data"]
    invoice = next(row for row in detail["paid_basis"]["entries"] if row["kind"] == "invoice")
    assert (invoice["amount"], invoice["purchase_charge_amount"]) == (170000, 6000)


def test_detail_lists_each_subsidy_with_the_buyer(harness):  # noqa: F811
    client, tables, _, _, _ = harness
    tables["merchant_companies"].append({"company_id": BETA})
    tables["meal_transactions"] += [
        _charge(401, "2026-11-10T03:00:00+00:00"),
        _charge(402, "2026-11-11T03:00:00+00:00"),
        _reversal(403, "2026-11-11T03:00:00+00:00", "2026-11-12T03:00:00+00:00"),
        _meal(404, "2026-11-13T03:00:00+00:00"),
    ]
    detail = client.get(f"/v1/admin/merchant/revenue/detail{PERIOD}&party={BETA}", headers=AUTH).json()["data"]
    entries = [(row["kind"], row["amount"], row["label"], row["person_name"]) for row in detail["paid_basis"]["entries"]
               if row["kind"].startswith("subsidy")]
    assert entries == [
        ("subsidy_refund", -1000, "회사 보조금 환불 (미사용 식권)", "박민수"),
        ("subsidy", 1000, "회사 보조금 (식권 구매)", "박민수"),
        ("subsidy", 1000, "회사 보조금 (식권 구매)", "박민수"),
    ]
    paid = detail["paid_basis"]
    assert paid["subsidy_amount"] == 1000
    assert paid["revenue_amount"] == paid["net_payment_amount"] + 1000 + paid["invoice_amount"]
    # The meal list holds the meal only.
    assert [row["id"] for row in detail["usage_basis"]["items"] if row["id"] in (401, 402, 403, 404)] == [404]


def test_the_employee_app_does_not_show_the_charge_as_a_meal():
    rows = [
        {**_charge(1, "2099-01-10T03:00:00+00:00"), "merchant_id": "m"},
        {**_meal(2, "2099-01-12T03:00:00+00:00"), "merchant_id": "m"},
    ]
    repo = SimpleNamespace(client=SimpleNamespace())

    def rest_get(table, params):
        if table == "normal_meal_transactions":
            assert "flags" in params["select"]
            return list(rows)
        if table == "merchants":
            return [{"id": "m", "name": "식당"}]
        return []

    repo.client.rest_get = rest_get
    usage = me_router._employee_usage(repo, "u2")
    assert [row["id"] for row in usage["recent_transactions"]] == [2]
    assert usage["month_used"] == 8000                    # the meal, not meal + charge


def test_company_admin_and_restaurant_feeds_use_the_helper():
    import inspect

    from app.routers import boards, merchant_admin
    assert "is_subsidy_charge(tx)" in inspect.getsource(admin_router)
    assert inspect.getsource(admin_router).count("without_subsidy_charges(") >= 1
    assert inspect.getsource(merchant_admin).count("without_subsidy_charges(") >= 2
    assert inspect.getsource(boards).count("without_subsidy_charges(") == 2
