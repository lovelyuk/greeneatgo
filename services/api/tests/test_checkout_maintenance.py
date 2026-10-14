"""Offline cutover tests: actual inventory, ingress rejection and transparent bypass."""
import ast
import asyncio
import importlib
from pathlib import Path
from unittest.mock import patch

import pytest
import re
from fastapi.testclient import TestClient

from app import checkout_maintenance as maintenance
from app.config import Settings

# Code review inventory: direct legacy orders share checkout; no direct creation
# route exists in this revision. /pay and /transactions/scan are ledger/consume.
PAYABLE_ROUTES = {
    ("POST", "/v1/vouchers/purchase", "purchase"),
    ("POST", "/v1/vouchers/purchase-subsidized", "purchase_subsidized"),
    ("GET", "/v1/payments/checkout/{checkout_token}", "checkout"),
}
BLOCKED_PATHS = [
    "/v1/vouchers/purchase", "/v1/vouchers/purchase-subsidized",
    "/v1/payments/checkout/offline-fixture",
]


@pytest.fixture(scope="module")
def real_app():
    # Never load .env, call a provider, construct a repository, or submit orders.
    settings = Settings("https://offline.invalid", "fixture-anon", "fixture-service")
    with patch("app.config.get_settings", return_value=settings):
        app = importlib.import_module("app.main").app
    return app


async def probe(path, method="GET", **extra):
    calls, messages = [], []

    async def downstream(scope, receive, send):
        calls.append(scope)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        raise AssertionError("maintenance must not read request bodies")

    async def send(message):
        messages.append(message)

    scope = {"type": "http", "method": method, "path": path,
             "raw_path": path.encode(), "query_string": b"", "headers": [], **extra}
    await maintenance.CheckoutMaintenanceMiddleware(downstream)(scope, receive, send)
    return scope, calls, messages


def route_inventory(app):
    # OpenAPI includes effective paths even with FastAPI's lazy included routers.
    return [(method.upper(), path, operation["operationId"])
            for path, methods in app.openapi()["paths"].items()
            for method, operation in methods.items()
            if method in {"get", "post", "put", "patch", "delete", "head", "options"}]


def test_actual_payable_route_inventory(real_app):
    inventory = route_inventory(real_app)
    for method, path, endpoint in PAYABLE_ROUTES:
        assert any(m == method and p == path and op.startswith(endpoint + "_")
                   for m, p, op in inventory)
    # Audit every router for order inserts, not merely hand-picked route names.
    creators = set()
    for source in (Path(__file__).parents[1] / "app/routers").glob("*.py"):
        tree = ast.parse(source.read_text())
        for function in (n for n in tree.body if isinstance(n, ast.FunctionDef)):
            if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "rest_post" and n.args
                   and isinstance(n.args[0], ast.Constant)
                   and n.args[0].value == "payment_orders" for n in ast.walk(function)):
                creators.add(function.name)
    assert creators == {"purchase", "purchase_subsidized"}
    actual = {(m, p, next(endpoint for endpoint in sorted(creators | {"checkout"},
                                                         key=len, reverse=True)
                          if op.startswith(endpoint + "_")))
              for m, p, op in inventory
              if any(op.startswith(endpoint + "_") for endpoint in creators | {"checkout"})}
    assert actual == PAYABLE_ROUTES


@pytest.mark.parametrize("path", BLOCKED_PATHS)
@pytest.mark.parametrize("suffix", ["", "/"])
@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
def test_payable_paths_fail_closed_without_body_or_downstream(path, suffix, method):
    _, calls, messages = asyncio.run(probe(path + suffix, method))
    assert not calls
    assert messages[0]["status"] == 503
    headers = dict(messages[0]["headers"])
    assert headers[b"retry-after"] == b"60"
    assert headers[b"cache-control"] == b"no-store"
    assert b"offline-fixture" not in messages[-1]["body"]
    if method == "HEAD":
        assert messages[-1]["body"] == b""
    else:
        assert b"CHECKOUT_MAINTENANCE" in messages[-1]["body"]


@pytest.mark.parametrize("path", BLOCKED_PATHS)
def test_options_transparent(path):
    scope, calls, messages = asyncio.run(probe(path, "OPTIONS"))
    assert calls == [scope]
    assert messages[0]["status"] == 204


def test_every_other_actual_route_passes_through(real_app):
    payable = {(method, path) for method, path, _ in PAYABLE_ROUTES}
    inventory = route_inventory(real_app)
    assert len(inventory) > 100  # Never let lazy routing turn coverage into a no-op.
    for method, template, _ in inventory:
        if (method, template) in payable:
            continue
        path = re.sub(r"\{[^}]+\}", "offline-fixture", template)
        scope, calls, messages = asyncio.run(probe(path, method))
        assert calls == [scope], (method, path)
        assert messages[0]["status"] == 204


@pytest.mark.parametrize("path", [
    "/v1/payments/checkout", "/v1/payments/checkout/", "/v1/payments/checkout/token/extra",
    "/v1/payments/checkout-future/token", "/v1/vouchers/purchase-future",
    "/v1/vouchers/purchase-subsidized-future", "/v1/vouchers/purchase/extra",
    "/future/checkout/token", "/v1/vouchers/purchase//", "/V1/vouchers/purchase",
    "/v1/payments/notification", "/v1/payments/confirm", "/v1/payments/recovery",
    "/v1/health", "/v1/me", "/p", "/f", "/c",
])
def test_no_prefix_or_arbitrary_future_path_block(path):
    scope, calls, _ = asyncio.run(probe(path, "POST"))
    assert calls == [scope]


def test_use_asgi_decoded_path_not_query_or_raw_uri():
    _, calls, messages = asyncio.run(probe(
        "/v1/vouchers/purchase", "POST", raw_path=b"/v1/vouchers/%70urchase",
        query_string=b"next=/v1/payments/notification"))
    assert not calls and messages[0]["status"] == 503
    scope, calls, _ = asyncio.run(probe(
        "/v1/me", raw_path=b"/v1/me", query_string=b"next=/v1/vouchers/purchase"))
    assert calls == [scope]


@pytest.mark.parametrize("token", ["a%20b", "%3F", "%23", "%25", "%E2%98%83", "%0A"])
def test_encoded_single_segment_tokens_blocked_in_real_app(real_app, token):
    with TestClient(real_app) as client:
        response = client.get("/v1/payments/checkout/" + token)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CHECKOUT_MAINTENANCE"


@pytest.mark.parametrize("path", BLOCKED_PATHS)
def test_real_app_wiring_and_outer_cors(real_app, path):
    with patch("app.repositories.join_repository.JoinRepository.__init__",
               side_effect=AssertionError("must not construct repository")):
        with TestClient(real_app) as client:
            headers = {"Origin": "http://localhost:5173"}
            response = client.post(path, headers=headers)
            assert response.status_code == 503
            assert response.headers["retry-after"] == "60"
            assert response.headers["access-control-allow-origin"] == headers["Origin"]
            preflight = client.options(path, headers={**headers,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type"})
            assert preflight.status_code == 200
            assert "retry-after" not in preflight.headers


def test_disabled_constant_is_transparent(monkeypatch):
    monkeypatch.setattr(maintenance, "CHECKOUT_MAINTENANCE_ENABLED", False)
    for path in BLOCKED_PATHS:
        scope, calls, _ = asyncio.run(probe(path, "POST"))
        assert calls == [scope]


@pytest.mark.parametrize("kind", ["lifespan", "websocket"])
def test_non_http_scopes_transparent(kind):
    scope, calls, _ = asyncio.run(probe("/v1/vouchers/purchase", type=kind))
    assert calls == [scope]
