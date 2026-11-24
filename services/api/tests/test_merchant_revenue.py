"""Restaurant revenue on the paid/issued basis next to the usage basis."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.repositories.supabase_http import SupabaseHttpError
from app.routers.merchant_revenue import router
from app.services.join_flow import JoinFlowError

AUTH = {"Authorization": "Bearer fixture"}
MERCHANT = "22222222-2222-4222-8222-222222222222"
ACME = "33333333-3333-4333-8333-333333333333"
BETA = "44444444-4444-4444-8444-444444444444"
PERIOD = "?from=2026-11-01&to=2026-11-30"


def _tables():
    return {
        "meal_transactions": [
            # ACME ledger: two meals, one cancelled -> usage 8,800
            {"id": 1, "user_id": "u1", "company_id": ACME, "amount": -8800, "kind": "spend", "pay_type": "ledger", "settlement_total_amount": 8800, "meal_window": "중식", "created_at": "2026-11-03T03:00:00+00:00"},
            {"id": 2, "user_id": "u1", "company_id": ACME, "amount": -8800, "kind": "spend", "pay_type": "ledger", "settlement_total_amount": 8800, "meal_window": "중식", "created_at": "2026-11-15T03:00:00+00:00"},
            {"id": 3, "user_id": "u1", "company_id": ACME, "amount": 8800, "kind": "cancel", "pay_type": "ledger", "settlement_total_amount": 8800, "meal_window": "중식", "created_at": "2026-11-15T03:00:00+00:00"},
            # BETA subsidized: the company's share only when no settlement snapshot exists
            {"id": 4, "user_id": "u2", "company_id": BETA, "amount": -8000, "kind": "spend", "pay_type": "subsidized", "company_subsidy_amount": 3000, "settlement_total_amount": None, "meal_window": "석식", "created_at": "2026-11-20T10:00:00+00:00"},
            # personal voucher meals (also a ledger employee paying with a personal voucher)
            {"id": 5, "user_id": "u3", "company_id": None, "amount": -8000, "kind": "spend", "pay_type": "voucher", "settlement_total_amount": None, "meal_window": "식권", "created_at": "2026-11-21T03:00:00+00:00"},
        ],
        "payment_orders": [
            {"id": "o1", "order_id": "GE-1", "user_id": "u3", "company_id": None, "amount": 80000, "point_amount": 0, "status": "done", "pay_type": "voucher", "product_name": "11장 식권", "payment_method": "CARD", "approved_at": "2026-11-02T01:00:00+00:00", "created_at": "2026-11-02T00:59:00+00:00"},
            {"id": "o2", "order_id": "GE-2", "user_id": "u3", "company_id": None, "amount": 8000, "point_amount": 0, "status": "refunded", "pay_type": "voucher", "product_name": "1장 식권", "payment_method": "NAVERPAY", "approved_at": "2026-11-05T01:00:00+00:00", "created_at": "2026-11-05T00:59:00+00:00"},
            {"id": "o3", "order_id": "GE-3", "user_id": "u2", "company_id": BETA, "amount": 5000, "point_amount": 1000, "status": "done", "pay_type": "subsidized", "product_name": "지원 식권", "payment_method": "CARD", "approved_at": "2026-11-10T01:00:00+00:00", "created_at": "2026-11-10T00:59:00+00:00"},
        ],
        "refund_requests": [
            {"id": "r1", "order_id": "o2", "user_id": "u3", "refund_amount": 8000, "point_amount": 0, "status": "completed", "created_at": "2026-11-06T01:00:00+00:00", "completed_at": "2026-11-06T02:00:00+00:00"},
        ],
        "tax_invoices": [
            {"id": "i1", "settlement_id": "s-oct", "company_id": ACME, "document_type": "original", "write_date": "2026-10-31", "supply_amount": 160000, "vat_amount": 16000, "total_amount": 176000, "nts_confirm_num": "20261105-1", "issued_at": "2026-11-05T05:00:00+00:00", "cancelled_at": None},
            # demo settlement and a cancelled document never count
            {"id": "i2", "settlement_id": "s-demo", "company_id": ACME, "document_type": "original", "write_date": "2026-10-31", "supply_amount": 900000, "vat_amount": 90000, "total_amount": 990000, "nts_confirm_num": "demo", "issued_at": "2026-11-06T05:00:00+00:00", "cancelled_at": None},
            {"id": "i3", "settlement_id": "s-sep", "company_id": BETA, "document_type": "original", "write_date": "2026-09-30", "supply_amount": 10000, "vat_amount": 1000, "total_amount": 11000, "nts_confirm_num": "x", "issued_at": "2026-11-07T05:00:00+00:00", "cancelled_at": "2026-11-08T05:00:00+00:00"},
        ],
        "normal_settlements": [
            {"id": "s-nov", "company_id": ACME, "period_ym": "2026-11", "total_amount": 8800, "settlement_status": "draft", "tax_invoice_status": "not_requested"},
            {"id": "s-oct", "company_id": ACME, "period_ym": "2026-10", "total_amount": 176000, "settlement_status": "confirmed", "tax_invoice_status": "issued"},
            {"id": "s-sep", "company_id": BETA, "period_ym": "2026-09", "total_amount": 11000, "settlement_status": "confirmed", "tax_invoice_status": "requested"},
            {"id": "s-void", "company_id": BETA, "period_ym": "2026-08", "total_amount": 5000, "settlement_status": "cancelled", "tax_invoice_status": "not_requested"},
        ],
        "companies": [{"id": ACME, "name": "합성테크"}, {"id": BETA, "name": "가온상사"}],
        "app_users": [{"id": "u1", "display_name": "김하늘", "employee_no": "E1", "department": "개발"},
                      {"id": "u2", "display_name": "박민수", "employee_no": "E2", "department": "영업"},
                      {"id": "u3", "display_name": "이손님", "employee_no": None, "department": None}],
        "merchant_companies": [{"company_id": ACME}],
    }


@pytest.fixture
def harness():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    tables = _tables()
    calls = []
    with patch("app.routers.merchant_revenue.JoinRepository") as repo_class, patch(
        "app.routers.merchant_revenue._merchant_admin", return_value=(SimpleNamespace(id="actor"), MERCHANT),
    ) as actor:
        repo = repo_class.return_value

        def rest_get(table, params):
            calls.append((table, params))
            rows = tables[table]
            if "id" in params and params["id"].startswith("in.("):
                wanted = params["id"][4:-1].split(",")
                rows = [row for row in rows if str(row["id"]) in wanted]
            if table == "merchant_companies":
                rows = [row for row in rows if params["company_id"] == f"eq.{row['company_id']}"]
            return rows

        repo.client.rest_get.side_effect = rest_get
        yield TestClient(app), tables, calls, actor, repo


def test_summary_shows_both_bases_per_party(harness):
    client, _, calls, _, _ = harness
    data = client.get(f"/v1/admin/merchant/revenue/summary{PERIOD}", headers=AUTH).json()["data"]
    assert data["paid_basis"] == {
        # o3 was paid 5,000 in money and 1,000 in company points: only the money counts.
        "payment_amount": 93000, "payment_count": 3, "refund_amount": 8000, "refund_count": 1,
        "net_payment_amount": 85000, "invoice_amount": 176000, "invoice_count": 1, "revenue_amount": 261000,
        "point_amount": 1000, "subsidy_amount": 0, "subsidy_count": 0,
    }
    assert data["usage_basis"] == {"amount": 8800 + 3000 + 8000, "count": 3}
    # ACME's running November draft and BETA's requested-but-not-issued September settlement.
    assert data["unbilled"] == {"amount": 8800 + 11000, "count": 2}
    assert [(p["name"], p["revenue_amount"], p["net_payment_amount"], p["invoice_amount"], p["usage_amount"], p["usage_count"], p["unbilled_amount"]) for p in data["parties"]] == [
        ("합성테크", 176000, 0, 176000, 8800, 1, 8800),
        ("가온상사", 5000, 5000, 0, 3000, 1, 11000),
        ("개인 고객", 80000, 80000, 0, 8000, 1, 0),
    ]
    # Every read is scoped to the caller's restaurant and the KST period.
    for table, params in calls:
        if table in ("meal_transactions", "payment_orders", "refund_requests", "tax_invoices", "normal_settlements"):
            assert params["merchant_id"] == f"eq.{MERCHANT}"
    meal_params = next(params for table, params in calls if table == "meal_transactions")
    assert meal_params["and"] == "(created_at.gte.2026-10-31T15:00:00+00:00,created_at.lt.2026-11-30T15:00:00+00:00)"
    payment_params = next(params for table, params in calls if table == "payment_orders" and "status" in params)
    assert payment_params["status"] == "in.(done,refunded)"
    assert next(params for table, params in calls if table == "tax_invoices")["issued_at"] == "not.is.null"


def test_company_detail_lists_invoices_meals_and_unbilled_settlements(harness):
    client, _, _, _, _ = harness
    data = client.get(f"/v1/admin/merchant/revenue/detail{PERIOD}&party={ACME}", headers=AUTH).json()["data"]
    assert data["party"] == {"key": ACME, "name": "합성테크"}
    paid = data["paid_basis"]
    assert (paid["revenue_amount"], paid["invoice_amount"], paid["net_payment_amount"], paid["entry_count"]) == (176000, 176000, 0, 1)
    assert paid["entries"][0] == {
        "kind": "invoice", "at": "2026-11-05T05:00:00+00:00", "amount": 176000, "label": "세금계산서 발행",
        "method": "20261105-1", "person_name": "-", "department": None, "employee_no": None,
        "supply_amount": 160000, "vat_amount": 16000, "write_date": "2026-10-31", "purchase_charge_amount": 0,
    }
    usage = data["usage_basis"]
    assert (usage["amount"], usage["count"], usage["cancel_count"], usage["item_count"]) == (8800, 2, 1, 3)
    assert usage["daily"] == [
        {"date": "2026-11-15", "count": 1, "cancel_count": 1, "amount": 0},
        {"date": "2026-11-03", "count": 1, "cancel_count": 0, "amount": 8800},
    ]
    assert [(i["id"], i["kind"], i["amount"], i["person_name"], i["employee_no"]) for i in usage["items"]] == [
        (1, "spend", 8800, "김하늘", "E1"), (2, "spend", 8800, "김하늘", "E1"), (3, "cancel", -8800, "김하늘", "E1")]
    assert data["unbilled"] == {"amount": 8800, "settlements": [
        {"period_ym": "2026-11", "amount": 8800, "settlement_status": "draft", "tax_invoice_status": "not_requested"}]}


def test_personal_detail_lists_payments_and_refunds(harness):
    client, _, _, _, _ = harness
    data = client.get(f"/v1/admin/merchant/revenue/detail{PERIOD}&party=personal", headers=AUTH).json()["data"]
    assert data["party"] == {"key": "personal", "name": "개인 고객"}
    assert all(e["point_amount"] == 0 for e in data["paid_basis"]["entries"])
    assert [(e["kind"], e["amount"], e["label"], e["method"], e["person_name"]) for e in data["paid_basis"]["entries"]] == [
        ("refund", -8000, "1장 식권", "네이버페이", "이손님"),
        ("payment", 8000, "1장 식권", "네이버페이", "이손님"),
        ("payment", 80000, "11장 식권", "카드", "이손님"),
    ]
    assert (data["paid_basis"]["payment_amount"], data["paid_basis"]["refund_amount"], data["paid_basis"]["revenue_amount"]) == (88000, 8000, 80000)
    assert (data["usage_basis"]["amount"], data["usage_basis"]["count"]) == (8000, 1)
    assert data["unbilled"] == {"amount": 0, "settlements": []}


def test_only_own_partner_companies_and_valid_periods_are_served(harness):
    client, _, _, actor, repo = harness
    # BETA exists but has no contract row with this restaurant in the fixture.
    assert client.get(f"/v1/admin/merchant/revenue/detail{PERIOD}&party={BETA}", headers=AUTH).status_code == 404
    assert client.get(f"/v1/admin/merchant/revenue/detail{PERIOD}&party=55555555-5555-4555-8555-555555555555", headers=AUTH).status_code == 404
    assert client.get(f"/v1/admin/merchant/revenue/detail{PERIOD}&party=all", headers=AUTH).status_code == 422
    assert client.get("/v1/admin/merchant/revenue/summary?from=2026-11-30&to=2026-11-01", headers=AUTH).status_code == 422
    assert client.get("/v1/admin/merchant/revenue/summary?from=2025-01-01&to=2026-11-01", headers=AUTH).status_code == 422
    actor.side_effect = JoinFlowError("FORBIDDEN", "식당관리자만 이용할 수 있어요")
    assert client.get(f"/v1/admin/merchant/revenue/summary{PERIOD}", headers=AUTH).status_code == 403
    actor.side_effect = None
    repo.client.rest_get.side_effect = SupabaseHttpError(500, "boom")
    assert client.get(f"/v1/admin/merchant/revenue/summary{PERIOD}", headers=AUTH).status_code == 502


def test_points_are_left_out_of_revenue_and_reported_separately(harness):
    client, tables, _, _, _ = harness
    tables["merchant_companies"].append({"company_id": BETA})
    # A refund that also gives 300 points back.
    tables["refund_requests"].append({"id": "r2", "order_id": "o3", "user_id": "u2", "refund_amount": 2000, "point_amount": 300,
                                      "status": "completed", "created_at": "2026-11-11T01:00:00+00:00", "completed_at": "2026-11-11T02:00:00+00:00"})
    summary = client.get(f"/v1/admin/merchant/revenue/summary{PERIOD}", headers=AUTH).json()["data"]
    beta = next(p for p in summary["parties"] if p["name"] == "가온상사")
    assert (beta["payment_amount"], beta["refund_amount"], beta["net_payment_amount"], beta["point_amount"], beta["revenue_amount"]) == (5000, 2000, 3000, 700, 3000)
    assert summary["paid_basis"]["point_amount"] == 700
    detail = client.get(f"/v1/admin/merchant/revenue/detail{PERIOD}&party={BETA}", headers=AUTH).json()["data"]
    assert [(e["kind"], e["amount"], e["point_amount"]) for e in detail["paid_basis"]["entries"]] == [("refund", -2000, -300), ("payment", 5000, 1000)]
    assert detail["paid_basis"]["revenue_amount"] == 3000
