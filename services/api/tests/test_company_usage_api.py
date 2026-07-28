from fastapi.testclient import TestClient
import pytest

from app.auth import bearer_token
from app.main import app
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.company_usage import get_company_usage_repository
from app.services.join_flow import JoinErrorCode, JoinFlowError, UserProfile

COMPANY_ID = "11111111-1111-1111-1111-111111111111"
USER_ID = "22222222-2222-2222-2222-222222222222"


def usage_payload():
    return {
        "period": {
            "ym": "2026-07",
            "timezone": "Asia/Seoul",
            "start_at": "2026-06-30T15:00:00Z",
            "end_at": "2026-07-31T15:00:00Z",
        },
        "summary": {
            "gross_spend_amount": 1000,
            "company_charge_amount": 700,
            "employee_paid_amount": 300,
            "transaction_count": 1,
            "spend_count": 1,
            "reversal_count": 0,
            "unique_users": 1,
            "used_employee_count": 1,
            "total_employee_count": 2,
            "active_employee_count": 1,
            "outstanding_settlement_amount": 500,
            "confirmed_payment_amount": 500,
        },
        "daily": [{
            "date": "2026-07-01",
            "gross_spend_amount": 1000,
            "company_charge_amount": 700,
            "employee_paid_amount": 300,
            "transaction_count": 1,
            "spend_count": 1,
            "reversal_count": 0,
            "unique_users": 1,
        }],
        "employees": [{
            "user_id": USER_ID,
            "display_name": "Employee",
            "employee_no": "E-1",
            "department": "Sales",
            "status": "active",
            "gross_spend_amount": 1000,
            "company_charge_amount": 700,
            "employee_paid_amount": 300,
            "transaction_count": 1,
            "spend_count": 1,
            "reversal_count": 0,
            "usage_days": 1,
        }],
        "settlements": {
            "count": 1,
            "total_amount": 1000,
            "confirmed_payment_amount": 500,
            "outstanding_amount": 500,
        },
    }


class FakeUsageRepository:
    def __init__(self):
        self.calls = []
        self.rpc_error = None
        self.actor_error = None

    def actor(self, token):
        self.calls.append(("actor", token))
        if self.actor_error:
            raise self.actor_error
        return UserProfile(
            id="admin",
            email="admin@example.com",
            display_name="Admin",
            role="company_admin",
            status="active",
            company_id=COMPANY_ID,
        )

    def monthly_usage(self, actor_id, company_id, ym):
        self.calls.append(("monthly_usage", actor_id, company_id, ym))
        if self.rpc_error:
            raise self.rpc_error
        return usage_payload()


@pytest.fixture
def usage_client():
    repo = FakeUsageRepository()
    app.dependency_overrides[bearer_token] = lambda: "access-token"
    app.dependency_overrides[get_company_usage_repository] = lambda: repo
    with TestClient(app) as client:
        yield client, repo
    app.dependency_overrides.clear()


def test_company_usage_contract_and_token_owned_tenant(usage_client):
    client, repo = usage_client
    response = client.get("/v1/admin/company-usage?ym=2026-07")
    assert response.status_code == 200
    assert repo.calls == [
        ("actor", "access-token"),
        ("monthly_usage", "admin", COMPANY_ID, "2026-07"),
    ]
    body = response.json()
    assert body == {"ok": True, "data": usage_payload(), "error": None}
    assert body["data"]["period"]["timezone"] == "Asia/Seoul"


def test_company_usage_rejects_missing_or_invalid_month_before_database(usage_client):
    client, repo = usage_client
    for query in ("", "?ym=2026-00", "?ym=2026-13", "?ym=2026-7", "?ym=not-a-month"):
        assert client.get(f"/v1/admin/company-usage{query}").status_code == 422
    assert repo.calls == []


def test_company_usage_requires_active_company_admin(usage_client):
    client, repo = usage_client
    repo.actor_error = JoinFlowError(JoinErrorCode.FORBIDDEN, "forbidden")
    response = client.get("/v1/admin/company-usage?ym=2026-07")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FORBIDDEN"
    assert all(call[0] != "monthly_usage" for call in repo.calls)


def test_company_usage_reports_missing_migration_without_mock_fallback(usage_client):
    client, repo = usage_client
    repo.rpc_error = SupabaseHttpError(
        404,
        '{"code":"PGRST202","message":"Could not find public.company_monthly_usage in the schema cache"}',
    )
    response = client.get("/v1/admin/company-usage?ym=2026-07")
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "COMPANY_USAGE_MIGRATION_REQUIRED",
        "message": "회사 이용 내역 데이터베이스 마이그레이션이 필요해요",
    }
    assert "data" not in response.json()


def test_company_usage_does_not_mislabel_generic_database_404_body(usage_client):
    client, repo = usage_client
    repo.rpc_error = SupabaseHttpError(404, '{"message":"database endpoint not found"}')
    response = client.get("/v1/admin/company-usage?ym=2026-07")
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "SUPABASE_ERROR"


def test_company_usage_maps_database_actor_mismatch_to_forbidden(usage_client):
    client, repo = usage_client
    repo.rpc_error = SupabaseHttpError(400, '{"message":"COMPANY_USAGE_ACTOR_FORBIDDEN"}')
    response = client.get("/v1/admin/company-usage?ym=2026-07")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FORBIDDEN"
