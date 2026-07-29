from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.auth import bearer_token
import app.routers.settlements as settlements_router
from app.main import app
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.settlements import get_popbill_service, get_settlement_repository
from app.services.join_flow import UserProfile
from app.services.popbill_service import PopbillError, PopbillIssueResult, PopbillStatus, PopbillURLResult

SETTLEMENT_ID = "11111111-1111-1111-1111-111111111111"

class FakeSettlements:
    def __init__(self, actor):
        self._actor = actor
        self.calls = []
        self.confirm_error = None
        self.demo = False
        self.detail = {"id": SETTLEMENT_ID, "tax_invoice_status": "issued", "tax_invoices": [
            {"document_type": "original", "invoicer_mgt_key": "GEAAAAAAAAAAAAAAAAAAAAAA"}
        ], "events": []}
        self.claim = {"action": "issue", "attempt_token": "22222222-2222-2222-2222-222222222222",
                      "tax_invoice": self.detail["tax_invoices"][0]}

    def actor(self, token, role):
        assert role == self._actor.role
        return self._actor

    def list_company(self, company_id, limit, offset, period_ym=None):
        self.calls.append(("list_company", company_id, limit, offset, period_ym))
        return [{"id": SETTLEMENT_ID, "company_id": company_id, "status": "draft"}]

    def company_month_summary(self, actor, period_ym):
        self.calls.append(("company_month_summary", actor.id, actor.company_id, period_ym))
        return {"settlement_count": 7, "paid_count": 2, "tx_count": 9, "total_amount": 11000}

    def list_merchant(self, merchant_id, limit, offset):
        self.calls.append(("list_merchant", merchant_id, limit, offset))
        return [{"id": "s1", "merchant_id": merchant_id}]

    def supplier_popbill_readiness(self, merchant_id, configured_corp_num):
        self.calls.append(("readiness", merchant_id, configured_corp_num))
        return {"supplier_ready": True, "corp_matches": True}

    def company_detail(self, settlement_id, company_id, *, include_transactions=False):
        self.calls.append(("company_detail", settlement_id, company_id, True) if include_transactions
                          else ("company_detail", settlement_id, company_id))
        return self.detail if company_id == "company-own" else None

    def merchant_detail(self, settlement_id, merchant_id, *, include_transactions=False):
        self.calls.append(("merchant_detail", settlement_id, merchant_id, True) if include_transactions
                          else ("merchant_detail", settlement_id, merchant_id))
        return self.detail if merchant_id == "merchant-own" and not self.demo else None

    def is_demo_settlement(self, merchant_id, settlement_id):
        return self.demo and merchant_id == "merchant-own"

    def merchant_demo_detail(self, settlement_id, merchant_id, *, include_transactions=False):
        self.calls.append(("merchant_demo_detail", settlement_id, merchant_id, include_transactions))
        return {**self.detail, "is_demo": True} if self.is_demo_settlement(merchant_id, settlement_id) else None

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

    def begin_revision(self, actor, settlement_id):
        self.calls.append(("begin_revision", actor.merchant_id, settlement_id))
        return {"idempotent": False}

    def mark_paid(self, actor, settlement_id, payload):
        self.calls.append(("paid", actor.merchant_id, settlement_id, payload.idempotency_key))
        return {"idempotent": False}

    def claim_invoice_issue(self, actor, settlement_id):
        self.calls.append(("claim", actor.merchant_id, settlement_id))
        return self.claim

    def finalize_invoice_issue(self, actor, settlement_id, token, outcome, failure_code=None, failure_message=None):
        self.calls.append(("finalize", outcome, token, failure_code, failure_message))
        return {"settlement": {"tax_invoice_status": "issued" if outcome == "success" else "issuing"},
                "tax_invoice": self.claim["tax_invoice"]}

    def apply_invoice_status(self, actor, settlement_id, status):
        self.calls.append(("apply", status.provider_state_code, status.nts_accepted))
        return {"settlement": {"tax_invoice_status": "nts_accepted" if status.nts_accepted else "issued"}}

    def original_invoice_management_key(self, actor, settlement_id):
        self.calls.append(("management_key", actor.role, settlement_id))
        return "GEAAAAAAAAAAAAAAAAAAAAAA"


