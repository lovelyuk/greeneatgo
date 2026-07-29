from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import bearer_token
from app.routers.settlements import get_popbill_service, get_settlement_repository
import app.routers.settlements as router
from app.services.join_flow import UserProfile
from app.services.popbill_service import PopbillIssueResult
from app.repositories.supabase_http import SupabaseHttpError

# The production app deliberately does not register demo_router after migration
# 0052. Mount it only in this legacy compatibility unit-test app so the dormant
# implementation remains covered without restoring an OpenAPI/HTTP surface.
app = FastAPI()
for compatibility_router in (
    router.company_router,
    router.company_alias_router,
    router.merchant_router,
    router.demo_router,
):
    app.include_router(compatibility_router, prefix="/v1")

SID = "11111111-1111-1111-1111-111111111111"


class DemoRepo:
    def __init__(self, role="merchant_admin"):
        self.profile = UserProfile(
            id="actor", email="merchant@example.com", display_name="merchant", role=role,
            status="active", merchant_id="merchant" if role == "merchant_admin" else None,
            company_id="company" if role == "company_admin" else None,
        )
        self.calls = []
        self.demo_member = True
        self.state = {"seeded": False, "stage": "empty"}

    def actor(self, token, role):
        assert token == "token"
        if self.profile.role != role:
            from app.services.join_flow import JoinErrorCode, JoinFlowError
            raise JoinFlowError(JoinErrorCode.FORBIDDEN, "forbidden")
        return self.profile

    def demo_state(self, actor):
        self.calls.append("state")
        return self.state

    def supplier_popbill_readiness(self, merchant_id, corp_num):
        self.calls.append("supplier")
        return {"supplier_ready": True, "corp_matches": True}

    def __getattr__(self, name):
        if name in {"demo_seed", "demo_create", "demo_confirm", "demo_mark_paid", "demo_reset"}:
            def action(actor, *args):
                self.calls.append(name)
                if name == "demo_reset":
                    self.calls.append(("reset_key", args[0] if args else None))
                if name == "demo_seed":
                    self.calls.append(("selection", str(args[0]), args[1]))
                return {"seeded": True, "stage": name.removeprefix("demo_")}
            return action
        raise AttributeError(name)

    def demo_assert_issue(self, actor):
        self.calls.append("membership")
        return {"settlement_id": SID}

    def merchant_detail(self, settlement_id, merchant_id):
        self.calls.append("detail")
        return None if self.demo_member else {"id": SID, "tax_invoice_status": "issued", "tax_invoices": [], "events": []}

    def merchant_demo_detail(self, settlement_id, merchant_id):
        self.calls.append("demo_detail")
        return {"id": SID, "tax_invoice_status": "issued", "tax_invoices": [], "events": []} if self.demo_member else None

    def company_detail(self, settlement_id, company_id):
        self.calls.append("detail")
        return None if self.demo_member else {"id": SID, "tax_invoice_status": "issued", "tax_invoices": [], "events": []}

    def is_demo_settlement(self, merchant_id, settlement_id):
        return self.demo_member

    def is_generated_settlement(self, merchant_id, settlement_id):
        return False

    def is_company_demo_settlement(self, company_id, settlement_id):
        return self.demo_member

    def has_current_demo(self, merchant_id):
        return self.demo_member

    def original_invoice_management_key(self, actor, settlement_id):
        self.calls.append("key")
        return "GEAAAAAAAAAAAAAAAAAAAAAA"

    def demo_invoice_management_key(self, merchant_id, settlement_id):
        self.calls.append("demo_key")
        return "GEAAAAAAAAAAAAAAAAAAAAAA" if self.demo_member else None

    def claim_invoice_issue(self, actor, settlement_id):
        self.calls.append("claim")
        return {"action": "issue", "attempt_token": "22222222-2222-2222-2222-222222222222",
                "tax_invoice": {"invoicer_mgt_key": "GEAAAAAAAAAAAAAAAAAAAAAA"}}

    def finalize_invoice_issue(self, actor, settlement_id, token, outcome, failure_code=None, failure_message=None):
        self.calls.append("finalize")
        return {"settlement": {"tax_invoice_status": "issued"}, "tax_invoice": {}}


