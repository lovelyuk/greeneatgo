import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.routers.merchant_admin import _ensure_settlements
from app.routers.payments import confirm
from app.routers.transactions import scan
from app.routers.voucher_products import active_products, purchase_subsidized, subsidized_price
from app.schemas import PaymentConfirmRequest, TransactionScanRequest, VoucherPurchaseRequest


class SubsidizedLedgerTests(unittest.TestCase):
    @patch("app.routers.voucher_products.get_settings")
    @patch("app.routers.voucher_products.JoinRepository")
    def test_legacy_empty_purchase_body_resolves_unique_contract_product(self, repo_class, settings):
        repo = repo_class.return_value
        self._employee_repo(repo)
        settings.return_value.pilot_merchant_id = "merchant-1"
        settings.return_value.public_api_base_url = "https://api.example.com"
        merchant = {"id": "merchant-1", "name": "돈토"}
        contract = {"unit_price": 8000, "subsidy_enabled": True,
                    "company_subsidy_amount": 1000, "restaurant_subsidy_amount": 1000, "status": "active"}
        product = {"id": "legacy-product", "name": "1장", "voucher_count": 1,
                   "bonus_count": 0, "sale_price": 8000, "status": "active",
                   "kiwoom_pay_method": "TOTAL", "is_event": False}
        repo.client.rest_get.side_effect = [[merchant], [contract], [product]]
        repo.client.rest_post.return_value = [{"id": "db-order", "amount": 6000}]
        repo.client.rpc.side_effect = [
            {"expired_count": 0}, {"point_amount": 0, "card_amount": 6000},
        ]

        data = purchase_subsidized(None, "bearer")["data"]

        self.assertEqual(data["product_id"], "legacy-product")
        self.assertEqual(data["card_amount"], 6000)

    @patch("app.routers.voucher_products.get_settings")
    @patch("app.routers.voucher_products.JoinRepository")
    def test_legacy_empty_purchase_body_rejects_ambiguous_products(self, repo_class, settings):
        repo = repo_class.return_value
        self._employee_repo(repo)
        settings.return_value.pilot_merchant_id = "merchant-1"
        merchant = {"id": "merchant-1", "name": "돈토"}
        contract = {"unit_price": 8000, "subsidy_enabled": True,
                    "company_subsidy_amount": 1000, "restaurant_subsidy_amount": 1000, "status": "active"}
        products = [{"id": f"legacy-{i}", "name": "1장", "voucher_count": 1,
                     "bonus_count": 0, "sale_price": 8000, "status": "active",
                     "kiwoom_pay_method": "TOTAL", "is_event": False} for i in range(2)]
        repo.client.rest_get.side_effect = [[merchant], [contract], products]

        with self.assertRaises(HTTPException) as ctx:
            purchase_subsidized(None, "bearer")

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, {
            "code": "UPGRADE_REQUIRED", "message": "상품을 안전하게 선택할 수 없어 앱 업데이트가 필요해요",
        })

    def _employee_repo(self, repo):
        repo.auth_user_from_token.return_value = SimpleNamespace(id="auth", email="employee@example.com")
        repo.get_profile.return_value = SimpleNamespace(id="user-1", role="employee", status="active", company_id="company-1")

    @patch("app.routers.voucher_products.get_settings")
    @patch("app.routers.voucher_products.JoinRepository")
    def test_product_purchase_uses_bearer_identity_and_package_snapshots(self, repo_class, settings):
        repo = repo_class.return_value
        self._employee_repo(repo)
        settings.return_value.pilot_merchant_id = "merchant-1"
        settings.return_value.public_api_base_url = "https://api.example"
        merchant = {"id": "merchant-1", "name": "돈토"}
        contract = {"company_id": "company-1", "unit_price": 8000, "subsidy_enabled": True,
                    "company_subsidy_amount": 1000, "restaurant_subsidy_amount": 1000, "status": "active"}
        repo.client.rest_get.side_effect = [[merchant], [contract]]
        price = subsidized_price("bearer")
        self.assertEqual(price["data"]["employee_pay_amount"], 6000)

        product = {"id": "product-123", "merchant_id": "merchant-1", "name": "10+1", "voucher_count": 10,
                   "bonus_count": 1, "sale_price": 72000, "status": "active", "kiwoom_pay_method": "BANK",
                   "is_event": False}
        repo.client.rest_get.side_effect = [[merchant], [contract], [product]]
        repo.client.rest_post.return_value = [{"id": "db-order", "amount": 52000}]
        repo.client.rpc.return_value = {"point_amount": 2000, "card_amount": 4000}
        order = purchase_subsidized(VoucherPurchaseRequest(product_id="product-123"), "bearer")
        values = repo.client.rest_post.call_args.args[1]
        self.assertEqual(order["data"]["amount"], 4000)
        self.assertEqual(order["data"]["point_amount"], 2000)
        self.assertEqual(values["user_id"], "user-1")
        self.assertEqual(values["company_id"], "company-1")
        self.assertEqual(values["pay_type"], "subsidized")
        self.assertEqual(values["company_subsidy_amount"], 1000)
        self.assertEqual(values["restaurant_subsidy_amount"], 1000)
        self.assertEqual(values["voucher_product_id"], "product-123")
        self.assertEqual(values["voucher_count"], 11)
        self.assertEqual(values["paid_voucher_count"], 10)
        self.assertEqual(values["bonus_voucher_count"], 1)
        self.assertEqual(values["total_employee_burden"], 52000)
        self.assertEqual(values["voucher_purchase_price"], "5200.0000")
        self.assertEqual(values["requested_payment_method"], "BANK")

    @patch("app.routers.voucher_products.get_settings")
    @patch("app.routers.voucher_products.JoinRepository")
    def test_point_only_purchase_skips_pg_and_fulfills_atomically(self, repo_class, settings):
        repo = repo_class.return_value
        self._employee_repo(repo)
        settings.return_value.pilot_merchant_id = "merchant-1"
        merchant = {"id": "merchant-1", "name": "돈토"}
        contract = {"unit_price": 8000, "subsidy_enabled": True, "company_subsidy_amount": 1000, "restaurant_subsidy_amount": 1000, "status": "active"}
        product = {"id": "product-123", "merchant_id": "merchant-1", "name": "1장", "voucher_count": 1,
                   "bonus_count": 0, "sale_price": 8000, "status": "active", "kiwoom_pay_method": "TOTAL",
                   "is_event": False}
        repo.client.rest_get.side_effect = [[merchant], [contract], [product]]
        repo.client.rest_post.return_value = [{"id": "db-order", "amount": 6000}]
        repo.client.rpc.side_effect = [
            {"expired_count": 0, "released_point_amount": 0},
            {"point_amount": 6000, "card_amount": 0},
            {"issued_count": 1},
        ]
        result = purchase_subsidized(VoucherPurchaseRequest(product_id="product-123"), "bearer")["data"]
        self.assertTrue(result["point_only"])
        self.assertIsNone(result["checkout_url"])
        self.assertEqual(repo.client.rpc.call_args_list[0].args, (
            "expire_stale_subsidized_orders", {"p_user_id": "user-1"}))
        self.assertEqual(repo.client.rpc.call_args_list[2].args[0], "fulfill_subsidized_order")
        self.assertIsNone(repo.client.rpc.call_args_list[2].args[1]["p_provider_payment_key"])

    @patch("app.routers.voucher_products.get_settings")
    @patch("app.routers.voucher_products.JoinRepository")
    def test_ledger_employee_catalog_has_no_products(self, repo_class, settings):
        repo = repo_class.return_value
        self._employee_repo(repo)
        settings.return_value.pilot_merchant_id = "merchant-1"
        merchant = {"id": "merchant-1", "name": "돈토"}
        contract = {"company_id": "company-1", "unit_price": 8000, "subsidy_enabled": False, "status": "active"}
        repo.client.rest_get.side_effect = [[merchant], [contract]]
        self.assertEqual(active_products("bearer")["data"], {"purchase_mode": "none", "items": []})
        self.assertEqual(repo.client.rest_get.call_count, 2)

    @patch("app.routers.voucher_products.get_settings")
    @patch("app.routers.voucher_products.JoinRepository")
    def test_subsidy_employee_catalog_prices_each_active_product(self, repo_class, settings):
        repo = repo_class.return_value
        self._employee_repo(repo)
        settings.return_value.pilot_merchant_id = "merchant-1"
        merchant = {"id": "merchant-1", "name": "돈토"}
        contract = {"company_id": "company-1", "unit_price": 8000, "subsidy_enabled": True,
                    "company_subsidy_amount": 1000, "restaurant_subsidy_amount": 500, "status": "active"}
        product = {"id": "product-123", "merchant_id": "merchant-1", "name": "10+1", "voucher_count": 10,
                   "bonus_count": 1, "sale_price": 72000, "status": "active", "kiwoom_pay_method": "BANK",
                   "is_event": False}
        repo.client.rest_get.side_effect = [[merchant], [contract], [product]]
        data = active_products("bearer")["data"]
        self.assertEqual(repo.client.rpc.call_args.args, (
            "expire_stale_subsidized_orders", {"p_user_id": "user-1"}))
        self.assertEqual(data["purchase_mode"], "subsidized")
        self.assertEqual(data["items"][0]["employee_pay_amount"], 57000)
        self.assertEqual(data["items"][0]["per_voucher_company_subsidy_amount"], 1000)
        self.assertEqual(data["items"][0]["per_voucher_restaurant_subsidy_amount"], 500)
        self.assertEqual(data["items"][0]["company_subsidy_amount"], 1000)
        self.assertEqual(data["items"][0]["restaurant_subsidy_amount"], 500)
        # Bonus vouchers are excluded: package totals use paid voucher_count=10.
        self.assertEqual(data["items"][0]["total_company_subsidy_amount"], 10000)
        self.assertEqual(data["items"][0]["total_restaurant_subsidy_amount"], 5000)

    @patch("app.routers.voucher_products.get_settings")
    @patch("app.routers.voucher_products.JoinRepository")
    def test_nonpositive_subsidized_product_price_is_hidden_and_rejected(self, repo_class, settings):
        repo = repo_class.return_value
        self._employee_repo(repo)
        settings.return_value.pilot_merchant_id = "merchant-1"
        merchant = {"id": "merchant-1", "name": "돈토"}
        contract = {"company_id": "company-1", "unit_price": 8000, "subsidy_enabled": True,
                    "company_subsidy_amount": 3500, "restaurant_subsidy_amount": 3500, "status": "active"}
        product = {"id": "product-123", "merchant_id": "merchant-1", "name": "1장", "voucher_count": 1,
                   "bonus_count": 0, "sale_price": 6000, "status": "active", "kiwoom_pay_method": "TOTAL",
                   "is_event": False}
        repo.client.rest_get.side_effect = [[merchant], [contract], [product]]
        self.assertEqual(active_products("bearer")["data"]["items"], [])
        repo.client.rest_get.side_effect = [[merchant], [contract], [product]]
        with self.assertRaises(Exception) as ctx:
            purchase_subsidized(VoucherPurchaseRequest(product_id="product-123"), "bearer")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "INVALID_SUBSIDIZED_PRICE")

    @patch("app.routers.transactions.get_settings")
    @patch("app.routers.transactions.JoinRepository")
    def test_scan_consumes_subsidized_voucher_without_legacy_pay(self, repo_class, settings):
        repo = repo_class.return_value
        self._employee_repo(repo)
        settings.return_value.pilot_merchant_id = "merchant-1"
        merchant = {"id": "merchant-1", "name": "돈토", "qr_token": "QR", "status": "active"}
        repo.client.rest_get.side_effect = [[merchant], [merchant], [{"unit_price": 8000, "status": "active", "subsidy_enabled": True}], [{"name": "회사"}]]
        repo.client.rpc.return_value = {"id": "tx-1", "remaining": 0, "company_subsidy_amount": 1000}
        result = scan(TransactionScanRequest(qr_data="QR", idempotency_key="subsidized-scan"), "bearer")
        self.assertEqual(result["pay_type"], "subsidized")
        repo.client.rpc.assert_called_once_with("consume_subsidized_voucher", {
            "p_user_id": "user-1", "p_company_id": "company-1", "p_merchant_id": "merchant-1", "p_idempotency_key": "subsidized-scan"})

    @patch("app.routers.payments.JoinRepository")
    def test_subsidized_confirm_reads_completed_notification_result(self, repo_class):
        repo = repo_class.return_value
        self._employee_repo(repo)
        repo.client.rest_get.return_value = [{
            "id": "db-order", "order_id": "GE-S-order", "amount": 6000,
            "status": "done", "pay_type": "subsidized", "provider_payment_key": "daou-trx",
        }]
        result = confirm(PaymentConfirmRequest(order_id="GE-S-order", amount=6000), "bearer")
        self.assertEqual(result["data"]["provider_payment_key"], "daou-trx")
        repo.client.rpc.assert_not_called()

    def test_settlement_charges_only_company_share_for_subsidized(self):
        repo = MagicMock()
        repo.client.rest_get.side_effect = [[
            {"id": "ledger", "amount": -8000, "kind": "spend", "pay_type": "ledger", "created_at": "2026-07-01T00:00:00Z"},
            {"id": "sub", "amount": -8000, "kind": "spend", "pay_type": "subsidized", "company_subsidy_amount": 1000, "created_at": "2026-07-02T00:00:00Z"},
        ], [], [{"period_ym": "2026-07", "total_amount": 9000, "tx_count": 2}]]
        rows = _ensure_settlements(repo, "merchant-1", "company-1")
        self.assertEqual(rows[0]["total_amount"], 9000)
        posted = repo.client.rest_post.call_args.args[1]
        self.assertEqual(posted["total_amount"], 9000)


if __name__ == "__main__":
    unittest.main()
