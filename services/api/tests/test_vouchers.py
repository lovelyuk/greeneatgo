import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.repositories.supabase_http import SupabaseHttpError
from app.routers.me import _customer_usage
from app.routers.toss_payments import confirm
from app.routers.transactions import scan
from app.routers.voucher_products import _values, active_products
from app.schemas import (
    TossPaymentConfirmRequest,
    TransactionScanRequest,
    VoucherProductCreateRequest,
)
from app.services.vouchers import calculate_sale_price, krw_amount, parse_qr_data, per_voucher_price


class VoucherCoreTests(unittest.TestCase):
    def test_discount_and_bonus_price_snapshots(self):
        sale = calculate_sale_price(8000, 10, 10)
        self.assertEqual(sale, Decimal("72000.00"))
        self.assertEqual(krw_amount(sale), 72000)
        self.assertEqual(per_voucher_price(80000, 11), Decimal("7272.7273"))
        self.assertEqual(per_voucher_price(100, 3), Decimal("33.3333"))

    def test_discount_must_be_below_one_hundred(self):
        with self.assertRaises(ValidationError):
            VoucherProductCreateRequest.model_validate(
                {"name": "free", "voucher_count": 1, "unit_price": 8000, "discount_rate": 100}
            )

    def test_voucher_name_is_trimmed_and_blank_is_rejected(self):
        payload = VoucherProductCreateRequest.model_validate(
            {"name": "  10장  ", "voucher_count": 10, "unit_price": 8000}
        )
        self.assertEqual(payload.name, "10장")
        with self.assertRaises(ValidationError):
            VoucherProductCreateRequest.model_validate(
                {"name": "   ", "voucher_count": 10, "unit_price": 8000}
            )

    def test_admin_payload_never_accepts_client_sale_price(self):
        payload = VoucherProductCreateRequest.model_validate({
            "name": "10장", "voucher_count": 10, "unit_price": 8000,
            "discount_rate": 10, "sale_price": 1,
        })
        values = _values(payload, partial=False)
        self.assertNotIn("sale_price", values)

    def test_qr_parser_keeps_supported_formats(self):
        self.assertEqual(parse_qr_data("restaurant:abc-123"), ("id", "abc-123"))
        self.assertEqual(parse_qr_data("QR-PILOT-KIMCHI"), ("qr_token", "QR-PILOT-KIMCHI"))
        self.assertEqual(
            parse_qr_data("greeneat://pay?qr_token=QR-PILOT-KIMCHI"),
            ("qr_token", "QR-PILOT-KIMCHI"),
        )

    @patch("app.routers.toss_payments.confirm_payment")
    @patch("app.routers.toss_payments.get_settings")
    @patch("app.routers.toss_payments.JoinRepository")
    def test_toss_done_uses_atomic_voucher_fulfillment(self, repo_class, settings, toss_confirm):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="auth", email="a@example.com")
        repo.get_profile.return_value = SimpleNamespace(id="user-1", role="customer", status="active")
        repo.client.rest_get.return_value = [{
            "id": "db-order", "order_id": "GE-V-order", "amount": 72000, "status": "ready",
            "pay_type": "voucher", "payment_key": None, "approved_at": None,
        }]
        toss_confirm.return_value = {
            "status": "DONE", "paymentKey": "payment-key", "method": "카드",
            "approvedAt": "2026-07-10T00:00:00Z",
        }
        repo.client.rpc.return_value = {"issued_count": 10, "voucher_balance": 10, "duplicate": False}

        result = confirm(TossPaymentConfirmRequest(
            payment_key="payment-key", order_id="GE-V-order", amount=72000
        ), "bearer")

        self.assertEqual(result["data"]["issued_count"], 10)
        repo.client.rpc.assert_called_once()
        self.assertEqual(repo.client.rpc.call_args.args[0], "fulfill_voucher_order")
        repo.client.rest_patch.assert_not_called()

    @patch("app.routers.transactions.JoinRepository")
    def test_customer_scan_returns_402_no_voucher(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="auth", email="a@example.com")
        repo.get_profile.return_value = SimpleNamespace(id="user-1", role="customer", status="active", company_id=None)
        repo.client.rest_get.return_value = [{
            "id": "merchant-1", "name": "돈토", "qr_token": "QR-DONTO", "status": "active"
        }]
        repo.client.rpc.side_effect = SupabaseHttpError(400, '{"message":"NO_VOUCHER"}')

        with self.assertRaises(HTTPException) as ctx:
            scan(TransactionScanRequest(qr_data="QR-DONTO", idempotency_key="scan-key-123"), "bearer")
        self.assertEqual(ctx.exception.status_code, 402)
        detail = ctx.exception.detail
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail.get("reason"), "no_voucher")  # type: ignore[union-attr]

    @patch("app.routers.transactions.pay")
    @patch("app.routers.transactions.get_settings")
    @patch("app.routers.transactions.JoinRepository")
    def test_employee_scan_uses_contract_price_and_drops_product_override(self, repo_class, settings, legacy_pay):
        repo = repo_class.return_value
        settings.return_value.pilot_merchant_id = "merchant-1"
        repo.auth_user_from_token.return_value = SimpleNamespace(id="auth", email="a@example.com")
        repo.get_profile.return_value = SimpleNamespace(
            id="user-1", role="employee", status="active", company_id="company-1"
        )
        merchant = {"id": "merchant-1", "name": "돈토", "qr_token": "QR-DONTO", "status": "active"}
        repo.client.rest_get.side_effect = [
            [merchant], [merchant], [{"unit_price": 8300, "status": "active"}], [{"name": "테스트회사"}],
        ]
        legacy_pay.return_value = {"data": {"payment": {"id": "tx-1"}}}

        result = scan(TransactionScanRequest(
            qr_data="QR-DONTO", idempotency_key="scan-key-employee",
            product_id="product-override", amount=1,
        ), "bearer")

        request = legacy_pay.call_args.args[0]
        self.assertEqual(request.amount, 8300)
        self.assertIsNone(request.product_id)
        self.assertEqual(result["pay_type"], "ledger")

    @patch("app.routers.voucher_products.get_settings")
    @patch("app.routers.voucher_products.JoinRepository")
    def test_product_listing_is_constrained_to_resolved_pilot_merchant(self, repo_class, settings):
        repo = repo_class.return_value
        settings.return_value.pilot_merchant_id = "merchant-pilot"
        repo.client.rest_get.side_effect = [[{"id": "merchant-pilot", "name": "돈토"}], []]

        result = active_products()

        self.assertEqual(result["data"]["items"], [])
        product_params = repo.client.rest_get.call_args_list[1].args[1]
        self.assertEqual(product_params["merchant_id"], "eq.merchant-pilot")

    def test_customer_usage_keeps_direct_toss_history_and_exact_rpc_balance(self):
        repo = MagicMock()
        repo.client.rpc.return_value = 1501
        repo.client.rest_get.side_effect = [
            [{"id": "voucher-tx", "amount": -8000, "product_name": "식권 사용", "merchant_id": "m1",
              "voucher_id": "v1", "created_at": "2026-07-10T01:00:00Z", "pay_type": "voucher"}],
            [{"id": "direct-order", "amount": 9000, "product_name": "비빔밥", "merchant_name": "돈토",
              "approved_at": "2026-07-10T02:00:00Z", "created_at": "2026-07-10T01:59:00Z",
              "pay_type": "direct"}],
            [{"id": "m1", "name": "돈토"}],
        ]

        usage = _customer_usage(repo, "user-1")

        self.assertEqual(usage["voucher_balance"], 1501)
        self.assertEqual(usage["recent_transactions"][0]["kind"], "toss_payment")
        self.assertEqual(usage["voucher_use_history"][0]["kind"], "voucher_use")
        repo.client.rpc.assert_called_once_with("voucher_balance", {"p_user_id": "user-1"})


if __name__ == "__main__":
    unittest.main()
