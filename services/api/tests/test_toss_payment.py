import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.routers.toss_payments import checkout
from app.services.toss_payment import TossConfirmInput, TossPaymentError, confirm_payment, validate_confirm_input


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps({
            "paymentKey": "payment-key",
            "orderId": "GE-order-123",
            "totalAmount": 9000,
            "status": "DONE",
            "method": "카드",
        }).encode()


class TossPaymentServiceTests(unittest.TestCase):
    def _checkout_html(self, pay_type: str) -> str:
        order = {
            "user_id": "user-1",
            "amount": 8000,
            "order_id": "GE-order-123",
            "product_name": "돈토식권",
            "merchant_name": "돈토",
            "pay_type": pay_type,
        }
        with patch("app.routers.toss_payments.JoinRepository") as repo_class, patch(
            "app.routers.toss_payments.get_settings",
            return_value=SimpleNamespace(
                public_api_base_url="https://api.example.com",
                toss_client_key="test_ck_example",
            ),
        ):
            repo_class.return_value.client.rest_get.return_value = [order]
            return bytes(checkout("checkout-token").body).decode()

    def test_voucher_checkout_opens_standard_payment_automatically(self):
        html = self._checkout_html("voucher")
        self.assertIn("autoStart=true", html)
        self.assertIn("if(autoStart){button.style.display='none';await startPayment();}", html)

    def test_direct_product_checkout_keeps_manual_payment_button(self):
        html = self._checkout_html("direct")
        self.assertIn("autoStart=false", html)

    def test_rejects_changed_amount_before_toss_approval(self):
        payload = TossConfirmInput("payment-key", "GE-order-123", 100)
        with self.assertRaises(TossPaymentError) as ctx:
            validate_confirm_input(expected_order_id="GE-order-123", expected_amount=9000, payload=payload)
        self.assertEqual(ctx.exception.code, "AMOUNT_MISMATCH")

    def test_rejects_other_order_id_before_toss_approval(self):
        payload = TossConfirmInput("payment-key", "GE-other-123", 9000)
        with self.assertRaises(TossPaymentError) as ctx:
            validate_confirm_input(expected_order_id="GE-order-123", expected_amount=9000, payload=payload)
        self.assertEqual(ctx.exception.code, "ORDER_ID_MISMATCH")

    @patch("app.services.toss_payment.urlopen", return_value=_Response())
    def test_confirm_uses_basic_secret_and_server_amount(self, mocked_urlopen):
        payload = TossConfirmInput("payment-key", "GE-order-123", 9000)
        result = confirm_payment("test_secret", payload)

        request = mocked_urlopen.call_args.args[0]
        expected = base64.b64encode(b"test_secret:").decode()
        self.assertEqual(request.get_header("Authorization"), f"Basic {expected}")
        self.assertEqual(request.get_header("Idempotency-key"), "GE-order-123")
        self.assertEqual(json.loads(request.data), {
            "paymentKey": "payment-key",
            "orderId": "GE-order-123",
            "amount": 9000,
        })
        self.assertEqual(result["status"], "DONE")


if __name__ == "__main__":
    unittest.main()
