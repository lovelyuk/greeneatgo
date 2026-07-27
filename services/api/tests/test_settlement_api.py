from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import bearer_token
from app.main import app
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.settlements import get_settlement_repository
from app.services.join_flow import UserProfile

SETTLEMENT_ID = "11111111-1111-1111-1111-111111111111"

class FakeSettlements:
    def __init__(self, actor):
        self._actor = actor
        self.calls = []
        self.confirm_error = None
        self.detail = {"id": SETTLEMENT_ID, "tax_invoice_status": "issued", "tax_invoices": [], "events": []}

    def actor(self, token, role):
        assert role == self._actor.role
        return self._actor

    def list_company(self, company_id, limit, offset, period_ym=None):
        self.calls.append(("list_company", company_id, limit, offset, period_ym))
        return [{"id": SETTLEMENT_ID, "company_id": company_id, "status": "draft"}]

    def company_month_summary(self, company_id, period_ym):
        self.calls.append(("company_month_summary", company_id, period_ym))
        return {"settlement_count": 7, "paid_count": 2, "tx_count": 9, "total_amount": 11000}

    def list_merchant(self, merchant_id, limit, offset):
        self.calls.append(("list_merchant", merchant_id, limit, offset))
        return [{"id": "s1", "merchant_id": merchant_id}]

    def company_detail(self, settlement_id, company_id):
        self.calls.append(("company_detail", settlement_id, company_id))
        return self.detail if company_id == "company-own" else None

    def merchant_detail(self, settlement_id, merchant_id):
        self.calls.append(("merchant_detail", settlement_id, merchant_id))
        return self.detail if merchant_id == "merchant-own" else None

    def confirm(self, actor, settlement_id):
        self.calls.append(("confirm", actor.company_id, settlement_id))
        if self.confirm_error is not None:
            raise self.confirm_error
        return {"idempotent": False}

    def dispute(self, actor, settlement_id, reason, key):
        self.calls.append(("dispute", actor.company_id, settlement_id, reason, key))
        return {"idempotent": False}

    def send(self, actor, settlement_id):
        self.calls.append(("send", actor.merchant_id, settlement_id))
        return {"idempotent": False}

    def mark_paid(self, actor, settlement_id, payload):
        self.calls.append(("paid", actor.merchant_id, settlement_id, payload.idempotency_key))
        return {"idempotent": False}


@pytest.fixture
def client_factory():
    clients = []

    def make(role):
        actor = UserProfile(id="actor", email="a@example.com", display_name="actor", role=role,
                            status="active", company_id="company-own" if role == "company_admin" else None,
                            merchant_id="merchant-own" if role == "merchant_admin" else None)
        repo = FakeSettlements(actor)
        app.dependency_overrides[bearer_token] = lambda: "token"
        app.dependency_overrides[get_settlement_repository] = lambda: repo
        client = TestClient(app)
        clients.append(client)
        return client, repo

    yield make
    app.dependency_overrides.clear()
    for client in clients:
        client.close()


def test_company_routes_scope_server_tenant_and_alias_is_company_only(client_factory):
    client, repo = client_factory("company_admin")
    response = client.get("/v1/company/settlements?limit=100&offset=4")
    assert response.status_code == 200
    assert repo.calls[-1] == ("list_company", "company-own", 100, 4, None)
    alias = client.get("/v1/admin/settlements?ym=2026-07")
    assert alias.status_code == 200
    assert repo.calls[-2] == ("list_company", "company-own", 20, 0, "2026-07")
    assert repo.calls[-1] == ("company_month_summary", "company-own", "2026-07")
    assert "summary" in alias.json()["data"]
    assert alias.json()["data"]["summary"]["settlement_count"] == 7
    assert client.get(f"/v1/admin/settlements/{SETTLEMENT_ID}").status_code == 200
    assert str(repo.calls[-1][1]) == SETTLEMENT_ID
    assert client.get("/v1/company/settlements?limit=101").status_code == 422


def test_confirm_requires_all_three_explicit_true_and_uses_no_client_snapshot(client_factory):
    client, repo = client_factory("company_admin")
    path = f"/v1/company/settlements/{SETTLEMENT_ID}/confirm-and-request-tax-invoice"
    assert client.post(path, json={"business_info_accurate": True, "email_accurate": True}).status_code == 422
    assert client.post(path, json={"business_info_accurate": True, "email_accurate": False, "amount_checked": True}).status_code == 422
    response = client.post(path, json={"business_info_accurate": True, "email_accurate": True, "amount_checked": True,
                                      "total_amount": 1, "recipient_snapshot": {"name": "attacker"}})
    assert response.status_code == 200
    assert repo.calls[-1][0:2] == ("confirm", "company-own")
    assert str(repo.calls[-1][2]) == SETTLEMENT_ID


def test_confirm_maps_incomplete_supplier_profile_to_stable_422(client_factory):
    client, repo = client_factory("company_admin")
    repo.confirm_error = SupabaseHttpError(
        400,
        '{"code":"P0001","message":"SUPPLIER_PROFILE_INCOMPLETE"}',
    )
    response = client.post(
        f"/v1/company/settlements/{SETTLEMENT_ID}/confirm-and-request-tax-invoice",
        json={
            "business_info_accurate": True,
            "email_accurate": True,
            "amount_checked": True,
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SUPPLIER_PROFILE_INCOMPLETE"


def test_company_dispute_and_merchant_actions_pass_tenant_and_idempotency(client_factory):
    client, repo = client_factory("company_admin")
    assert client.post(f"/v1/company/settlements/{SETTLEMENT_ID}/dispute", json={"reason": "  ", "idempotency_key": "k"}).status_code == 422
    assert client.post(f"/v1/company/settlements/{SETTLEMENT_ID}/dispute", json={"reason": "wrong amount", "idempotency_key": "k"}).status_code == 200
    assert repo.calls[-1][0:2] == ("dispute", "company-own")
    assert str(repo.calls[-1][2]) == SETTLEMENT_ID
    assert repo.calls[-1][3:] == ("wrong amount", "k")

    client, repo = client_factory("merchant_admin")
    assert client.post(f"/v1/admin/merchant/settlements/{SETTLEMENT_ID}/send").status_code == 200
    paid = {"amount": 1100, "depositor_name": "Green Eat", "deposited_at": datetime.now(timezone.utc).isoformat(),
            "memo": "bank match", "idempotency_key": "payment-key"}
    assert client.post(f"/v1/admin/merchant/settlements/{SETTLEMENT_ID}/mark-paid", json=paid).status_code == 200
    assert repo.calls[-1][0:2] == ("paid", "merchant-own")
    assert str(repo.calls[-1][2]) == SETTLEMENT_ID
    assert repo.calls[-1][3] == "payment-key"


def test_popbill_routes_fail_closed_after_tenant_and_issued_validation(client_factory):
    client, repo = client_factory("company_admin")
    response = client.get(f"/v1/company/settlements/{SETTLEMENT_ID}/tax-invoice/pdf")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "POPBILL_NOT_CONFIGURED"
    repo.detail = {**repo.detail, "tax_invoice_status": "requested"}
    assert client.get(f"/v1/company/settlements/{SETTLEMENT_ID}/tax-invoice/view").status_code == 409

    client, repo = client_factory("merchant_admin")
    response = client.post(f"/v1/admin/merchant/settlements/{SETTLEMENT_ID}/tax-invoice/issue")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "POPBILL_NOT_CONFIGURED"
    assert repo.calls[-1][0] == "merchant_detail"
    assert str(repo.calls[-1][1]) == SETTLEMENT_ID
    assert repo.calls[-1][2] == "merchant-own"
