import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.repositories.supabase_http import SupabaseHttpError
from app.routers.me import _customer_usage
from app.routers.merchant_admin import list_transactions
from app.routers.payments import confirm
from app.routers.transactions import scan
from app.routers.voucher_products import _delete_replaced_image, _event_status, _is_exposed, _values, active_products, admin_delete_product
from app.schemas import (
    PaymentConfirmRequest,
    TransactionScanRequest,
    VoucherProductCreateRequest,
    VoucherProductUpdateRequest,
)
from app.services.vouchers import calculate_sale_price, krw_amount, parse_qr_data, per_voucher_price


class VoucherCoreTests(unittest.TestCase):
    def test_voucher_product_tax_type_is_always_taxable(self):
        create = VoucherProductCreateRequest.model_validate({
            "name": "식권", "voucher_count": 1, "unit_price": 8000,
            "tax_type": "tax_free",
        })
        update = VoucherProductUpdateRequest.model_validate({"tax_type": "unclassified"})
        status_only = VoucherProductUpdateRequest.model_validate({"status": "sold_out"})

        self.assertEqual(_values(create, partial=False)["tax_type"], "taxable")
        self.assertEqual(_values(update, partial=True)["tax_type"], "taxable")
        self.assertEqual(_values(status_only, partial=True)["tax_type"], "taxable")

    @patch("app.routers.voucher_products.get_settings")
    @patch("app.routers.voucher_products.JoinRepository")
    def test_legacy_public_catalog_remains_available_without_auth(self, repo_class, settings):
        repo = repo_class.return_value
        settings.return_value.pilot_merchant_id = "merchant-pilot"
        product = {"id": "public-product", "name": "식권", "voucher_count": 1,
                   "bonus_count": 0, "sale_price": 8000, "status": "active", "is_event": False}
        repo.client.rest_get.side_effect = [[{"id": "merchant-pilot", "name": "돈토"}], [product]]

        data = active_products(None)["data"]

        self.assertEqual(data["purchase_mode"], "voucher")
        self.assertEqual(data["items"][0]["id"], "public-product")
        repo.auth_user_from_token.assert_not_called()
        product_params = repo.client.rest_get.call_args_list[1].args[1]
        self.assertEqual(product_params["deleted_at"], "is.null")

    @patch("app.routers.voucher_products.JoinRepository")
    def test_public_catalog_falls_back_safely_before_0055_migration(self, repo_class):
        repo = repo_class.return_value
        legacy_product = {
            "id": "legacy-product", "merchant_id": "merchant-pilot", "name": "기존 상품",
            "voucher_count": 1, "bonus_count": 0, "unit_price": 8000, "discount_rate": 0,
            "sale_price": 8000, "status": "active", "display_order": 0, "image_url": None,
            "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        }
        repo.client.rest_get.side_effect = [
            [{"id": "merchant-pilot", "name": "돈토"}],
            SupabaseHttpError(400, "PGRST204 deleted_at column is missing"),
            [legacy_product],
        ]

        data = active_products(None)["data"]

        self.assertEqual(data["items"][0]["id"], "legacy-product")
        legacy_params = repo.client.rest_get.call_args_list[2].args[1]
        self.assertNotIn("deleted_at", legacy_params)

    @patch("app.routers.voucher_products.JoinRepository")
    def test_invalid_presented_catalog_token_never_downgrades_to_public(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.side_effect = SupabaseHttpError(401, "invalid jwt")

        with self.assertRaises(HTTPException) as ctx:
            active_products("bad-token")

        self.assertEqual(ctx.exception.status_code, 401)
        repo.client.rest_get.assert_not_called()

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

    @patch("app.routers.merchant_admin.JoinRepository")
    def test_merchant_transactions_include_company_person_and_three_type_labels(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="admin", email="admin@example.com")
        repo.get_profile.return_value = SimpleNamespace(
            id="admin", role="merchant_admin", status="active", merchant_id="merchant-1"
        )
        repo.client.rest_get.side_effect = [
            [
                {"id": "ledger", "user_id": "user-1", "company_id": "company-1", "amount": -8000,
                 "kind": "spend", "pay_type": "ledger", "created_at": "2026-07-22T01:03:00Z"},
                {"id": "subsidized", "user_id": "user-1", "company_id": "company-1", "amount": -8000,
                 "kind": "spend", "pay_type": "subsidized", "created_at": "2026-07-22T01:02:00Z"},
                {"id": "voucher", "user_id": "user-2", "company_id": None, "amount": -8000,
                 "kind": "spend", "pay_type": "voucher", "created_at": "2026-07-22T01:01:00Z"},
            ],
            [],
            [
                {"id": "user-1", "display_name": "김직원", "company_id": "company-1", "employee_no": "E001", "department": "영업"},
                {"id": "user-2", "display_name": "이일반", "company_id": None, "employee_no": None, "department": None},
            ],
            [{"id": "company-1", "name": "테스트업체"}],
        ]
        repo.client.rpc.return_value = 3

        items = list_transactions("bearer")["data"]["items"]

        self.assertEqual(
            [(item["company_name"], item["employee_name"], item["payment_type_label"]) for item in items],
            [("테스트업체", "김직원", "장부"), ("테스트업체", "김직원", "보조금"),
             ("일반 고객", "이일반", "일반")],
        )

    def test_discount_and_bonus_price_snapshots(self):
        sale = calculate_sale_price(8000, 10, 10)
        self.assertEqual(sale, Decimal("72000.00"))
        fixed_sale = calculate_sale_price(8000, 10, 0, 500)
        self.assertEqual(fixed_sale, Decimal("75000.00"))
        self.assertEqual(krw_amount(sale), 72000)
        self.assertEqual(per_voucher_price(80000, 11), Decimal("7272.7273"))
        self.assertEqual(per_voucher_price(100, 3), Decimal("33.3333"))
        with self.assertRaises(ValueError):
            calculate_sale_price("0.01", 1, 99)
        with self.assertRaises(ValueError):
            calculate_sale_price("999999999999.99", 1000, 0)

    def test_product_accepts_only_one_discount_mode(self):
        fixed = VoucherProductCreateRequest.model_validate({
            "name": "500원 할인", "voucher_count": 10, "unit_price": 8000,
            "discount_amount_per_voucher": 500,
        })
        self.assertEqual(fixed.discount_amount_per_voucher, Decimal("500"))
        with self.assertRaises(ValidationError):
            VoucherProductCreateRequest.model_validate({
                "name": "중복 할인", "voucher_count": 10, "unit_price": 8000,
                "discount_rate": 10, "discount_amount_per_voucher": 500,
            })
        with self.assertRaises(ValidationError):
            VoucherProductCreateRequest.model_validate({
                "name": "무료 오류", "voucher_count": 1, "unit_price": 8000,
                "discount_amount_per_voucher": 8000,
            })
        with self.assertRaises(ValidationError):
            VoucherProductCreateRequest.model_validate({
                "name": "반올림 무료 오류", "voucher_count": 1, "unit_price": "0.01", "discount_rate": 99,
            })
        with self.assertRaises(ValidationError):
            VoucherProductCreateRequest.model_validate({
                "name": "최대 금액 초과", "voucher_count": 1000, "unit_price": "999999999999.99",
            })

    def test_discount_must_be_below_one_hundred(self):
        with self.assertRaises(ValidationError):
            VoucherProductCreateRequest.model_validate(
                {"name": "free", "voucher_count": 1, "unit_price": 8000, "discount_rate": 100}
            )

    def test_voucher_payment_policy_defaults_total_and_accepts_only_bank_or_total(self):
        default = VoucherProductCreateRequest.model_validate(
            {"name": "일반", "voucher_count": 1, "unit_price": 8000}
        )
        bank = VoucherProductCreateRequest.model_validate(
            {"name": "10+1", "voucher_count": 10, "bonus_count": 1,
             "unit_price": 8000, "kiwoom_pay_method": "BANK"}
        )
        self.assertEqual(default.kiwoom_pay_method, "TOTAL")
        self.assertEqual(bank.kiwoom_pay_method, "BANK")
        with self.assertRaises(ValidationError):
            VoucherProductCreateRequest.model_validate(
                {"name": "잘못됨", "voucher_count": 1, "unit_price": 8000,
                 "kiwoom_pay_method": "CARD"}
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

    def test_admin_payload_rejects_client_sale_price(self):
        with self.assertRaises(ValidationError):
            VoucherProductCreateRequest.model_validate({
                "name": "10장", "voucher_count": 10, "unit_price": 8000,
                "discount_rate": 10, "sale_price": 1,
            })

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
        self.assertFalse(_is_exposed({"status": "sold_out", "is_event": False}, now))

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
            "pay_type": "voucher", "provider_payment_key": "daou-trx", "approved_at": "2026-07-10T00:00:00Z", "tax_type": "taxable",
        }]

        result = confirm(PaymentConfirmRequest(order_id="GE-V-order", amount=72000), "bearer")

        self.assertEqual(result["data"]["payment"]["transaction_id"], "daou-trx")
        self.assertNotIn("provider_payment_key", result["data"])
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
    def test_employee_scan_uses_contract_price_without_product_selection(self, repo_class, settings, legacy_pay):
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
        ), "bearer")

        request = legacy_pay.call_args.args[0]
        self.assertEqual(request.amount, 8300)
        self.assertNotIn("product_id", request.model_dump())
        self.assertEqual(result["pay_type"], "ledger")

    def test_scan_ignores_removed_product_selection_fields_from_old_clients(self):
        payload = TransactionScanRequest.model_validate({
            "qr_data": "QR-DONTO",
            "idempotency_key": "scan-key-legacy",
            "product_id": "product-override",
            "amount": 1,
        })
        self.assertNotIn("product_id", payload.model_dump())
        self.assertNotIn("amount", payload.model_dump())

    @patch("app.routers.voucher_products.get_settings")
    @patch("app.routers.voucher_products.JoinRepository")
    def test_product_listing_is_constrained_to_resolved_pilot_merchant(self, repo_class, settings):
        repo = repo_class.return_value
        settings.return_value.pilot_merchant_id = "merchant-pilot"
        repo.auth_user_from_token.return_value = SimpleNamespace(id="auth", email="a@example.com")
        repo.get_profile.return_value = SimpleNamespace(id="user-1", role="customer", status="active", company_id=None)
        repo.client.rest_get.side_effect = [[{"id": "merchant-pilot", "name": "돈토"}], []]

        result = active_products("bearer")

        self.assertEqual(result["data"]["items"], [])
        repo.auth_user_from_token.assert_called_once_with("bearer")
        product_params = repo.client.rest_get.call_args_list[1].args[1]
        self.assertEqual(product_params["merchant_id"], "eq.merchant-pilot")

    @patch("app.routers.voucher_products.JoinRepository")
    def test_product_catalog_requires_an_active_voucher_account(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="auth", email="a@example.com")
        repo.get_profile.return_value = SimpleNamespace(
            id="admin-1", role="merchant_admin", status="active", company_id=None,
        )

        with self.assertRaises(HTTPException) as ctx:
            active_products("bearer")

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIsInstance(ctx.exception.detail, dict)
        self.assertEqual(cast(dict, ctx.exception.detail)["code"], "VOUCHER_ACCOUNT_ONLY")
        repo.client.rest_get.assert_not_called()

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
        repo.auth_user_from_token.return_value = SimpleNamespace(id="auth", email="a@example.com")
        repo.get_profile.return_value = SimpleNamespace(id="user-1", role="customer", status="active", company_id=None)

        result = active_products("bearer")

        self.assertEqual([item["id"] for item in result["data"]["items"]], ["normal", "ongoing"])
        self.assertEqual(result["data"]["purchase_mode"], "voucher")
        self.assertTrue(result["data"]["items"][1]["is_event"])

    def test_customer_usage_keeps_direct_payment_history_and_exact_rpc_balance(self):
        repo = MagicMock()
        repo.client.rpc.return_value = 1501
        repo.client.rest_get.side_effect = [
            [
                {"id": "voucher-bonus", "amount": 0, "product_name": "식권 사용", "merchant_id": "m1",
                 "voucher_id": "v11", "created_at": "2026-07-10T01:30:00Z", "pay_type": "voucher"},
                {"id": "voucher-paid", "amount": -8000, "product_name": "식권 사용", "merchant_id": "m1",
                 "voucher_id": "v10", "created_at": "2026-07-10T01:00:00Z", "pay_type": "voucher"},
            ],
            [{"id": "direct-order", "amount": 9000, "product_name": "비빔밥", "merchant_name": "돈토",
              "approved_at": "2026-07-10T02:00:00Z", "created_at": "2026-07-10T01:59:00Z",
              "pay_type": "direct"}],
            [
                {"id": "v10", "order_id": "voucher-order", "issue_index": 10},
                {"id": "v11", "order_id": "voucher-order", "issue_index": 11},
            ],
            [{"id": "voucher-order", "paid_voucher_count": 10}],
            [{"id": "m1", "name": "돈토"}],
        ]

        usage = _customer_usage(repo, "user-1")

        self.assertEqual(usage["voucher_balance"], 1501)
        self.assertEqual(usage["recent_transactions"][0]["kind"], "payment")
        self.assertEqual(usage["voucher_use_history"][0]["amount"], 0)
        self.assertTrue(usage["voucher_use_history"][0]["is_bonus"])
        self.assertEqual(usage["voucher_use_history"][1]["amount"], 8000)
        self.assertFalse(usage["voucher_use_history"][1]["is_bonus"])
        repo.client.rpc.assert_called_once_with("voucher_balance", {"p_user_id": "user-1"})


@patch("app.routers.voucher_products._merchant_admin", return_value=(SimpleNamespace(id="admin"), "merchant-1"))
@patch("app.routers.voucher_products.JoinRepository")
def test_admin_product_delete_is_tenant_scoped_soft_delete(repo_class, _merchant_admin):
    repo = repo_class.return_value
    repo.client.rest_patch.return_value = [{"id": "product-1"}]

    result = admin_delete_product("product-1", "token")

    assert result["data"] == {"deleted": True, "id": "product-1"}
    params = repo.client.rest_patch.call_args.args[1]
    values = repo.client.rest_patch.call_args.args[2]
    assert params == {
        "id": "eq.product-1", "merchant_id": "eq.merchant-1", "deleted_at": "is.null",
    }
    assert values["status"] == "sold_out"
    assert values["deleted_at"]


if __name__ == "__main__":
    unittest.main()
