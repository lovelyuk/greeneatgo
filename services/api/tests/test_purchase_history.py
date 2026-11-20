"""Buyer purchase history and receipt, over HTTP with fixture-only I/O."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.repositories.supabase_http import SupabaseHttpError
from app.routers.payments import ORDER_SELECT, router

USER_ID = "fixture-user"
SETTINGS = SimpleNamespace(kiwoompay_base_url="https://api.kiwoompay.co.kr", kiwoompay_cpid="FIXTURE")


def order(**overrides):
    row = {
        "id": "private-db-id", "user_id": USER_ID, "order_id": "GE-V-fixture-1", "amount": 8000,
        "status": "done", "pay_type": "voucher", "payment_method": "CARD", "tax_type": "taxable",
        "merchant_id": "merchant-1", "merchant_name": "가산 한식뷔페", "product_name": "1장 식권",
        "voucher_count": 1, "approved_at": "2026-11-19T03:08:00+00:00", "created_at": "2026-11-19T03:07:00+00:00",
        "provider_payment_key": "DAOU123", "provider_response": {
            "AUTHNO": "30011223", "CARDNAME": "신한카드", "CARDNO": "5107370000008900", "secret": "never-shown"},
    }
    row.update(overrides)
    return row


@pytest.fixture
def harness():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    with patch("app.routers.payments.JoinRepository") as repo_class, patch(
        "app.routers.payments.get_settings", return_value=SETTINGS,
    ):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id=USER_ID, email=None)
        repo.get_profile.return_value = SimpleNamespace(id=USER_ID, status="active", role="customer")
        yield TestClient(app), repo


AUTH = {"Authorization": "Bearer fixture"}


def test_history_lists_only_own_paid_orders_newest_first(harness):
    client, repo = harness
    repo.client.rest_get.return_value = [order(), order(order_id="GE-V-fixture-0", amount=0, status="refunded", payment_method=None)]
    response = client.get("/v1/payments/history", headers=AUTH)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    table, params = repo.client.rest_get.call_args.args
    assert table == "payment_orders"
    assert params["user_id"] == f"eq.{USER_ID}"
    assert params["status"] == "in.(done,refund_processing,refunded)"
    assert params["order"].startswith("approved_at.desc")
    items = response.json()["data"]["items"]
    assert items[0] == {
        "order_id": "GE-V-fixture-1", "product_name": "1장 식권", "merchant_id": "merchant-1",
        "merchant_name": "가산 한식뷔페", "amount": 8000, "status": "done", "pay_type": "voucher",
        "method": "CARD", "method_label": "카드", "voucher_count": 1,
        "approved_at": "2026-11-19T03:08:00+00:00", "has_receipt": True,
    }
    # A point-only order has no provider slip.
    assert items[1]["has_receipt"] is False and items[1]["method_label"] is None
    assert "private-db-id" not in response.text


def test_receipt_is_owner_scoped_and_hides_provider_payload(harness):
    client, repo = harness
    repo.client.rest_get.return_value = [order()]
    response = client.get("/v1/payments/history/GE-V-fixture-1", headers=AUTH)
    assert response.status_code == 200
    table, params = repo.client.rest_get.call_args.args
    assert (table, params["select"]) == ("payment_orders", ORDER_SELECT)
    assert params["order_id"] == "eq.GE-V-fixture-1" and params["user_id"] == f"eq.{USER_ID}"
    data = response.json()["data"]
    assert data["refund"] is None
    assert data["slip_title"] == "카드 매출전표"
    assert data["completion"]["payment"]["authorization_number"] == "30011223"
    assert data["completion"]["payment"]["masked_card_number"].endswith("8900") and "5107370000008900" not in response.text
    assert data["completion"]["receipts"]["sales_slip_url"].startswith("https://agent.kiwoompay.co.kr/")
    assert data["receipt"]["lookup"] == {"date": "2026-11-19", "amount": 8000, "number": "30011223", "number_type": "approval"}
    assert "never-shown" not in response.text and "private-db-id" not in response.text


def test_refunded_order_carries_the_refund(harness):
    client, repo = harness

    def rest_get(table, params):
        if table == "payment_orders":
            return [order(status="refunded")]
        assert table == "refund_requests"
        assert params["order_id"] == "eq.private-db-id" and params["user_id"] == f"eq.{USER_ID}"
        return [{"status": "completed", "refund_amount": 8000, "point_amount": 0, "completed_at": "2026-11-20T00:10:00+00:00"}]

    repo.client.rest_get.side_effect = rest_get
    data = client.get("/v1/payments/history/GE-V-fixture-1", headers=AUTH).json()["data"]
    assert data["summary"]["status"] == "refunded"
    assert data["refund"] == {"status": "completed", "refund_amount": 8000, "point_amount": 0, "completed_at": "2026-11-20T00:10:00+00:00"}


def test_refund_in_progress_has_no_completion_time(harness):
    client, repo = harness
    repo.client.rest_get.side_effect = lambda table, params: [order(status="refund_processing")] if table == "payment_orders" else []
    data = client.get("/v1/payments/history/GE-V-fixture-1", headers=AUTH).json()["data"]
    assert data["refund"] == {"status": "processing", "refund_amount": None, "point_amount": None, "completed_at": None}


def test_unknown_or_foreign_order_is_404_and_bad_ids_are_rejected(harness):
    client, repo = harness
    repo.client.rest_get.return_value = []
    assert client.get("/v1/payments/history/GE-V-someone-else", headers=AUTH).status_code == 404
    assert client.get("/v1/payments/history/a%20b%27c", headers=AUTH).status_code == 422
    assert client.get("/v1/payments/history", params={"limit": 1000}, headers=AUTH).status_code == 422


def test_admin_accounts_are_refused_and_database_errors_are_mapped(harness):
    client, repo = harness
    repo.get_profile.return_value = SimpleNamespace(id=USER_ID, status="active", role="merchant_admin")
    assert client.get("/v1/payments/history", headers=AUTH).status_code == 403
    repo.get_profile.return_value = SimpleNamespace(id=USER_ID, status="active", role="employee")
    repo.client.rest_get.side_effect = SupabaseHttpError(500, "boom")
    assert client.get("/v1/payments/history", headers=AUTH).status_code == 502
    assert client.get("/v1/payments/history/GE-V-fixture-1", headers=AUTH).status_code == 502
