import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.routers.merchant_admin import _ensure_settlements
from app.routers.toss_payments import confirm
from app.routers.transactions import scan
from app.routers.voucher_products import purchase_subsidized, subsidized_price
from app.schemas import TossPaymentConfirmRequest, TransactionScanRequest


class SubsidizedLedgerTests(unittest.TestCase):
    def _employee_repo(self, repo):
        repo.auth_user_from_token.return_value = SimpleNamespace(id="auth", email="employee@example.com")
        repo.get_profile.return_value = SimpleNamespace(id="user-1", role="employee", status="active", company_id="company-1")

    @patch("app.routers.voucher_products.get_settings")
    @patch("app.routers.voucher_products.JoinRepository")
    def test_price_and_purchase_use_bearer_identity_and_contract_snapshot(self, repo_class, settings):
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

        repo.client.rest_get.side_effect = [[merchant], [contract]]
        repo.client.rest_post.return_value = [{"id": "db-order", "amount": 6000}]
        repo.client.rpc.return_value = {"point_amount": 2000, "card_amount": 4000}
        order = purchase_subsidized("bearer")
        values = repo.client.rest_post.call_args.args[1]
        self.assertEqual(order["data"]["amount"], 4000)
        self.assertEqual(order["data"]["point_amount"], 2000)
        self.assertEqual(values["user_id"], "user-1")
        self.assertEqual(values["company_id"], "company-1")
        self.assertEqual(values["pay_type"], "subsidized")
        self.assertEqual(values["company_subsidy_amount"], 1000)

    @patch("app.routers.voucher_products.get_settings")
    @patch("app.routers.voucher_products.JoinRepository")
    def test_point_only_purchase_skips_toss_and_fulfills_atomically(self, repo_class, settings):
        repo = repo_class.return_value
        self._employee_repo(repo)
        settings.return_value.pilot_merchant_id = "merchant-1"
        merchant = {"id": "merchant-1", "name": "돈토"}
        contract = {"unit_price": 8000, "subsidy_enabled": True, "company_subsidy_amount": 1000, "restaurant_subsidy_amount": 1000, "status": "active"}
        repo.client.rest_get.side_effect = [[merchant], [contract]]
        repo.client.rest_post.return_value = [{"id": "db-order", "amount": 6000}]
        repo.client.rpc.side_effect = [{"point_amount": 6000, "card_amount": 0}, {"issued_count": 1}]
        result = purchase_subsidized("bearer")["data"]
        self.assertTrue(result["point_only"])
        self.assertIsNone(result["checkout_url"])
        self.assertEqual(repo.client.rpc.call_args_list[1].args[0], "fulfill_subsidized_order")
        self.assertIsNone(repo.client.rpc.call_args_list[1].args[1]["p_payment_key"])

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

    @patch("app.routers.toss_payments.confirm_payment")
    @patch("app.routers.toss_payments.get_settings")
    @patch("app.routers.toss_payments.JoinRepository")
    def test_toss_subsidized_confirmation_uses_atomic_fulfillment(self, repo_class, settings, toss_confirm):
        repo = repo_class.return_value
        self._employee_repo(repo)
        repo.client.rest_get.return_value = [{"id": "db-order", "order_id": "GE-S-order", "amount": 6000,
            "status": "ready", "pay_type": "subsidized", "payment_key": None, "approved_at": None}]
        toss_confirm.return_value = {"status": "DONE", "paymentKey": "pay-key", "method": "카드"}
        repo.client.rpc.return_value = {"issued_count": 1, "duplicate": False}
        result = confirm(TossPaymentConfirmRequest(payment_key="pay-key", order_id="GE-S-order", amount=6000), "bearer")
        self.assertEqual(result["data"]["issued_count"], 1)
        self.assertEqual(repo.client.rpc.call_args.args[0], "fulfill_subsidized_order")
        repo.client.rest_patch.assert_not_called()

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
