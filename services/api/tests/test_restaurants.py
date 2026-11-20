"""Buyer restaurant list (the app's restaurant picker)."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.repositories.supabase_http import SupabaseHttpError
from app.routers.restaurants import router

USER = "fixture-user"
AUTH = {"Authorization": "Bearer fixture"}
PRODUCTS = [
    {"id": "p1", "merchant_id": "m1", "name": "1장", "voucher_count": 1, "bonus_count": 0, "sale_price": 8000, "status": "active", "is_event": False},
    {"id": "p2", "merchant_id": "m1", "name": "11장", "voucher_count": 10, "bonus_count": 1, "sale_price": 72000, "status": "active", "is_event": False},
    {"id": "p3", "merchant_id": "m1", "name": "품절", "voucher_count": 1, "bonus_count": 0, "sale_price": 100, "status": "sold_out", "is_event": False},
]


@pytest.fixture
def harness():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    with patch("app.routers.restaurants.JoinRepository") as repo_class, patch(
        "app.routers.restaurants.get_settings", return_value=SimpleNamespace(pilot_merchant_id=None),
    ):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id=USER, email=None)
        repo.get_profile.return_value = SimpleNamespace(id=USER, status="active", role="customer")
        tables = {
            "merchants": [{"id": "m1", "name": "가산 한식뷔페", "address": "가산디지털1로 145", "category": "한식", "status": "active"}],
            "vouchers": [{"merchant_id": "m1"}, {"merchant_id": "m1"}, {"merchant_id": "other"}],
            "voucher_products": PRODUCTS,
        }
        repo.client.rest_get.side_effect = lambda table, params: tables[table]
        yield TestClient(app), repo, tables


def test_lists_the_exposed_restaurant_with_own_balance_and_lowest_price(harness):
    client, repo, _ = harness
    response = client.get("/v1/restaurants", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["data"] == {
        "items": [{"id": "m1", "name": "가산 한식뷔페", "address": "가산디지털1로 145", "category": "한식",
                   "voucher_balance": 2, "voucher_price": 7200}],
        "default_merchant_id": "m1",
    }
    voucher_query = next(c.args[1] for c in repo.client.rest_get.call_args_list if c.args[0] == "vouchers")
    assert (voucher_query["user_id"], voucher_query["status"]) == (f"eq.{USER}", "eq.unused")


def test_no_products_on_sale_means_no_price_and_employees_are_admitted(harness):
    client, repo, tables = harness
    tables["voucher_products"] = [PRODUCTS[2]]
    tables["vouchers"] = []
    repo.get_profile.return_value = SimpleNamespace(id=USER, status="active", role="employee")
    item = client.get("/v1/restaurants", headers=AUTH).json()["data"]["items"][0]
    assert (item["voucher_balance"], item["voucher_price"]) == (0, None)


def test_no_restaurant_yet_is_an_empty_list(harness):
    client, _, tables = harness
    tables["merchants"] = []
    assert client.get("/v1/restaurants", headers=AUTH).json()["data"] == {"items": [], "default_merchant_id": None}


def test_admins_are_refused_and_database_errors_are_mapped(harness):
    client, repo, _ = harness
    repo.get_profile.return_value = SimpleNamespace(id=USER, status="active", role="merchant_admin")
    assert client.get("/v1/restaurants", headers=AUTH).status_code == 403
    repo.get_profile.return_value = SimpleNamespace(id=USER, status="suspended", role="customer")
    assert client.get("/v1/restaurants", headers=AUTH).status_code == 403
    repo.get_profile.return_value = SimpleNamespace(id=USER, status="active", role="customer")
    repo.client.rest_get.side_effect = SupabaseHttpError(500, "boom")
    assert client.get("/v1/restaurants", headers=AUTH).status_code == 502