class ReadyProvider:
    def __init__(self):
        self.calls = []

    def certificate_readiness(self):
        self.calls.append("certificate_readiness")
        return SimpleNamespace(certificate_verified=True, certificate_expires_on="2027-01-01")

    def issue(self, invoice, *, allow_delayed_issue=False):
        self.calls.append(("issue", allow_delayed_issue))
        return PopbillIssueResult(invoice["invoicer_mgt_key"], 1, False)

    def get_view_url(self, key):
        self.calls.append(("view", key))
        return SimpleNamespace(url="https://provider.example/demo-view", expires_in=30)

    def get_pdf_url(self, key):
        self.calls.append(("pdf", key))
        return SimpleNamespace(url="https://provider.example/demo-pdf", expires_in=30)


@pytest.fixture
def demo_client(monkeypatch):
    repo = DemoRepo()
    app.dependency_overrides[bearer_token] = lambda: "token"
    app.dependency_overrides[get_settlement_repository] = lambda: repo
    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace(
        popbill_link_id="link", popbill_secret_key="secret", popbill_corp_num="1234567890",
        popbill_user_id="user", popbill_is_test=True, popbill_ip_restrict_on=True,
        popbill_use_static_ip=False, popbill_use_local_time=True,
    ))
    monkeypatch.setattr(router, "PopbillService", lambda config: ReadyProvider())
    with TestClient(app) as client:
        yield client, repo
    app.dependency_overrides.clear()


def test_demo_state_and_actions_are_merchant_scoped(demo_client):
    client, repo = demo_client
    response = client.get("/v1/admin/merchant/settlement-demo")
    assert response.status_code == 200
    assert response.json()["data"]["stage"] == "empty"
    assert response.json()["data"]["readiness"] == {
        "configured": True, "is_test": True, "certificate_verified": True,
        "certificate_expires_on": "2027-01-01", "supplier_ready": True, "corp_matches": True,
    }
    assert client.post("/v1/admin/merchant/settlement-demo/seed", json={
        "company_id": "33333333-3333-3333-3333-333333333333", "period_ym": "2026-06"
    }).status_code == 200
    for action in ("create", "confirm", "mark-paid", "reset"):
        assert client.post(f"/v1/admin/merchant/settlement-demo/{action}").status_code == 200
    assert ("selection", "33333333-3333-3333-3333-333333333333", "2026-06") in repo.calls
    assert "secret" not in response.text and "link" not in response.text
    assert repo.calls[:2] == ["state", "supplier"]


def test_demo_issue_reuses_claim_provider_finalize_only_after_readiness(demo_client):
    client, repo = demo_client
    provider = ReadyProvider()
    app.dependency_overrides[get_popbill_service] = lambda: provider
    response = client.post("/v1/admin/merchant/settlement-demo/issue")
    assert response.status_code == 200
    assert repo.calls == ["membership", "supplier", "demo_detail", "claim", "finalize"]
    assert provider.calls == ["certificate_readiness", ("issue", True)]


def test_demo_issue_refuses_non_test_without_claim(demo_client, monkeypatch):
    client, repo = demo_client
    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace(
        popbill_link_id="link", popbill_secret_key="secret", popbill_corp_num="1234567890",
        popbill_user_id="user", popbill_is_test=False, popbill_ip_restrict_on=True,
        popbill_use_static_ip=False, popbill_use_local_time=True,
    ))
    response = client.post("/v1/admin/merchant/settlement-demo/issue")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SETTLEMENT_DEMO_TEST_MODE_REQUIRED"
    assert "claim" not in repo.calls


def test_generic_issue_returns_not_found_for_demo(demo_client, monkeypatch):
    client, repo = demo_client
    provider = ReadyProvider()
    app.dependency_overrides[get_popbill_service] = lambda: provider
    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace(
        popbill_link_id="link", popbill_secret_key="secret", popbill_corp_num="1234567890",
        popbill_user_id="user", popbill_is_test=False, popbill_ip_restrict_on=True,
        popbill_use_static_ip=False, popbill_use_local_time=True,
    ))

    response = client.post(f"/v1/admin/merchant/settlements/{SID}/tax-invoice/issue")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SETTLEMENT_NOT_FOUND"
    assert provider.calls == []
    assert "claim" not in repo.calls


