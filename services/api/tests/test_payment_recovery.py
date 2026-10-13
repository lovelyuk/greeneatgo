"""Recovery router exercised over HTTP; all database/provider I/O is fixture-only."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.repositories.supabase_http import SupabaseHttpError
from app.routers.payments import ORDER_SELECT, router
from app.services.payment_completion import present_payment_completion


ORDER_ID = "GE-V-fixture-order"
USER_ID = "fixture-user"
SETTINGS = SimpleNamespace(
    public_api_base_url="https://api.example.invalid/v1/",
    kiwoompay_base_url="https://apitest.kiwoompay.co.kr",
    kiwoompay_cpid="FIXTURE",
)


def order(**overrides):
    row = {
        "id": "private-db-id", "user_id": USER_ID, "order_id": ORDER_ID,
        "checkout_token": "existing_fixture_token", "amount": 8000,
        "status": "ready", "pay_type": "direct", "tax_type": "taxable",
        "requested_payment_method": "TOTAL", "merchant_id": "private-merchant",
        "product_name": "Fixture meal", "merchant_name": "Fixture restaurant",
        "provider_response": {"CARDNO": "5107370000008900", "private": "hidden-provider"},
    }
    row.update(overrides)
    return row


@pytest.fixture
def harness():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    with patch("app.routers.payments.JoinRepository") as repo_class, patch(
        "app.routers.payments.get_settings", return_value=SETTINGS
    ), patch("app.routers.payments.request_payment_hash") as provider, patch(
        "app.routers.payments.time.sleep"
    ) as sleep:
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id=USER_ID, email="fixture@example.invalid")
        repo.get_profile.return_value = SimpleNamespace(id=USER_ID, status="active", role="customer")
        repo.client.rest_get.return_value = [order()]
        yield TestClient(app), repo, provider, sleep
        provider.assert_not_called()
        sleep.assert_not_called()
        repo.client.rest_post.assert_not_called()
        repo.client.rest_patch.assert_not_called()
        repo.client.rest_delete.assert_not_called()
        assert all(c.args[0] == "expire_stale_subsidized_orders" for c in repo.client.rpc.call_args_list)


def recover(client, **params):
    return client.get("/v1/payments/recovery", params={"order_id": ORDER_ID, "amount": "8000", **params}, headers={"Authorization": "Bearer fixture-token"})


def assert_error(response, status, code):
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert "existing_fixture_token" not in response.text
    assert "hidden-provider" not in response.text
    assert "private-db-id" not in response.text


@pytest.mark.parametrize("role", ["customer", "employee"])
def test_ready_never_returns_payable_checkout_scoped_to_authenticated_owner(harness, role):
    client, repo, _, _ = harness
    repo.get_profile.return_value.role = role
    response = recover(client)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "data": {
        "order_id": ORDER_ID, "amount": 8000, "status": "ready",
        "recovery_action": "reconcile", "checkout_url": None, "resumable": False,
    }, "error": None}
    repo.client.rest_get.assert_called_once_with("payment_orders", {
        "select": ORDER_SELECT, "order_id": f"eq.{ORDER_ID}", "user_id": f"eq.{USER_ID}", "limit": "1",
    })
    repo.client.rpc.assert_not_called()


@pytest.mark.parametrize("role", ["platform_admin", "merchant_admin", "company_admin"])
def test_admins_cannot_recover_even_their_own_orders(harness, role):
    client, repo, _, _ = harness
    repo.get_profile.return_value.role = role
    assert_error(recover(client), 403, "CUSTOMER_ONLY")
    repo.client.rest_get.assert_not_called()


@pytest.mark.parametrize("profile", [None, SimpleNamespace(id=USER_ID, role="customer", status="inactive")])
def test_only_active_accounts(harness, profile):
    client, repo, _, _ = harness
    repo.get_profile.return_value = profile
    assert_error(recover(client), 403, "CUSTOMER_ONLY")
    repo.client.rest_get.assert_not_called()


def test_missing_auth_rejected_without_repository_io(harness):
    client, repo, _, _ = harness
    response = client.get("/v1/payments/recovery", params={"order_id": ORDER_ID, "amount": "8000"})
    assert_error(response, 401, "UNAUTHENTICATED")
    repo.auth_user_from_token.assert_not_called()


@pytest.mark.parametrize("missing", [True, False])
def test_nonexistent_and_other_users_orders_indistinguishable(harness, missing):
    client, repo, _, _ = harness
    def scoped_get(table, filters):
        assert table == "payment_orders"
        assert filters["user_id"] == f"eq.{USER_ID}"
        other = order(user_id="other-user")
        return [] if missing or filters["user_id"] != f"eq.{other['user_id']}" else [other]
    repo.client.rest_get.side_effect = scoped_get
    assert_error(recover(client), 404, "ORDER_NOT_FOUND")
    repo.client.rpc.assert_not_called()


@pytest.mark.parametrize("status", ["ready", "done", "canceled"])
def test_amount_mismatch_prevents_disclosure_and_expiry(harness, status):
    client, repo, _, _ = harness
    repo.client.rest_get.return_value = [order(status=status, pay_type="subsidized")]
    assert_error(recover(client, amount="7999"), 400, "AMOUNT_MISMATCH")
    repo.client.rpc.assert_not_called()


@pytest.mark.parametrize("params", [
    {"amount": "0"}, {"amount": "-1"}, {"amount": "8000.5"}, {"amount": "nope"},
    {"order_id": ""}, {"order_id": "short"}, {"order_id": "x" * 65},
    {"order_id": " GE-V-fixture-order"}, {"order_id": "GE-V-fixture-order "},
])
def test_invalid_query_rejected_before_io(harness, params):
    client, repo, _, _ = harness
    assert recover(client, **params).status_code == 422
    repo.auth_user_from_token.assert_not_called()


def test_done_uses_existing_completion_presenter_without_polling(harness):
    client, repo, _, _ = harness
    row = order(status="done", pay_type="voucher", voucher_count=3, payment_method="CARD", provider_payment_key="fixture-trx")
    repo.client.rest_get.return_value = [row]
    response = recover(client)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "data": {
        "order_id": ORDER_ID, "amount": 8000, "status": "done", "recovery_action": "complete", "checkout_url": None, "resumable": False,
        "completion": present_payment_completion(row, base_url=SETTINGS.kiwoompay_base_url, cpid=SETTINGS.kiwoompay_cpid),
    }, "error": None}
    assert "5107370000008900" not in response.text
    assert "hidden-provider" not in response.text
    assert "existing_fixture_token" not in response.text
    assert "private-db-id" not in response.text
    repo.client.rest_get.assert_called_once()
    repo.client.rpc.assert_not_called()


@pytest.mark.parametrize("status,public_status", [
    ("canceled", "canceled"), ("failed", "failed"), ("refunded", "refunded"),
    ("refund_processing", "refund_processing"), ("provider-private-state", "unknown"), (None, "unknown"),
])
def test_ambiguous_states_never_clear_pending_or_expose_checkout(harness, status, public_status):
    client, repo, _, _ = harness
    repo.client.rest_get.return_value = [order(status=status, tax_type="unclassified")]
    response = recover(client)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "data": {
        "order_id": ORDER_ID, "amount": 8000, "status": public_status,
        "recovery_action": "reconcile", "checkout_url": None, "resumable": False,
    }, "error": None}
    repo.client.rpc.assert_not_called()


@pytest.mark.parametrize("status", ["ready", "done"])
def test_tax_guard_preserved(harness, status):
    client, repo, _, _ = harness
    repo.client.rest_get.return_value = [order(status=status, tax_type="unclassified")]
    assert_error(recover(client), 409, "TAX_TYPE_UNCLASSIFIED")


@pytest.mark.parametrize("pay_type", ["voucher", "subsidized"])
def test_unavailable_product_cannot_resume(harness, pay_type):
    client, repo, _, _ = harness
    row = order(pay_type=pay_type, voucher_product_id="fixture-product", voucher_count=2)
    repo.client.rest_get.side_effect = [[row], [row], []] if pay_type == "subsidized" else [[row], []]
    assert_error(recover(client), 409, "VOUCHER_PRODUCT_NOT_EXPOSED")


@pytest.mark.parametrize("started", [None, "2026-01-01T00:00:00Z"])
def test_subsidized_ready_uses_db_expiry_and_does_not_mark_or_cancel(harness, started):
    client, repo, _, _ = harness
    row = order(pay_type="subsidized", checkout_started_at=started, voucher_count=1, paid_voucher_count=1, bonus_voucher_count=0)
    repo.client.rest_get.side_effect = [[row], [row]]
    response = recover(client)
    assert response.status_code == 200
    assert response.json()["data"]["recovery_action"] == "reconcile"
    repo.client.rpc.assert_called_once_with("expire_stale_subsidized_orders", {"p_user_id": USER_ID})


def test_expired_subsidized_order_keeps_existing_error_guard(harness):
    client, repo, _, _ = harness
    repo.client.rest_get.side_effect = [[order(pay_type="subsidized")], [order(pay_type="subsidized", status="canceled")]]
    assert_error(recover(client), 409, "ORDER_EXPIRED")


@pytest.mark.parametrize("refreshed", [[], [order(status="done", pay_type="subsidized")]])
def test_expiry_refresh_cannot_return_stale_resume_url(harness, refreshed):
    client, repo, _, _ = harness
    repo.client.rest_get.side_effect = [[order(pay_type="subsidized")], refreshed]
    expected = (409, "ORDER_NOT_READY") if refreshed else (404, "ORDER_NOT_FOUND")
    assert_error(recover(client), *expected)


def test_ready_invalid_method_is_blocked(harness):
    client, repo, _, _ = harness
    repo.client.rest_get.return_value = [order(requested_payment_method="INVALID")]
    assert_error(recover(client), 409, "INVALID_PAYMENT_METHOD")


def test_missing_checkout_token_requires_reconciliation(harness):
    client, repo, _, _ = harness
    repo.client.rest_get.return_value = [order(checkout_token=None)]
    response = recover(client)
    assert response.status_code == 200
    assert response.json()["data"]["recovery_action"] == "reconcile"
    assert response.json()["data"]["checkout_url"] is None


@pytest.mark.parametrize("stage", ["auth", "profile", "order", "expiry", "refresh", "availability"])
def test_database_failures_are_bounded_and_do_not_leak(harness, stage):
    client, repo, _, _ = harness
    failure = SupabaseHttpError(503, "hidden-provider private-db-id existing_fixture_token")
    if stage == "auth":
        repo.auth_user_from_token.side_effect = failure
    elif stage == "profile":
        repo.get_profile.side_effect = failure
    elif stage == "order":
        repo.client.rest_get.side_effect = failure
    elif stage in {"expiry", "refresh"}:
        repo.client.rest_get.side_effect = [[order(pay_type="subsidized")], failure]
        if stage == "expiry":
            repo.client.rpc.side_effect = failure
    else:
        repo.client.rest_get.side_effect = [[order(pay_type="voucher", voucher_product_id="fixture-product")], failure]
    assert_error(recover(client), 502, "SUPABASE_ERROR")


def test_invalid_auth_token_maps_to_unauthenticated(harness):
    client, repo, _, _ = harness
    repo.auth_user_from_token.side_effect = SupabaseHttpError(401, "private-auth-body")
    assert_error(recover(client), 401, "UNAUTHENTICATED")


@pytest.mark.parametrize("pay_type", ["direct", "voucher", "subsidized"])
@pytest.mark.parametrize("started", [None, "2026-01-01T00:00:00Z"])
def test_every_recovery_order_is_nonpayable_even_if_prior_entry_uncertain(harness, pay_type, started):
    client, repo, _, _ = harness
    row = order(pay_type=pay_type, checkout_started_at=started, voucher_count=1, paid_voucher_count=1, bonus_voucher_count=0, voucher_product_id="fixture-product" if pay_type == "voucher" else None)
    repo.client.rest_get.side_effect = lambda table, params: [{"id": "fixture-product", "status": "active", "is_event": False}] if table == "voucher_products" else [row]
    response = recover(client)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["recovery_action"] == "reconcile"
    assert data["resumable"] is False
    assert data["checkout_url"] is None
    assert "existing_fixture_token" not in response.text
