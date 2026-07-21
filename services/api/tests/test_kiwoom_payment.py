import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.payments import checkout, router
from app.services.kiwoom_payment import (
    KiwoomHashInput,
    KiwoomPaymentError,
    cancel_payment,
    request_payment_hash,
)


class _Headers:
    def get_content_charset(self):
        return "utf-8"


class _Response:
    def __init__(self, payload):
        self.payload = payload
        self.headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class KiwoomPaymentServiceTests(unittest.TestCase):
    @patch("app.services.kiwoom_payment.urlopen", return_value=_Response({
        "RESULTCODE": "0000", "ERRORMESSAGE": "", "KIWOOM_ENC": "secure-hash",
    }))
    def test_hash_request_uses_server_order_values_as_strings(self, mocked_urlopen):
        result = request_payment_hash(
            "https://apitest.kiwoompay.co.kr",
            KiwoomHashInput(cpid="CPID", order_id="GE-order-123", amount=9000),
        )
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://apitest.kiwoompay.co.kr/pay/hash")
        self.assertEqual(json.loads(request.data.decode()), {
            "PAYMETHOD": "TOTAL", "TYPE": "W", "CPID": "CPID",
            "ORDERNO": "GE-order-123", "AMOUNT": "9000",
        })
        self.assertEqual(result, "secure-hash")

    @patch("app.services.kiwoom_payment.urlopen")
    def test_cancel_runs_ready_then_cancel_and_validates_result(self, mocked_urlopen):
        mocked_urlopen.side_effect = [
            _Response({"RETURNURL": "https://apitest.kiwoompay.co.kr/pay/cancel", "TOKEN": "token-1"}),
            _Response({"RESULTCODE": "0000", "TOKEN": "token-1", "AMOUNT": "72000", "TRXID": "trx-1"}),
        ]
        result = cancel_payment(
            "https://apitest.kiwoompay.co.kr", "auth-key", "CPID", "trx-1", 72000,
            cancel_reason="식권구매환불",
        )
        ready, cancel = [call.args[0] for call in mocked_urlopen.call_args_list]
        self.assertEqual(ready.full_url, "https://apitest.kiwoompay.co.kr/pay/ready")
        self.assertEqual(ready.get_header("Authorization"), "auth-key")
        self.assertEqual(json.loads(ready.data.decode("euc-kr")), {
            "CPID": "CPID", "PAYMETHOD": "CARD", "CANCELREQ": "Y",
        })
        self.assertEqual(cancel.get_header("Token"), "token-1")
        self.assertEqual(json.loads(cancel.data.decode("euc-kr"))["AMOUNT"], "72000")
        self.assertEqual(result["RESULTCODE"], "0000")

    @patch("app.services.kiwoom_payment.urlopen")
    def test_cancel_rejects_untrusted_return_url(self, mocked_urlopen):
        mocked_urlopen.return_value = _Response({"RETURNURL": "https://evil.example/cancel", "TOKEN": "token-1"})
        with self.assertRaises(KiwoomPaymentError) as ctx:
            cancel_payment("https://apitest.kiwoompay.co.kr", "auth", "CPID", "trx", 1000)
        self.assertEqual(ctx.exception.code, "KIWOOMPAY_INVALID_CANCEL_URL")

    def test_checkout_posts_hash_bound_form_without_external_sdk(self):
        order = {
            "user_id": "user-1", "amount": 8000, "order_id": "GE-order-123",
            "product_name": "그린잇 식권", "merchant_name": "돈토", "pay_type": "direct",
            "merchant_id": "merchant-1", "product_id": "product-1", "voucher_product_id": None,
        }
        settings = SimpleNamespace(
            public_api_base_url="https://api.example.com/v1",
            kiwoompay_cpid="CPID", kiwoompay_base_url="https://apitest.kiwoompay.co.kr",
            kiwoompay_app_url="greeneatgo://payment",
        )
        with patch("app.routers.payments.JoinRepository") as repo_class, patch(
            "app.routers.payments.get_settings", return_value=settings,
        ), patch("app.routers.payments.request_payment_hash", return_value="secure-hash"):
            repo_class.return_value.client.rest_get.return_value = [order]
            html = bytes(checkout("checkout-token").body).decode()
        self.assertIn("https://apitest.kiwoompay.co.kr/pay/linkEnc", html)
        self.assertIn('name="KIWOOM_ENC" value="secure-hash"', html)
        self.assertIn('name="PAYMETHOD" value="TOTAL"', html)
        self.assertIn("document.getElementById('payment').submit()", html)

    def test_notification_validates_order_and_persists_daou_transaction(self):
        app = FastAPI()
        app.include_router(router)
        order = {
            "id": "db-order", "order_id": "GE-order-123", "amount": 8000,
            "status": "ready", "pay_type": "direct", "provider_payment_key": None,
        }
        settings = SimpleNamespace(
            kiwoompay_cpid="CPID", kiwoompay_notification_ips=("123.140.121.205",),
        )
        with patch("app.routers.payments.JoinRepository") as repo_class, patch(
            "app.routers.payments.get_settings", return_value=settings,
        ):
            repo = repo_class.return_value
            repo.client.rest_get.return_value = [order]
            repo.client.rest_patch.return_value = [{**order, "status": "done"}]
            response = TestClient(app).get(
                "/payments/notification",
                params={
                    "CPID": "CPID", "PAYMETHOD": "CARD", "ORDERNO": "GE-order-123",
                    "DAOUTRX": "daou-trx-1", "AMOUNT": "8000", "SETTDATE": "20260721090000",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("<RESULT>SUCCESS</RESULT>", response.text)
        update = repo.client.rest_patch.call_args.args[2]
        self.assertEqual(update["provider_payment_key"], "daou-trx-1")
        self.assertEqual(update["provider_response"]["ORDERNO"], "GE-order-123")


if __name__ == "__main__":
    unittest.main()