@pytest.mark.parametrize("role,path,payload", [
    ("company_admin", f"/v1/company/settlements/{SID}/confirm-and-request-tax-invoice",
     {"business_info_accurate": True, "email_accurate": True, "amount_checked": True}),
    ("company_admin", f"/v1/company/settlements/{SID}/dispute",
     {"reason": "wrong amount", "idempotency_key": "demo-dispute"}),
    ("merchant_admin", f"/v1/admin/merchant/settlements/{SID}/send", None),
    ("merchant_admin", f"/v1/admin/merchant/settlements/{SID}/mark-paid",
     {"amount": 1000, "depositor_name": "Demo", "deposited_at": "2026-07-01T00:00:00Z", "idempotency_key": "demo-paid"}),
])
def test_generic_mutations_return_not_found_for_demo(monkeypatch, role, path, payload):
    repo = DemoRepo(role)
    app.dependency_overrides[bearer_token] = lambda: "token"
    app.dependency_overrides[get_settlement_repository] = lambda: repo
    with TestClient(app) as client:
        response = client.post(path, json=payload) if payload is not None else client.post(path)
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SETTLEMENT_NOT_FOUND"
    assert not any(call in repo.calls for call in ("confirm", "dispute", "send", "paid"))


def test_demo_state_exposes_only_normalized_invoice_evidence(demo_client):
    client, repo = demo_client
    repo.state = {
        "seeded": True,
        "stage": "issued",
        "settlement": {
            "id": SID,
            "tax_invoice_status": "nts_accepted",
            "issued_at": "2026-07-28T01:02:03+00:00",
            "nts_status": "accepted",
            "nts_confirm_num": "NTS-CONFIRM-1",
            "can_view_tax_invoice": True,
            "can_download_tax_invoice_pdf": True,
            "invoicer_mgt_key": "SECRET-MANAGEMENT-KEY",
            "popbill_status_code": 304,
            "popbill_status_message": "raw provider message",
            "provider_response": {"secret": "raw"},
        },
    }

    response = client.get("/v1/admin/merchant/settlement-demo")

    assert response.status_code == 200
    evidence = response.json()["data"]["settlement"]
    assert evidence == {
        "id": SID,
        "tax_invoice_status": "nts_accepted",
        "issued_at": "2026-07-28T01:02:03+00:00",
        "nts_status": "accepted",
        "nts_confirm_num": "NTS-CONFIRM-1",
        "can_view_tax_invoice": True,
        "can_download_tax_invoice_pdf": True,
    }
    assert "SECRET" not in response.text and "raw provider" not in response.text


def test_demo_rejects_company_admin_before_any_demo_rpc(monkeypatch):
    repo = DemoRepo("company_admin")
    app.dependency_overrides[bearer_token] = lambda: "token"
    app.dependency_overrides[get_settlement_repository] = lambda: repo
    with TestClient(app) as client:
        response = client.post("/v1/admin/merchant/settlement-demo/seed", json={
            "company_id": "33333333-3333-3333-3333-333333333333", "period_ym": "2026-06"
        })
    app.dependency_overrides.clear()
    assert response.status_code == 403
    assert repo.calls == []


def test_demo_reset_forwards_optional_idempotency_header(demo_client):
    client, repo = demo_client
    response = client.post(
        "/v1/admin/merchant/settlement-demo/reset",
        headers={"Idempotency-Key": "reset-retry-1"},
    )
    assert response.status_code == 200
    assert ("reset_key", "reset-retry-1") in repo.calls


