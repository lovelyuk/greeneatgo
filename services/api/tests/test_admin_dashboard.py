from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.admin_dashboard_schemas import AdminDashboardSummary
from app.auth import bearer_token
from app.main import app
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.admin_dashboard import get_admin_dashboard_repository
from app.services.join_flow import UserProfile

MERCHANT_ID = "11111111-1111-1111-1111-111111111111"
COMPANY_ID = "22222222-2222-2222-2222-222222222222"
OTHER_ID = "33333333-3333-3333-3333-333333333333"


def payload():
    return {
        "total_amount": 900,
        "total_amount_delta_pct": 12.5,
        "total_count": 2,
        "total_count_delta_pct": None,
        "by_meal_type": [
            {"label": "중식", "amount": 1000, "count": 3, "ratio": 75.0},
            {"label": "석식", "amount": -100, "count": -1, "ratio": 25.0},
        ],
        "top_companies_by_amount": [{"rank": 1, "name": "회사", "amount": 900}],
        "top_companies_by_count": [{"rank": 1, "name": "회사", "count": 2}],
        "unit": "day",
        "series": [{"date": "2026-07-01", "amount": 900, "count": 2}],
    }


class FakeRepository:
    def __init__(self, actor):
        self.profile = actor
        self.calls = []
        self.error = None

    def actor(self, token):
        self.calls.append(("actor", token))
        return self.profile

    def summary(self, actor_id, period_from, period_to, merchant_id, company_id):
        self.calls.append(("summary", actor_id, period_from, period_to, merchant_id, company_id))
        if self.error:
            raise self.error
        return payload()


def actor(role="platform_admin", merchant_id=None, company_id=None, status="active"):
    return UserProfile(id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", email="a@example.com", display_name="A",
                       role=role, status=status, merchant_id=merchant_id, company_id=company_id)


@pytest.fixture
def dashboard_client():
    repo = FakeRepository(actor())
    app.dependency_overrides[bearer_token] = lambda: "token"
    app.dependency_overrides[get_admin_dashboard_repository] = lambda: repo
    with TestClient(app) as client:
        yield client, repo
    app.dependency_overrides.clear()


def test_platform_dashboard_contract_and_rpc_arguments(dashboard_client):
    client, repo = dashboard_client
    response = client.get(f"/v1/admin/dashboard/summary?from=2026-07-01&to=2026-07-01&merchant_id={MERCHANT_ID}&company_id={COMPANY_ID}")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "data": payload(), "error": None}
    assert repo.calls == [
        ("actor", "token"),
        ("summary", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", date(2026, 7, 1), date(2026, 7, 1), MERCHANT_ID, COMPANY_ID),
    ]


def test_dashboard_nested_models_enforce_exact_public_keys():
    data = payload()
    model = AdminDashboardSummary.model_validate(data)
    dumped = model.model_dump(mode="json")
    assert set(dumped["by_meal_type"][0]) == {"label", "amount", "count", "ratio"}
    assert set(dumped["top_companies_by_amount"][0]) == {"rank", "name", "amount"}
    assert set(dumped["top_companies_by_count"][0]) == {"rank", "name", "count"}

    for collection, legacy_keys in (
        ("by_meal_type", {"meal_type": "중식"}),
        ("top_companies_by_amount", {"company_id": COMPANY_ID, "company_name": "회사"}),
        ("top_companies_by_count", {"company_id": COMPANY_ID, "company_name": "회사"}),
    ):
        invalid = payload()
        invalid[collection][0].update(legacy_keys)
        with pytest.raises(ValidationError):
            AdminDashboardSummary.model_validate(invalid)


@pytest.mark.parametrize("ratio", [-0.1, 100.1])
def test_dashboard_rejects_out_of_range_meal_ratios(ratio):
    invalid = payload()
    invalid["by_meal_type"][0]["ratio"] = ratio
    with pytest.raises(ValidationError):
        AdminDashboardSummary.model_validate(invalid)


@pytest.mark.parametrize("unit", [None, "hour", "quarter"])
def test_dashboard_rejects_unknown_series_unit(unit):
    invalid = payload()
    invalid["unit"] = unit
    with pytest.raises(ValidationError):
        AdminDashboardSummary.model_validate(invalid)


def test_invalid_or_reversed_dates_never_reach_repository(dashboard_client):
    client, repo = dashboard_client
    for query in ("from=no&to=2026-07-01", "from=2026-07-02&to=2026-07-01"):
        assert client.get(f"/v1/admin/dashboard/summary?{query}").status_code == 422
    assert repo.calls == []


def test_dashboard_period_is_limited_to_366_inclusive_days(dashboard_client):
    client, repo = dashboard_client
    accepted = client.get("/v1/admin/dashboard/summary?from=2026-01-01&to=2027-01-01")
    assert accepted.status_code == 200
    repo.calls.clear()

    rejected = client.get("/v1/admin/dashboard/summary?from=2026-01-01&to=2027-01-02")
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "INVALID_DATE_RANGE"
    assert repo.calls == []


def test_only_platform_admin_may_request_global_scope(dashboard_client):
    client, repo = dashboard_client
    repo.profile = actor("merchant_admin", merchant_id=MERCHANT_ID)
    response = client.get("/v1/admin/dashboard/summary?from=2026-07-01&to=2026-07-02")
    assert response.status_code == 403
    assert all(call[0] != "summary" for call in repo.calls)


@pytest.mark.parametrize(
    "profile,query",
    [
        (actor("merchant_admin", merchant_id=MERCHANT_ID), f"merchant_id={OTHER_ID}"),
        (actor("company_admin", company_id=COMPANY_ID), f"company_id={OTHER_ID}"),
        (actor("merchant_admin", merchant_id=MERCHANT_ID), f"company_id={COMPANY_ID}"),
        (actor("company_admin", company_id=COMPANY_ID), f"merchant_id={MERCHANT_ID}"),
    ],
)
def test_missing_or_inaccessible_primary_scope_is_concealed_as_not_found(dashboard_client, profile, query):
    client, repo = dashboard_client
    repo.profile = profile
    response = client.get(f"/v1/admin/dashboard/summary?from=2026-07-01&to=2026-07-02&{query}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SCOPE_NOT_FOUND"
    assert all(call[0] != "summary" for call in repo.calls)


def test_owned_scope_and_optional_intersection_are_forwarded(dashboard_client):
    client, repo = dashboard_client
    repo.profile = actor("merchant_admin", merchant_id=MERCHANT_ID)
    response = client.get(f"/v1/admin/dashboard/summary?from=2026-07-01&to=2026-07-02&merchant_id={MERCHANT_ID}&company_id={COMPANY_ID}")
    assert response.status_code == 200
    assert repo.calls[-1][-2:] == (MERCHANT_ID, COMPANY_ID)


def test_database_scope_failure_is_404_and_missing_migration_is_503(dashboard_client):
    client, repo = dashboard_client
    base = "/v1/admin/dashboard/summary?from=2026-07-01&to=2026-07-02"
    repo.error = SupabaseHttpError(400, '{"message":"ADMIN_DASHBOARD_SCOPE_NOT_FOUND"}')
    assert client.get(base).status_code == 404
    repo.error = SupabaseHttpError(404, '{"code":"PGRST202","message":"admin_dashboard_summary schema cache"}')
    assert client.get(base).status_code == 503
