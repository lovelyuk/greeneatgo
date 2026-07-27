from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.repositories.supabase_http import SupabaseHttpError
from app.routers.pay import _map_rpc_error as map_ledger_error
from app.routers.payments import checkout, confirm, router
from app.routers.transactions import _map_rpc_error as map_transaction_error
from app.schemas import PaymentConfirmRequest


def _checkout_settings():
    return SimpleNamespace(
        public_api_base_url="https://api.example.com/v1",
        kiwoompay_cpid="CPID",
        kiwoompay_base_url="https://apitest.kiwoompay.co.kr",
        kiwoompay_app_url="greeneatgo://payment",
    )


def _direct_order(tax_type: str):
    return {
        "id": "direct-order",
        "user_id": "user-1",
        "amount": 8000,
        "order_id": "GE-DIRECT-1",
        "product_name": "점심",
        "merchant_name": "돈토",
        "pay_type": "direct",
        "status": "ready",
        "merchant_id": "merchant-1",
        "product_id": "product-1",
        "voucher_product_id": None,
        "requested_payment_method": "TOTAL",
        "provider_payment_key": None,
        "tax_type": tax_type,
    }


def test_unclassified_legacy_direct_checkout_never_calls_provider():
    with patch("app.routers.payments.JoinRepository") as repo_class, patch(
        "app.routers.payments.get_settings", return_value=_checkout_settings()
    ), patch("app.routers.payments.request_payment_hash") as request_hash:
        repo_class.return_value.client.rest_get.return_value = [_direct_order("unclassified")]
        with pytest.raises(HTTPException) as caught:
            checkout("legacy-ready-token")

    assert caught.value.status_code == 409
    assert caught.value.detail == {
        "code": "TAX_TYPE_UNCLASSIFIED",
        "message": "과세 유형이 설정되지 않은 주문은 결제할 수 없어요",
    }
    request_hash.assert_not_called()


def test_classified_legacy_direct_checkout_calls_provider():
    with patch("app.routers.payments.JoinRepository") as repo_class, patch(
        "app.routers.payments.get_settings", return_value=_checkout_settings()
    ), patch("app.routers.payments.request_payment_hash", return_value="secure-hash") as request_hash:
        repo_class.return_value.client.rest_get.return_value = [_direct_order("taxable")]
        response = checkout("legacy-ready-token")

    assert response.status_code == 200
    request_hash.assert_called_once()


def _notification_response(repo, *, rpc_error=None):
    app = FastAPI()
    app.include_router(router)
    settings = SimpleNamespace(kiwoompay_cpid="CPID", kiwoompay_notification_ips=())
    with patch("app.routers.payments.JoinRepository") as repo_class, patch(
        "app.routers.payments.get_settings", return_value=settings
    ):
        repo_class.return_value = repo
        repo.client.rest_get.return_value = [_direct_order("unclassified")]
        if rpc_error is not None:
            repo.client.rpc.side_effect = rpc_error
        return TestClient(app).get("/payments/notification", params={
            "CPID": "CPID",
            "PAYMETHOD": "CARD",
            "ORDERNO": "GE-DIRECT-1",
            "DAOUTRX": "provider-trx",
            "AMOUNT": "8000",
        })


def test_legacy_direct_notification_delegates_atomically_to_database():
    from unittest.mock import MagicMock

    repo = MagicMock()
    repo.client.rpc.return_value = {"status": "done", "duplicate": False, "tax_type": "taxable"}
    response = _notification_response(repo)

    assert response.status_code == 200
    assert "<RESULT>SUCCESS</RESULT>" in response.text
    repo.client.rpc.assert_called_once_with("complete_kiwoom_payment_notification", {
        "p_order_id": "direct-order", "p_provider_order_id": "GE-DIRECT-1",
        "p_cpid": "CPID", "p_amount": 8000, "p_payment_method": "CARD",
        "p_provider_transaction_id": "provider-trx",
        "p_payload": {
            "CPID": "CPID", "PAYMETHOD": "CARD", "ORDERNO": "GE-DIRECT-1",
            "DAOUTRX": "provider-trx", "AMOUNT": "8000", "source_ip": "testclient",
        },
        "p_source_ip": "testclient",
    })
    assert all(call.args[0] not in {"fulfill_voucher_order", "fulfill_subsidized_order", "enqueue_legacy_payment_notification"}
               for call in repo.client.rpc.call_args_list)
    repo.client.rest_patch.assert_not_called()


def test_legacy_direct_notification_maps_database_unclassified_error_to_conflict():
    from unittest.mock import MagicMock

    repo = MagicMock()
    response = _notification_response(
        repo,
        rpc_error=SupabaseHttpError(400, '{"code":"P0001","message":"TAX_TYPE_UNCLASSIFIED"}'),
    )

    assert response.status_code == 409
    assert "<RESULT>FAIL</RESULT>" in response.text
    repo.client.rest_patch.assert_not_called()
    repo.client.rpc.assert_called_once()
    assert all(call.args[0] not in {"fulfill_voucher_order", "fulfill_subsidized_order", "enqueue_legacy_payment_notification"}
               for call in repo.client.rpc.call_args_list)


def test_unclassified_direct_result_is_not_reported_as_completed():
    order = {**_direct_order("unclassified"), "status": "done", "provider_payment_key": "provider-trx"}
    with patch("app.routers.payments.JoinRepository") as repo_class:
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="auth-1", email="user@example.com")
        repo.get_profile.return_value = SimpleNamespace(id="user-1", role="customer", status="active")
        repo.client.rest_get.return_value = [order]
        with pytest.raises(HTTPException) as caught:
            confirm(PaymentConfirmRequest(order_id="GE-DIRECT-1", amount=8000), "token")

    assert caught.value.status_code == 409
    assert isinstance(caught.value.detail, dict)
    assert caught.value.detail.get("code") == "TAX_TYPE_UNCLASSIFIED"


@pytest.mark.parametrize(
    ("flow", "mapper"),
    (("ledger", map_ledger_error), ("voucher", map_transaction_error), ("subsidized", map_transaction_error)),
)
def test_unclassified_sql_errors_have_stable_409_contract_without_db_leak(flow, mapper):
    raw = 'database detail: TAX_TYPE_UNCLASSIFIED secret relation payment_orders'
    error = mapper(SupabaseHttpError(400, raw))

    assert error.status_code == 409, flow
    assert error.detail["code"] == "TAX_TYPE_UNCLASSIFIED"
    assert error.detail["message"] == "과세 유형이 설정되지 않아 결제할 수 없어요"
    assert raw not in str(error.detail)