def test_no_unused_period_has_stable_conflict_mapping(demo_client):
    client, repo = demo_client

    def fail(actor, company_id, period_ym):
        raise SupabaseHttpError(400, '{"message":"SETTLEMENT_DEMO_NO_UNUSED_PERIOD"}')

    repo.demo_seed = fail
    response = client.post("/v1/admin/merchant/settlement-demo/seed", json={
        "company_id": "33333333-3333-3333-3333-333333333333", "period_ym": "2026-06"
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SETTLEMENT_DEMO_NO_UNUSED_PERIOD"


@pytest.mark.parametrize("payload", [
    {},
    {"company_id": "not-a-uuid", "period_ym": "2026-06"},
    {"company_id": "33333333-3333-3333-3333-333333333333", "period_ym": "2026-13"},
])
def test_demo_seed_schema_rejects_invalid_selection_before_repository(demo_client, payload):
    client, repo = demo_client
    response = client.post("/v1/admin/merchant/settlement-demo/seed", json=payload)
    assert response.status_code == 422
    assert "demo_seed" not in repo.calls


@pytest.mark.parametrize("path", [
    f"/v1/admin/merchant/settlements/{SID}/tax-invoice/refresh-status",
    f"/v1/admin/merchant/settlements/{SID}/tax-invoice/view-url",
    f"/v1/admin/merchant/settlements/{SID}/tax-invoice/view",
    f"/v1/admin/merchant/settlements/{SID}/tax-invoice/pdf-url",
    f"/v1/admin/merchant/settlements/{SID}/tax-invoice/pdf",
])
def test_generic_merchant_provider_routes_return_not_found_for_demo(demo_client, monkeypatch, path):
    client, _ = demo_client
    calls = []
    app.dependency_overrides[get_popbill_service] = lambda: (lambda: calls.append("constructed"))
    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace(
        popbill_link_id="link", popbill_secret_key="secret", popbill_corp_num="1234567890",
        popbill_user_id="user", popbill_is_test=False, popbill_ip_restrict_on=True,
        popbill_use_static_ip=False, popbill_use_local_time=True,
    ))
    response = client.post(path) if path.endswith("refresh-status") else client.get(path)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SETTLEMENT_NOT_FOUND"
    assert calls == []


@pytest.mark.parametrize("prefix", ["/v1/company/settlements", "/v1/admin/settlements"])
@pytest.mark.parametrize("suffix", ["view-url", "view", "pdf-url", "pdf"])
def test_company_demo_document_routes_and_aliases_never_call_non_test_provider(monkeypatch, prefix, suffix):
    repo = DemoRepo("company_admin")
    calls = []
    app.dependency_overrides[bearer_token] = lambda: "token"
    app.dependency_overrides[get_settlement_repository] = lambda: repo
    app.dependency_overrides[get_popbill_service] = lambda: (lambda: calls.append("constructed"))
    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace(
        popbill_link_id="link", popbill_secret_key="secret", popbill_corp_num="1234567890",
        popbill_user_id="user", popbill_is_test=False, popbill_ip_restrict_on=True,
        popbill_use_static_ip=False, popbill_use_local_time=True,
    ))
    with TestClient(app) as client:
        response = client.get(f"{prefix}/{SID}/tax-invoice/{suffix}")
    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SETTLEMENT_NOT_FOUND"
    assert calls == [] and "key" not in repo.calls


@pytest.mark.parametrize("kind", ["view", "pdf"])
def test_demo_document_routes_use_membership_scoped_key_and_test_provider(demo_client, kind):
    client, repo = demo_client
    provider = ReadyProvider()
    app.dependency_overrides[get_popbill_service] = lambda: provider

    response = client.get(f"/v1/admin/merchant/settlement-demo/{SID}/tax-invoice/{kind}-url")

    assert response.status_code == 200
    assert response.json()["data"]["url"] == f"https://provider.example/demo-{kind}"
    assert repo.calls == ["demo_detail", "demo_key"]
    assert provider.calls == [(kind, "GEAAAAAAAAAAAAAAAAAAAAAA")]


def test_demo_document_route_enforces_test_mode_before_key_or_provider(demo_client, monkeypatch):
    client, repo = demo_client
    calls = []
    app.dependency_overrides[get_popbill_service] = lambda: (lambda: calls.append("constructed"))
    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace(
        popbill_link_id="link", popbill_secret_key="secret", popbill_corp_num="1234567890",
        popbill_user_id="user", popbill_is_test=False, popbill_ip_restrict_on=True,
        popbill_use_static_ip=False, popbill_use_local_time=True,
    ))

    response = client.get(f"/v1/admin/merchant/settlement-demo/{SID}/tax-invoice/view-url")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SETTLEMENT_DEMO_TEST_MODE_REQUIRED"
    assert repo.calls == ["demo_detail"]
    assert calls == []


def test_current_demo_readiness_in_non_test_mode_never_constructs_provider(demo_client, monkeypatch):
    client, _ = demo_client
    calls = []
    monkeypatch.setattr(router, "PopbillService", lambda config: calls.append("constructed"))
    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace(
        popbill_link_id="link", popbill_secret_key="secret", popbill_corp_num="1234567890",
        popbill_user_id="user", popbill_is_test=False, popbill_ip_restrict_on=True,
        popbill_use_static_ip=False, popbill_use_local_time=True,
    ))
    for path in ("/v1/admin/merchant/settlements/popbill-readiness", "/v1/admin/merchant/settlement-demo"):
        response = client.get(path)
        assert response.status_code == 200
        readiness = response.json()["data"].get("readiness", response.json()["data"])
        assert readiness["configured"] is False
    assert calls == []
