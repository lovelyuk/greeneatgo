"""Real HTTP/router seam; only repository and provider I/O are fakes."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.repositories.supabase_http import SupabaseHttpError
from app.routers import payments
from app.services.kiwoom_payment import KiwoomPaymentError

PATH = "/payments/checkout/fixture-checkout-token/sdk"
HEADERS = {"Authorization": "Bearer fixture-owner-token"}


@pytest.fixture
def seam(monkeypatch):
    order = dict(id="fixture-row", order_id="FIXTURE_ORDER_1", user_id="fixture-owner",
                 checkout_token="fixture-checkout-token", amount=1200, status="ready",
                 pay_type="direct", tax_type="taxable", product_name="식권|상품",
                 product_id="fixture-product", requested_payment_method="TOTAL",
                 provider_response={"private": "must-not-leak"})
    settings = SimpleNamespace(kiwoompay_cpid="TEST0001",
        kiwoompay_base_url="https://apitest.kiwoompay.co.kr",
        public_api_base_url="https://merchant.example/v1", kiwoompay_app_url="fixture://")
    events, hashes = [], []
    state = dict(admitted=False, block=None, hash="fixture-opaque-hash", expired=False,
                 exposed=True, auth_error=False, role="customer", profile_status="active")

    class Repository:
        client = None

        def __init__(self):
            self.client = self

        def auth_user_from_token(self, token):
            assert token == "fixture-owner-token"
            if state["auth_error"]:
                raise SupabaseHttpError(401, "fixture auth rejection")
            return SimpleNamespace(id="fixture-owner", email=None)

        def get_profile(self, user_id, email=None):
            return SimpleNamespace(id=user_id, role=state["role"], status=state["profile_status"])

        def rest_get(self, table, params):
            assert table == "payment_orders"
            if "checkout_token" in params:
                assert params["checkout_token"] == "eq.fixture-checkout-token"
                if params.get("user_id") != "eq." + order["user_id"]:
                    return []
                if order["status"] != "ready":
                    return []
            return [dict(order)]

        def rpc(self, name, args):
            events.append(name)
            assert args == {"p_order_id": order["id"]}
            if state["block"] == name or (name == "admit_payment_checkout" and state["admitted"]):
                raise SupabaseHttpError(409, "fixture inactive checkout")
            if name == "admit_payment_checkout":
                state["admitted"] = True
            return None

    def hash_io(base, payload, *, strict_response=False):
        if payload.payment_type == "P":
            assert strict_response is True
        else:
            assert strict_response is False
        events.append("hash")
        hashes.append((base, payload))
        if isinstance(state["hash"], Exception):
            raise state["hash"]
        return state["hash"]

    def expire(repo, user_id):
        events.append("expiry")
        if state["expired"]:
            order["status"] = "canceled"

    monkeypatch.setattr(payments, "JoinRepository", Repository)
    monkeypatch.setattr(payments, "get_settings", lambda: settings)
    monkeypatch.setattr(payments, "request_payment_hash", hash_io)
    monkeypatch.setattr(payments, "_expire_stale_subsidized_orders", expire)
    monkeypatch.setattr(payments, "_load_products", lambda *a: ([dict(status="active")] if state["exposed"] else [], None))
    monkeypatch.setattr(payments, "_is_exposed", lambda product: state["exposed"])
    app = FastAPI()
    app.include_router(payments.router)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, order=order, settings=settings, events=events, hashes=hashes, state=state)


def post(s):
    # Caller-supplied values must not override the stored snapshot.
    return s.client.post(PATH, headers=HEADERS, json={"AMOUNT": "1", "ORDERNO": "ATTACK", "TYPE": "W"})


def error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


@pytest.mark.parametrize("base,mode", [("https://api.kiwoompay.co.kr", "REAL"), ("https://apitest.kiwoompay.co.kr", "DEV")])
@pytest.mark.parametrize("pay_type", ["direct", "voucher", "subsidized"])
def test_contract_and_one_shot(seam, base, mode, pay_type):
    s = seam
    s.settings.kiwoompay_base_url = base
    s.order.update(pay_type=pay_type, voucher_product_id="fixture-voucher", merchant_id="fixture-merchant")
    response = post(s)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    expected = dict(PAYMETHOD="TOTAL", TYPE="P", CPID="TEST0001", ORDERNO="FIXTURE_ORDER_1",
        PRODUCTTYPE="2", AMOUNT="1200", PRODUCTNAME="식권 상품", PRODUCTCODE="fixture-pr",
        USERID="fixture-owner", KIWOOM_ENC="fixture-opaque-hash", RETURNURL="https://merchant.example/p",
        HOMEURL="https://merchant.example/p", FAILURL="https://merchant.example/f",
        CLOSEURL="https://merchant.example/c", APPURL="fixture://", DIRECTRESULTFLAG="Y")
    assert response.json() == {"ok": True, "data": {"sdk_mode": mode, "fields": expected}, "error": None}
    assert s.events[-3:] == ["admit_payment_checkout", "hash", "assert_payment_checkout_active"]
    hash_base, payload = s.hashes[0]
    assert (hash_base, payload.payment_type, payload.pay_method, payload.order_id, payload.amount) == (base, "P", "TOTAL", "FIXTURE_ORDER_1", 1200)
    error(post(s), 409, "ORDER_NOT_READY")
    assert len(s.hashes) == 1


def test_requires_bearer(seam):
    error(seam.client.post(PATH), 401, "UNAUTHENTICATED")
    assert seam.events == []


def test_wrong_owner(seam):
    seam.order["user_id"] = "fixture-other-owner"
    error(post(seam), 404, "ORDER_NOT_FOUND")
    assert seam.events == []


def test_invalid_auth(seam):
    seam.state["auth_error"] = True
    error(post(seam), 401, "UNAUTHENTICATED")
    assert seam.events == []


@pytest.mark.parametrize("role,status", [("merchant", "active"), ("customer", "inactive")])
def test_account_guard(seam, role, status):
    seam.state.update(role=role, profile_status=status)
    error(post(seam), 403, "CUSTOMER_ONLY")
    assert seam.events == []


def test_employee_owner(seam):
    seam.state["role"] = "employee"
    assert post(seam).status_code == 200


@pytest.mark.parametrize("method,code", [("BANK", "SDK_PAYMENT_METHOD_UNSUPPORTED"), ("CARD", "INVALID_PAYMENT_METHOD")])
def test_method_rejected_without_admission(seam, method, code):
    seam.order["requested_payment_method"] = method
    error(post(seam), 409, code)
    assert seam.events == []


@pytest.mark.parametrize("base", ["https://api.kiwoompay.co.kr/", "http://api.kiwoompay.co.kr", "https://api.kiwoompay.co.kr:443", "https://api.kiwoompay.co.kr/pay", "https://api.kiwoompay.co.kr?x=1", "https://api.kiwoompay.co.kr.evil.example", "https://unknown.example", "HTTPS://api.kiwoompay.co.kr"])
def test_unknown_origin_before_admission(seam, base):
    seam.settings.kiwoompay_base_url = base
    error(post(seam), 503, "KIWOOMPAY_SDK_NOT_CONFIGURED")
    assert seam.events == []


@pytest.mark.parametrize("cpid", ["", "SHORT", "TOOLONG01", "TEST|001", "TEST 001"])
def test_cpid_guard(seam, cpid):
    seam.settings.kiwoompay_cpid = cpid
    error(post(seam), 503, "KIWOOMPAY_SDK_NOT_CONFIGURED")
    assert seam.events == []


@pytest.mark.parametrize("key,value", [("order_id", ""), ("order_id", "x" * 51), ("order_id", "bad|order"), ("product_name", ""), ("user_id", ""), ("amount", 0), ("amount", -1), ("amount", True), ("amount", 1.5), ("amount", "1.5"), ("amount", 10000000000)])
def test_required_snapshot_guard(seam, key, value):
    seam.order[key] = value
    # Empty owner is not owned; all other invalid snapshots fail validation.
    error(post(seam), 404 if key == "user_id" else 409, "ORDER_NOT_FOUND" if key == "user_id" else "INVALID_SDK_CHECKOUT")
    assert seam.events == []


def test_tax_guard(seam):
    seam.order["tax_type"] = "unclassified"
    error(post(seam), 409, "TAX_TYPE_UNCLASSIFIED")
    assert seam.events == []


def test_product_guard(seam):
    seam.order.update(pay_type="voucher", voucher_product_id="fixture-voucher", merchant_id="fixture-merchant")
    seam.state["exposed"] = False
    error(post(seam), 409, "VOUCHER_PRODUCT_NOT_EXPOSED")
    assert seam.events == []


def test_expiry_guard(seam):
    seam.order["pay_type"] = "subsidized"
    seam.state["expired"] = True
    error(post(seam), 409, "ORDER_EXPIRED")
    assert seam.events == ["expiry"]


@pytest.mark.parametrize("guard", ["admit_payment_checkout", "assert_payment_checkout_active"])
def test_checkout_guards(seam, guard):
    seam.state["block"] = guard
    error(post(seam), 409, "ORDER_NOT_READY")
    assert seam.events == ([guard] if guard == "admit_payment_checkout" else ["admit_payment_checkout", "hash", guard])


@pytest.mark.parametrize("value", [None, "", " ", {}, [], "x" * 1001, "bad|hash", "bad\nhash"])
def test_malformed_hash_never_returned_or_readmitted(seam, value):
    seam.state["hash"] = value
    error(post(seam), 502, "KIWOOMPAY_INVALID_RESPONSE")
    assert seam.events[:2] == ["admit_payment_checkout", "hash"]
    error(post(seam), 409, "ORDER_NOT_READY")
    assert len(seam.hashes) == 1


def test_hash_failure_is_bounded(seam):
    seam.state["hash"] = KiwoomPaymentError(502, "PROVIDER_RAW", "fixture-private-provider-response")
    response = post(seam)
    error(response, 502, "KIWOOMPAY_HASH_FAILED")
    assert "fixture-private" not in response.text
    error(post(seam), 409, "ORDER_NOT_READY")


@pytest.mark.parametrize("raw_hash", [123, True, {}, [], ["opaque"]])
def test_real_hash_service_rejects_non_string_sdk_response(seam, monkeypatch, raw_hash):
    from app.services import kiwoom_payment
    monkeypatch.setattr(kiwoom_payment, "_request_json", lambda *a, **kw: {"RESULTCODE": "0000", "KIWOOM_ENC": raw_hash})
    monkeypatch.setattr(payments, "request_payment_hash", kiwoom_payment.request_payment_hash)
    response = post(seam)
    assert response.status_code == 502, response.text
    assert "fields" not in response.json()
    error(post(seam), 409, "ORDER_NOT_READY")


@pytest.mark.parametrize("mode", ["DEV", "REAL"])
def test_real_router_to_provider_wire_and_exported_browser_contract(seam, monkeypatch, mode):
    import json
    import os
    from pathlib import Path
    from unittest.mock import MagicMock
    from app.services import kiwoom_payment
    seam.settings.kiwoompay_base_url = "https://api.kiwoompay.co.kr" if mode == "REAL" else "https://apitest.kiwoompay.co.kr"
    seam.order.update(order_id="GE-S-final-L1", user_id="fixture-owner", amount=41000)
    requests = []
    def fake_urlopen(request, timeout):
        requests.append(request)
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = b'{"RESULTCODE":"0000","KIWOOM_ENC":"synthetic-hash"}'
        return response
    monkeypatch.setattr(kiwoom_payment, "urlopen", fake_urlopen)
    monkeypatch.setattr(payments, "request_payment_hash", kiwoom_payment.request_payment_hash)
    result = post(seam)
    assert result.status_code == 200
    assert len(requests) == 1
    request = requests[0]
    assert request.full_url == seam.settings.kiwoompay_base_url + "/pay/hash"
    assert request.method == "POST"
    assert json.loads(request.data) == dict(PAYMETHOD="TOTAL", TYPE="P", CPID="TEST0001", ORDERNO="GE-S-final-L1", AMOUNT="41000")
    assert seam.events == ["admit_payment_checkout", "assert_payment_checkout_active"]
    assert result.json()["data"]["sdk_mode"] == mode
    error(post(seam), 409, "ORDER_NOT_READY")
    assert len(requests) == 1
    if os.environ.get("PC_SDK_ROUTER_RECEIPTS"):
        path = Path(os.environ["PC_SDK_ROUTER_RECEIPTS"]) / ("router-sdk-contract-" + mode + ".json")
        path.write_text(json.dumps(result.json()["data"], ensure_ascii=False, indent=2))


def test_existing_get_stays_webview(seam):
    # The fake owner filter is only applicable to the authenticated new endpoint.
    repo = payments.JoinRepository()
    repo.rest_get = lambda table, params: [dict(seam.order)]
    from unittest.mock import patch
    with patch.object(payments, "JoinRepository", return_value=repo):
        response = seam.client.get("/payments/checkout/fixture-checkout-token")
    assert response.status_code == 200
    assert 'name="TYPE" value="W"' in response.text
    assert seam.hashes[0][1].payment_type == "W"