class FakePopbill:
    def __init__(self, issue_error=None):
        self.issue_error = issue_error
        self.calls = []

    def issue(self, invoice, *, allow_delayed_issue=False):
        self.calls.append(("issue", invoice["invoicer_mgt_key"], allow_delayed_issue))
        if self.issue_error:
            raise self.issue_error
        return PopbillIssueResult(invoice["invoicer_mgt_key"], 1, False)

    def get_status(self, key):
        self.calls.append(("status", key))
        return PopbillStatus(key, "item", 304, None, True, "nts", "20260701", "20260701", "20260701")

    def get_view_url(self, key):
        self.calls.append(("view", key))
        return PopbillURLResult(key, "view", "https://provider.example/view")

    def get_pdf_url(self, key):
        self.calls.append(("pdf", key))
        return PopbillURLResult(key, "pdf", "https://provider.example/pdf")


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


def test_popbill_readiness_is_merchant_scoped_and_exposes_no_credentials(client_factory, monkeypatch):
    client, repo = client_factory("merchant_admin")
    monkeypatch.setattr(settlements_router, "get_settings", lambda: SimpleNamespace(
        popbill_link_id="link", popbill_secret_key="secret", popbill_corp_num="123-45-67890",
        popbill_user_id="user", popbill_is_test=True, popbill_ip_restrict_on=True,
        popbill_use_static_ip=False, popbill_use_local_time=True,
    ))
    class ReadyPopbill:
        def __init__(self, config):
            self.config = config

        def certificate_readiness(self):
            return SimpleNamespace(
                certificate_verified=True,
                certificate_expires_on="2027-07-27",
            )

    monkeypatch.setattr(settlements_router, "PopbillService", ReadyPopbill)

    response = client.get("/v1/admin/merchant/settlements/popbill-readiness")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "configured": True,
        "is_test": True,
        "certificate_verified": True,
        "certificate_expires_on": "2027-07-27",
        "supplier_ready": True,
        "corp_matches": True,
    }
    assert repo.calls[-1] == ("readiness", "merchant-own", "123-45-67890")
    assert "secret" not in response.text and "link" not in response.text


def test_popbill_readiness_separates_configuration_from_provider_failure(
    client_factory, monkeypatch
):
    client, _ = client_factory("merchant_admin")
    monkeypatch.setattr(settlements_router, "get_settings", lambda: SimpleNamespace(
        popbill_link_id="link", popbill_secret_key="secret", popbill_corp_num="123-45-67890",
        popbill_user_id="user", popbill_is_test=True, popbill_ip_restrict_on=True,
        popbill_use_static_ip=False, popbill_use_local_time=True,
    ))

    class UnreachablePopbill:
        def __init__(self, config):
            self.config = config

        def certificate_readiness(self):
            raise PopbillError("POPBILL_TEMPORARILY_UNAVAILABLE", "safe")

    monkeypatch.setattr(settlements_router, "PopbillService", UnreachablePopbill)

    response = client.get("/v1/admin/merchant/settlements/popbill-readiness")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "configured": True,
        "is_test": True,
        "certificate_verified": False,
        "certificate_expires_on": None,
        "supplier_ready": True,
        "corp_matches": True,
    }
    assert "secret" not in response.text and "link" not in response.text


def test_company_routes_scope_server_tenant_and_alias_is_company_only(client_factory):
    client, repo = client_factory("company_admin")
    response = client.get("/v1/company/settlements?limit=100&offset=4")
    assert response.status_code == 200
    assert repo.calls[-1] == ("list_company", "company-own", 100, 4, None)
    alias = client.get("/v1/admin/settlements?ym=2026-07")
    assert alias.status_code == 200
    assert repo.calls[-2] == ("list_company", "company-own", 20, 0, "2026-07")
    assert repo.calls[-1] == ("company_month_summary", "actor", "company-own", "2026-07")
    assert "summary" in alias.json()["data"]
    assert alias.json()["data"]["summary"]["settlement_count"] == 7
    assert client.get(f"/v1/admin/settlements/{SETTLEMENT_ID}").status_code == 200
    assert str(repo.calls[-1][1]) == SETTLEMENT_ID
    assert client.get(f"/v1/admin/settlements/{SETTLEMENT_ID}?include_transactions=true").status_code == 200
    assert repo.calls[-1][0] == "company_detail"
    assert str(repo.calls[-1][1]) == SETTLEMENT_ID
    assert repo.calls[-1][2:] == ("company-own", True)
    assert client.get("/v1/company/settlements?limit=101").status_code == 422


