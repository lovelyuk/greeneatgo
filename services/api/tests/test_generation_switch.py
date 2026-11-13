from fastapi.testclient import TestClient

from app.main import app


def test_generation_switch_turns_whole_router_off(monkeypatch):
    monkeypatch.setenv("TRANSACTION_GENERATION_ENABLED", "false")
    client = TestClient(app)
    for method, path in (("get", ""), ("post", "/seed"), ("post", "/confirm"), ("post", "/reset")):
        response = getattr(client, method)(f"/v1/admin/merchant/transaction-generation{path}",
                                           headers={"Authorization": "Bearer x"})
        assert response.status_code == 404, path
        assert response.json()["detail"]["code"] == "TRANSACTION_GENERATION_DISABLED"


def test_generation_switch_defaults_on(monkeypatch):
    monkeypatch.delenv("TRANSACTION_GENERATION_ENABLED", raising=False)
    response = TestClient(app).get("/v1/admin/merchant/transaction-generation")
    assert response.status_code != 404


def test_unilateral_company_link_and_global_company_search_are_gone():
    paths = set(app.openapi()["paths"])
    assert "/v1/admin/merchant/companies/link" not in paths
    assert "/v1/admin/merchant/companies/search" not in paths
    assert "/v1/admin/merchant/companies/create-and-link" in paths
