from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.repositories.supabase_http import SupabaseHttpError
from app.routers.payments import _notification_ip, router, short_redirect_router


def _request(peer: str | None, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    scope = {
        "type": "http",
        "headers": headers,
        "client": (peer, 12345) if peer else None,
    }
    return Request(scope)


def test_notification_ip_trusts_socket_peer_over_forwarded_internal_hop():
    # Render delivers the real caller as the socket peer, then trails its own
    # internal proxy IP at the right of X-Forwarded-For. The caller must win.
    request = _request("123.140.121.205", xff="123.140.121.205, 10.25.32.132")
    assert _notification_ip(request) == "123.140.121.205"


def test_notification_ip_ignores_forwarded_for_untrusted_peer():
    # A direct attacker cannot smuggle an allowed IP through X-Forwarded-For.
    request = _request("203.0.113.77", xff="123.140.121.205")
    assert _notification_ip(request) == "203.0.113.77"


def test_notification_ip_honours_forwarded_for_local_sentinel_peer():
    # Loopback/test peers legitimately front real callers (and inject the source
    # IP in tests), so the forwarded chain is honoured there.
    assert _notification_ip(_request("testclient", xff="203.0.113.77")) == "203.0.113.77"
    assert _notification_ip(_request("127.0.0.1", xff="123.140.121.205")) == "123.140.121.205"


LOGGER_NAME = "app.routers.payments"
SENSITIVE_ORDER_ID = "GE-private-order-491"
SENSITIVE_TRANSACTION_ID = "private-daou-transaction-492"
SENSITIVE_CARD = "5107370000008900"
SENSITIVE_SOURCE_IP = "203.0.113.77"


def _notification_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _notification_params(**overrides: str) -> dict[str, str]:
    params = {
        "CPID": "CPID",
        "PAYMETHOD": "CARD",
        "ORDERNO": SENSITIVE_ORDER_ID,
        "DAOUTRX": SENSITIVE_TRANSACTION_ID,
        "AMOUNT": "8000",
        "RESULTCODE": "0000",
        "CARDNO": SENSITIVE_CARD,
    }
    params.update(overrides)
    return params


def _order(**overrides: object) -> dict[str, object]:
    order = {
        "id": "private-database-id",
        "order_id": SENSITIVE_ORDER_ID,
        "amount": 8000,
        "status": "ready",
        "pay_type": "direct",
        "requested_payment_method": "TOTAL",
        "voucher_product_id": None,
        "voucher_count": 0,
        "paid_voucher_count": 0,
        "bonus_voucher_count": 0,
        "checkout_started_at": None,
    }
    order.update(overrides)
    return order


def test_post_short_success_is_neutral_and_cannot_complete_payment():
    app = FastAPI()
    app.include_router(short_redirect_router)
    client = TestClient(app)

    with patch("app.routers.payments.JoinRepository") as repo_class, patch(
        "app.routers.payments.present_payment_completion"
    ) as present_completion, patch("app.routers.payments._decode_form") as decode_form:
        get_response = client.get("/p")
        post_response = client.post(
            "/p",
            content=(
                f"CPID=CPID&ORDERNO={SENSITIVE_ORDER_ID}&"
                f"DAOUTRX={SENSITIVE_TRANSACTION_ID}&CARDNO={SENSITIVE_CARD}"
            ),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

    assert post_response.status_code == 200
    assert post_response.text == get_response.text
    assert "결제 승인 확인 중" in post_response.text
    repo_class.assert_not_called()
    present_completion.assert_not_called()
    decode_form.assert_not_called()


@pytest.mark.parametrize(
    ("reason", "expected_status", "params_update", "order_update", "rest_get_result", "rest_get_error", "rpc_error", "headers"),
    [
        ("invalid_source_ip", 400, {}, {}, None, None, None, {"X-Forwarded-For": "malformed-private-ip"}),
        ("source_ip_not_allowed", 403, {}, {}, None, None, None, {"X-Forwarded-For": SENSITIVE_SOURCE_IP}),
        ("cpid_mismatch", 400, {"CPID": "private-wrong-cpid"}, {}, None, None, None, {}),
        ("explicit_failure_or_cancel", 200, {"RESULTCODE": "private-failure-code"}, {}, None, None, None, {}),
        ("missing_keys", 400, {"ORDERNO": ""}, {}, None, None, None, {}),
        ("order_not_found", 404, {}, {}, [], None, None, {}),
        ("amount_mismatch", 409, {}, {"amount": 9000}, None, None, None, {}),
        ("method_mismatch", 409, {}, {"requested_payment_method": "BANK"}, None, None, None, {}),
        ("missing_method", 400, {"PAYMETHOD": ""}, {}, None, None, None, {}),
        ("invalid_status", 409, {}, {"status": "canceled"}, None, None, None, {}),
        (
            "checkout_boundary",
            409,
            {},
            {
                "pay_type": "subsidized",
                "voucher_product_id": "private-product-id",
                "voucher_count": 2,
                "paid_voucher_count": 2,
            },
            None,
            None,
            None,
            {},
        ),
        ("supabase", 500, {}, {}, None, SupabaseHttpError(503, "private-supabase-body"), None, {}),
        ("tax", 409, {}, {}, None, None, SupabaseHttpError(409, "TAX_TYPE_UNCLASSIFIED private-tax-body"), {}),
        ("value", 500, {"AMOUNT": "private-not-an-integer"}, {}, None, None, None, {}),
        ("unexpected", 500, {}, {}, None, RuntimeError("private-runtime-error"), None, {}),
    ],
)
def test_notification_reason_logs_are_structured_and_privacy_safe(
    caplog,
    reason,
    expected_status,
    params_update,
    order_update,
    rest_get_result,
    rest_get_error,
    rpc_error,
    headers,
):
    settings = SimpleNamespace(
        kiwoompay_cpid="CPID",
        kiwoompay_notification_ips=("123.140.121.205",),
    )
    caplog.set_level("WARNING", logger=LOGGER_NAME)

    with patch("app.routers.payments.JoinRepository") as repo_class, patch(
        "app.routers.payments.get_settings", return_value=settings
    ):
        repo = repo_class.return_value
        if rest_get_error is not None:
            repo.client.rest_get.side_effect = rest_get_error
        else:
            repo.client.rest_get.return_value = (
                rest_get_result if rest_get_result is not None else [_order(**order_update)]
            )
        if rpc_error is not None:
            repo.client.rpc.side_effect = rpc_error

        response = TestClient(_notification_app()).get(
            "/payments/notification",
            params=_notification_params(**params_update),
            headers=headers,
        )

    assert response.status_code == expected_status
    expected_ack = "SUCCESS" if reason == "explicit_failure_or_cancel" else "FAIL"
    assert f"<RESULT>{expected_ack}</RESULT>" in response.text

    records = [record for record in caplog.records if record.name == LOGGER_NAME]
    assert len(records) == 1
    assert records[0].reason == reason
    logged = caplog.text
    for sensitive_value in (
        SENSITIVE_ORDER_ID,
        SENSITIVE_TRANSACTION_ID,
        SENSITIVE_CARD,
        SENSITIVE_SOURCE_IP,
        "malformed-private-ip",
        "private-wrong-cpid",
        "private-failure-code",
        "private-product-id",
        "private-supabase-body",
        "private-tax-body",
        "private-not-an-integer",
        "private-runtime-error",
    ):
        assert sensitive_value not in logged