def test_merchant_detail_falls_back_to_owned_demo_detail_and_keeps_transactions_flag(client_factory):
    client, repo = client_factory("merchant_admin")
    repo.demo = True

    response = client.get(f"/v1/admin/merchant/settlements/{SETTLEMENT_ID}?include_transactions=true")

    assert response.status_code == 200
    assert response.json()["data"]["is_demo"] is True
    assert repo.calls == [
        ("merchant_detail", UUID(SETTLEMENT_ID), "merchant-own", True),
        ("merchant_demo_detail", UUID(SETTLEMENT_ID), "merchant-own", True),
    ]


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
    assert client.post(f"/v1/admin/merchant/settlements/{SETTLEMENT_ID}/begin-revision").status_code == 200
    assert repo.calls[-1][0:2] == ("begin_revision", "merchant-own")
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
    # Provider configuration is checked before claiming, so no row can be left issuing.
    assert [call[0] for call in repo.calls] == ["merchant_detail"]


def test_popbill_issue_success_rejection_and_ambiguous_are_finalized_safely(client_factory):
    client, repo = client_factory("merchant_admin")
    provider = FakePopbill()
    app.dependency_overrides[get_popbill_service] = lambda: provider
    response = client.post(f"/v1/admin/merchant/settlements/{SETTLEMENT_ID}/tax-invoice/issue")
    assert response.status_code == 200
    assert [call[0] for call in repo.calls] == ["merchant_detail", "claim", "finalize"]
    assert repo.calls[-1][1] == "success"

    repo.calls.clear()
    provider = FakePopbill(PopbillError("POPBILL_ISSUE_REJECTED", "raw provider PII", provider_code=-1))
    app.dependency_overrides[get_popbill_service] = lambda: provider
    response = client.post(f"/v1/admin/merchant/settlements/{SETTLEMENT_ID}/tax-invoice/issue")
    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "POPBILL_ISSUE_REJECTED", "message": "세금계산서 발행이 거절됐어요"}
    assert repo.calls[-1][1:] == ("rejected", "22222222-2222-2222-2222-222222222222", "POPBILL_ISSUE_REJECTED", "Popbill rejected the request")

    repo.calls.clear()
    provider = FakePopbill(PopbillError("POPBILL_RECONCILIATION_REQUIRED", "ambiguous"))
    app.dependency_overrides[get_popbill_service] = lambda: provider
    response = client.post(f"/v1/admin/merchant/settlements/{SETTLEMENT_ID}/tax-invoice/issue")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "POPBILL_RECONCILIATION_REQUIRED"
    assert repo.calls[-1][1] == "reconciliation_required"


def test_url_aliases_and_status_refresh_use_injected_provider(client_factory):
    client, repo = client_factory("merchant_admin")
    provider = FakePopbill()
    app.dependency_overrides[get_popbill_service] = lambda: provider
    for suffix in ("view", "view-url", "pdf", "pdf-url"):
        response = client.get(f"/v1/admin/merchant/settlements/{SETTLEMENT_ID}/tax-invoice/{suffix}")
        assert response.status_code == 200
        assert response.json()["data"]["expires_in"] == 30
        assert response.json()["data"]["url"].startswith("https://provider.example/")
    response = client.post(f"/v1/admin/merchant/settlements/{SETTLEMENT_ID}/tax-invoice/refresh-status")
    assert response.status_code == 200
    assert repo.calls[-1] == ("apply", 304, True)


def test_browser_payloads_recursively_redact_provider_and_attempt_internals(client_factory):
    client, repo = client_factory("merchant_admin")
    sensitive = {
        "invoicer_mgt_key": "SECRET-KEY", "popbill_status_code": 304,
        "nts_status_code": "SUC001", "issue_attempt_token": "token",
        "issue_attempt_started_at": "raw", "issue_lease_expires_at": "raw",
        "reconciliation_required_at": "raw", "provider_response": {"pii": "secret"},
        "popbill_status_message": "raw provider PII", "failure_message": "raw provider PII",
    }
    repo.detail = {"id": SETTLEMENT_ID, "tax_invoice_status": "issued",
                   "tax_invoices": [{"document_type": "original", **sensitive}],
                   "events": [{"payload": {**sensitive}}]}
    repo.claim = {"action": "already_issued", "attempt_token": "token",
                  "tax_invoice": {"document_type": "original", **sensitive}}
    provider = FakePopbill()
    app.dependency_overrides[get_popbill_service] = lambda: provider

    responses = [
        client.get(f"/v1/admin/merchant/settlements/{SETTLEMENT_ID}"),
        client.post(f"/v1/admin/merchant/settlements/{SETTLEMENT_ID}/tax-invoice/issue"),
    ]
    for response in responses:
        assert response.status_code == 200
        body = response.text
        for secret in ("SECRET-KEY", "raw provider PII", "provider_response", "issue_attempt_token"):
            assert secret not in body
