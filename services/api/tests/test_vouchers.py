import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.repositories.supabase_http import SupabaseHttpError
from app.routers.me import _customer_usage
from app.routers.merchant_admin import list_transactions
from app.routers.payments import confirm
from app.routers.transactions import scan
from app.routers.voucher_products import _delete_replaced_image, _event_status, _is_exposed, _values, active_products
from app.schemas import (
    PaymentConfirmRequest,
    TransactionScanRequest,
    VoucherProductCreateRequest,
)
from app.services.vouchers import calculate_sale_price, krw_amount, parse_qr_data, per_voucher_price


class VoucherCoreTests(unittest.TestCase):
    @patch("app.routers.merchant_admin.JoinRepository")
    def test_merchant_transactions_exclude_voucher_purchase_orders(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="admin", email="admin@example.com")
        repo.get_profile.return_value = SimpleNamespace(
            id="admin", role="merchant_admin", status="active", merchant_id="merchant-1"
        )
        repo.client.rest_get.side_effect = [[], []]
        repo.client.rpc.return_value = 0

        result = list_transactions("bearer")

        self.assertEqual(result["data"]["items"], [])
        payment_params = repo.client.rest_get.call_args_list[1].args[1]
        self.assertEqual(payment_params["status"], "eq.done")
        self.assertEqual(payment_params["pay_type"], "eq.direct")
        self.assertIn("pay_type", payment_params["select"])

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

    def test_event_product_requires_valid_period(self):
        now = datetime.now(timezone.utc)
        with self.assertRaises(ValidationError):
            VoucherProductCreateRequest.model_validate({
                "name": "이벤트", "voucher_count": 10, "unit_price": 8000, "is_event": True,
            })
        with self.assertRaises(ValidationError):
            VoucherProductCreateRequest.model_validate({
                "name": "이벤트", "voucher_count": 10, "unit_price": 8000, "is_event": True,
                "event_start_at": now.isoformat(), "event_end_at": (now - timedelta(minutes=1)).isoformat(),
            })

    def test_event_exposure_is_computed_without_changing_status(self):
        now = datetime(2026, 7, 10, 3, 0, tzinfo=timezone.utc)
        base = {"status": "active", "is_event": True}
        scheduled = {**base, "event_start_at": "2026-07-11T00:00:00+00:00", "event_end_at": "2026-07-12T00:00:00+00:00"}
        ongoing = {**base, "event_start_at": "2026-07-09T00:00:00+00:00", "event_end_at": "2026-07-11T00:00:00+00:00"}
        ended = {**base, "event_start_at": "2026-07-08T00:00:00+00:00", "event_end_at": "2026-07-09T00:00:00+00:00"}

        self.assertEqual(_event_status(scheduled, now)[0], "scheduled")
        self.assertEqual(_event_status(ongoing, now)[0], "event_active")
        self.assertEqual(_event_status(ended, now)[0], "event_ended")
        self.assertFalse(_is_exposed(scheduled, now))
        self.assertTrue(_is_exposed(ongoing, now))
        self.assertFalse(_is_exposed(ended, now))
        self.assertTrue(_is_exposed({"status": "active", "is_event": False}, now))
        self.assertFalse(_is_exposed({"status": "inactive", "is_event": False}, now))

    def test_voucher_image_replacement_deletes_previous_managed_object(self):
        repo = MagicMock()
        repo.client.settings.supabase_url = "https://sample.supabase.co"
        old_url = "https://sample.supabase.co/storage/v1/object/public/merchant-images/merchant-1/products/old.webp"
        new_url = "https://sample.supabase.co/storage/v1/object/public/merchant-images/merchant-1/products/new.webp"

        _delete_replaced_image(repo, "merchant-1", old_url, new_url)

        repo.client.delete_public_objects.assert_called_once_with(
            "merchant-images", ["merchant-1/products/old.webp"]
        )

    def test_qr_parser_keeps_supported_formats(self):
        self.assertEqual(parse_qr_data("restaurant:abc-123"), ("id", "abc-123"))
        self.assertEqual(parse_qr_data("QR-PILOT-KIMCHI"), ("qr_token", "QR-PILOT-KIMCHI"))
        self.assertEqual(
            parse_qr_data("greeneat://pay?qr_token=QR-PILOT-KIMCHI"),
            ("qr_token", "QR-PILOT-KIMCHI"),
        )

    @patch("app.routers.payments.JoinRepository")
    def test_confirm_returns_authoritative_completed_order(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="auth", email="a@example.com")
        repo.get_profile.return_value = SimpleNamespace(id="user-1", role="customer", status="active")
        repo.client.rest_get.return_value = [{
            "id": "db-order", "order_id": "GE-V-order", "amount": 72000, "status": "done",
            "pay_type": "voucher", "provider_payment_key": "daou-trx", "approved_at": "2026-07-10T00:00:00Z",
        }]

        result = confirm(PaymentConfirmRequest(order_id="GE-V-order", amount=72000), "bearer")

        self.assertEqual(result["data"]["provider_payment_key"], "daou-trx")
        repo.client.rpc.assert_not_called()

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

    @patch("app.routers.voucher_products.get_settings")
    @patch("app.routers.voucher_products.JoinRepository")
    def test_product_listing_filters_scheduled_and_ended_events(self, repo_class, settings):
        repo = repo_class.return_value
        settings.return_value.pilot_merchant_id = "merchant-pilot"
        now = datetime.now(timezone.utc)
        base = {
            "merchant_id": "merchant-pilot", "voucher_count": 10, "bonus_count": 0,
            "unit_price": 8000, "discount_rate": 10, "sale_price": 72000,
            "status": "active", "display_order": 0, "image_url": None,
            "created_at": now.isoformat(), "updated_at": now.isoformat(),
        }
        rows = [
            {**base, "id": "normal", "name": "상시", "is_event": False, "event_start_at": None, "event_end_at": None},
            {**base, "id": "ongoing", "name": "진행", "is_event": True,
             "event_start_at": (now - timedelta(days=1)).isoformat(), "event_end_at": (now + timedelta(days=1)).isoformat()},
            {**base, "id": "scheduled", "name": "예정", "is_event": True,
             "event_start_at": (now + timedelta(days=1)).isoformat(), "event_end_at": (now + timedelta(days=2)).isoformat()},
            {**base, "id": "ended", "name": "종료", "is_event": True,
             "event_start_at": (now - timedelta(days=2)).isoformat(), "event_end_at": (now - timedelta(days=1)).isoformat()},
        ]
        repo.client.rest_get.side_effect = [[{"id": "merchant-pilot", "name": "돈토"}], rows]

        result = active_products()

        self.assertEqual([item["id"] for item in result["data"]["items"]], ["normal", "ongoing"])
        self.assertTrue(result["data"]["items"][1]["is_event"])

    def test_customer_usage_keeps_direct_payment_history_and_exact_rpc_balance(self):
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
        self.assertEqual(usage["recent_transactions"][0]["kind"], "payment")
        self.assertEqual(usage["voucher_use_history"][0]["kind"], "voucher_use")
        repo.client.rpc.assert_called_once_with("voucher_balance", {"p_user_id": "user-1"})


if __name__ == "__main__":
    unittest.main()
