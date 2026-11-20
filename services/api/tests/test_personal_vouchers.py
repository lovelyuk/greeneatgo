"""Ledger employees pay with the company ledger or a voucher they bought themselves."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.repositories.supabase_http import SupabaseHttpError
from app.routers.transactions import consume_meal, member_qr, redeem_member_qr, scan
from app.routers.voucher_products import purchase
from app.schemas import MemberQrRedeemRequest, TransactionScanRequest, VoucherPurchaseRequest
from app.services import meal_qr

SECRET = "unit-test-meal-qr-secret"
USER = "0f8fad5b-d9cb-469f-a165-70867728950e"
MERCHANT = {"id": "merchant-1", "name": "돈토식당", "qr_token": "QR-DONTO", "avg_price": 8000, "status": "active"}
SETTINGS = SimpleNamespace(meal_qr_secret=SECRET, pilot_merchant_id=None, public_api_base_url="https://api.example/v1")
MIGRATIONS = Path(__file__).parents[3] / "supabase/migrations"


def employee():
    return SimpleNamespace(id=USER, role="employee", status="active", company_id="company-1", display_name="김직원")


class MealQrSourceTests(unittest.TestCase):
    def test_personal_code_round_trips_and_keeps_the_layout(self):
        code, _ = meal_qr.issue(USER, SECRET, now=1_800_000_000, personal=True)
        self.assertEqual(len(code), meal_qr.TOKEN_LENGTH)
        self.assertTrue(code.startswith("82") and code.isdigit())
        claim = meal_qr.verify(f"]Q1{code}\r\n", SECRET, now=1_800_000_010)
        self.assertEqual((claim.user_id, claim.pay_source), (USER, "personal"))
        self.assertEqual(claim.idempotency_key, f"meal-qr:{USER}:{claim.nonce}")

    def test_company_code_is_unchanged_and_the_source_is_signed(self):
        code, _ = meal_qr.issue(USER, SECRET, now=1_800_000_000)
        self.assertTrue(code.startswith("81"))
        self.assertEqual(meal_qr.verify(code, SECRET, now=1_800_000_010).pay_source, "company")
        # Flipping the version digit to switch who pays breaks the signature.
        with self.assertRaises(meal_qr.MealQrError):
            meal_qr.verify("82" + code[2:], SECRET, now=1_800_000_010)


class ConsumeMealSourceTests(unittest.TestCase):
    def _repo(self, links):
        repo = SimpleNamespace(client=SimpleNamespace())
        calls = []
        repo.client.rest_get = lambda table, params: links if table == "merchant_companies" else [{"name": "테스트회사"}]
        repo.client.rpc = lambda name, params: calls.append((name, params)) or {"id": "tx", "remaining": 2, "duplicate": False}
        return repo, calls

    def test_personal_source_uses_the_ordinary_voucher_rpc_without_touching_the_contract(self):
        repo, calls = self._repo([{"unit_price": 8000, "status": "active", "subsidy_enabled": False}])
        repo.client.rest_get = lambda table, params: self.fail("no contract lookup for a personal voucher")
        out = consume_meal(repo, employee(), MERCHANT, "key-12345678", pay_source="personal")
        self.assertEqual(calls, [("consume_voucher", {"p_user_id": USER, "p_merchant_id": "merchant-1", "p_idempotency_key": "key-12345678"})])
        self.assertEqual((out["pay_type"], out["remaining"]), ("voucher", 2))

    def test_default_source_keeps_ledger_and_subsidized_behaviour(self):
        repo, calls = self._repo([{"unit_price": 8000, "status": "active", "subsidy_enabled": False}])
        self.assertEqual(consume_meal(repo, employee(), MERCHANT, "key-12345678"), {"ledger_amount": 8000})
        self.assertEqual(calls, [])
        repo, calls = self._repo([{"unit_price": 8000, "status": "active", "subsidy_enabled": True}])
        out = consume_meal(repo, employee(), MERCHANT, "key-12345678", pay_source="company")
        self.assertEqual((calls[0][0], out["pay_type"]), ("consume_subsidized_voucher", "subsidized"))

    def test_personal_source_does_not_change_customers_or_admit_admins(self):
        repo, calls = self._repo([])
        customer = SimpleNamespace(id=USER, role="customer", status="active", company_id=None)
        self.assertEqual(consume_meal(repo, customer, MERCHANT, "key-12345678", pay_source="personal")["pay_type"], "voucher")
        admin = SimpleNamespace(id=USER, role="merchant_admin", status="active", company_id=None)
        with self.assertRaises(HTTPException) as caught:
            consume_meal(repo, admin, MERCHANT, "key-12345678", pay_source="personal")
        self.assertEqual(caught.exception.detail["code"], "ACCOUNT_TYPE_NOT_SUPPORTED")


@patch("app.routers.transactions.get_settings", return_value=SETTINGS)
@patch("app.routers.transactions.JoinRepository")
class ScanSourceTests(unittest.TestCase):
    def _repo(self, repo_class, *, vouchers=2):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id=USER, email=None)
        repo.get_profile.return_value = employee()

        def rest_get(table, params):
            if table == "merchants":
                return [MERCHANT]
            if table == "merchant_companies":
                return [{"unit_price": 8000, "status": "active", "subsidy_enabled": False}]
            if table == "vouchers":
                self.assertEqual((params["user_id"], params["merchant_id"], params["company_id"], params["status"]),
                                 (f"eq.{USER}", "eq.merchant-1", "is.null", "eq.unused"))
                return [{"id": f"v{i}"} for i in range(vouchers)]
            return [{"name": "테스트회사"}]

        repo.client.rest_get.side_effect = rest_get
        return repo

    def _limit(self, code="DAILY_LIMIT"):
        return HTTPException(status_code=400, detail={"code": code, "message": "오늘 식대 한도를 초과했어요"})

    def test_company_refusal_reports_the_personal_voucher_balance(self, repo_class, _settings):
        self._repo(repo_class, vouchers=2)
        for code in ("DAILY_LIMIT", "MONTHLY_LIMIT", "MEAL_LIMIT", "OUT_OF_WINDOW", "WEEKEND_BLOCKED", "NOT_AFFILIATED"):
            with patch("app.routers.transactions.pay", side_effect=self._limit(code)), self.assertRaises(HTTPException) as caught:
                scan(TransactionScanRequest(qr_data="QR-DONTO", idempotency_key="key-12345678"), "bearer")
            self.assertEqual(caught.exception.status_code, 400)
            self.assertEqual(caught.exception.detail["code"], code)
            self.assertEqual(caught.exception.detail["message"], "오늘 식대 한도를 초과했어요")
            self.assertEqual(caught.exception.detail["personal_voucher_balance"], 2)

    def test_other_errors_and_a_failed_balance_read_do_not_invent_an_offer(self, repo_class, _settings):
        repo = self._repo(repo_class)
        with patch("app.routers.transactions.pay", side_effect=self._limit("IDEMPOTENCY_CONFLICT")), self.assertRaises(HTTPException) as caught:
            scan(TransactionScanRequest(qr_data="QR-DONTO", idempotency_key="key-12345678"), "bearer")
        self.assertNotIn("personal_voucher_balance", caught.exception.detail)
        original = repo.client.rest_get.side_effect

        def failing(table, params):
            if table == "vouchers":
                raise SupabaseHttpError(500, "boom")
            return original(table, params)

        repo.client.rest_get.side_effect = failing
        with patch("app.routers.transactions.pay", side_effect=self._limit()), self.assertRaises(HTTPException) as caught:
            scan(TransactionScanRequest(qr_data="QR-DONTO", idempotency_key="key-12345678"), "bearer")
        self.assertEqual(caught.exception.detail["personal_voucher_balance"], 0)

    def test_personal_source_pays_with_the_voucher_and_never_calls_the_ledger(self, repo_class, _settings):
        repo = self._repo(repo_class)
        repo.client.rpc.return_value = {"id": "tx", "remaining": 1, "duplicate": False}
        with patch("app.routers.transactions.pay") as ledger:
            out = scan(TransactionScanRequest(qr_data="QR-DONTO", idempotency_key="key-12345678", pay_source="personal"), "bearer")
        ledger.assert_not_called()
        self.assertEqual(repo.client.rpc.call_args.args[0], "consume_voucher")
        self.assertEqual((out["pay_type"], out["remaining"]), ("voucher", 1))

    def test_personal_source_without_a_voucher_is_a_plain_no_voucher_error(self, repo_class, _settings):
        repo = self._repo(repo_class)
        repo.client.rpc.side_effect = SupabaseHttpError(400, "NO_VOUCHER")
        with self.assertRaises(HTTPException) as caught:
            scan(TransactionScanRequest(qr_data="QR-DONTO", idempotency_key="key-12345678", pay_source="personal"), "bearer")
        self.assertEqual((caught.exception.status_code, caught.exception.detail["code"]), (402, "NO_VOUCHER"))
        self.assertNotIn("personal_voucher_balance", caught.exception.detail)

    def test_unknown_source_is_rejected_by_the_schema(self, _repo_class, _settings):
        with self.assertRaises(ValueError):
            TransactionScanRequest(qr_data="QR-DONTO", idempotency_key="key-12345678", pay_source="company-card")


@patch("app.routers.transactions.get_settings", return_value=SETTINGS)
@patch("app.routers.transactions.JoinRepository")
class MemberQrSourceTests(unittest.TestCase):
    def test_employee_can_ask_for_a_personal_code_and_a_customer_cannot_change_source(self, repo_class, _settings):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id=USER, email=None)
        repo.get_profile.return_value = employee()
        data = member_qr(source="personal", token="bearer")["data"]
        self.assertEqual(data["pay_source"], "personal")
        self.assertEqual(meal_qr.verify(data["code"], SECRET).pay_source, "personal")
        self.assertEqual(member_qr(token="bearer")["data"]["pay_source"], "company")
        repo.get_profile.return_value = SimpleNamespace(id=USER, role="customer", status="active", company_id=None)
        data = member_qr(source="personal", token="bearer")["data"]
        self.assertEqual((data["pay_source"], data["code"][:2]), ("company", "81"))

    def test_counter_redeems_a_ledger_employees_personal_code(self, repo_class, _settings):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="admin", email=None)
        admin = SimpleNamespace(id="admin", role="merchant_admin", status="active", merchant_id="merchant-1")
        repo.get_profile.side_effect = lambda uid, email=None: admin if uid == "admin" else employee()
        repo.client.rest_get.return_value = [MERCHANT]
        repo.client.rpc.return_value = {"id": "tx-1", "remaining": 0, "duplicate": False, "total_amount": 8000}
        code, _ = meal_qr.issue(USER, SECRET, personal=True)
        out = redeem_member_qr(MemberQrRedeemRequest(code=code), "bearer")["data"]
        self.assertEqual(repo.client.rpc.call_args.args[0], "consume_voucher")
        self.assertEqual((out["pay_type"], out["remaining"], out["member_name"]), ("voucher", 0, "김직원"))


@patch("app.routers.voucher_products.get_settings", return_value=SETTINGS)
@patch("app.routers.voucher_products.JoinRepository")
class EmployeePurchaseTests(unittest.TestCase):
    PRODUCT = {"id": "product-1", "merchant_id": "merchant-1", "name": "1장 식권", "voucher_count": 1, "bonus_count": 0,
               "sale_price": 8000, "status": "active", "kiwoom_pay_method": "TOTAL", "is_event": False, "tax_type": "taxable"}

    def _repo(self, repo_class, *, subsidy):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id=USER, email=None)
        repo.get_profile.return_value = employee()

        def rest_get(table, params):
            if table == "merchants":
                return [{"id": "merchant-1", "name": "돈토식당", "status": "active"}]
            if table == "merchant_companies":
                return [{"company_id": "company-1", "unit_price": 8000, "subsidy_enabled": subsidy,
                         "company_subsidy_amount": 1000, "restaurant_subsidy_amount": 0, "status": "active"}]
            return [self.PRODUCT]

        repo.client.rest_get.side_effect = rest_get
        repo.client.rest_post.side_effect = lambda table, row: [{**row, "id": "order-db-id"}]
        return repo

    def test_ledger_employee_buys_an_ordinary_voucher_order_in_their_own_name(self, repo_class, _settings):
        repo = self._repo(repo_class, subsidy=False)
        data = purchase(VoucherPurchaseRequest(product_id="product-1"), "bearer")["data"]
        table, row = repo.client.rest_post.call_args.args
        self.assertEqual(table, "payment_orders")
        self.assertEqual((row["user_id"], row["pay_type"], row["amount"], row["status"]), (USER, "voucher", 8000, "ready"))
        # Nothing ties the order to the company: it is the employee's own purchase.
        self.assertNotIn("company_id", row)
        self.assertNotIn("company_subsidy_amount", row)
        self.assertEqual(data["amount"], 8000)

    def test_subsidized_employee_must_keep_using_the_subsidized_purchase(self, repo_class, _settings):
        repo = self._repo(repo_class, subsidy=True)
        with self.assertRaises(HTTPException) as caught:
            purchase(VoucherPurchaseRequest(product_id="product-1"), "bearer")
        self.assertEqual((caught.exception.status_code, caught.exception.detail["code"]), (409, "SUBSIDIZED_PURCHASE_REQUIRED"))
        repo.client.rest_post.assert_not_called()


class MigrationTests(unittest.TestCase):
    def test_0077_only_excludes_personal_voucher_meals_from_the_limit_sum(self):
        old = (MIGRATIONS / "0075_meal_pay_limits_under_lock.sql").read_text(encoding="utf-8")
        new = (MIGRATIONS / "0077_personal_vouchers_outside_company_limits.sql").read_text(encoding="utf-8")
        body = lambda sql: sql[sql.index("create or replace function public.process_meal_pay"):]
        removed = [line for line in body(old).splitlines() if line not in body(new).splitlines()]
        added = [line for line in body(new).splitlines() if line not in body(old).splitlines()]
        self.assertEqual(len(removed), 1)
        self.assertEqual(len(added), 2)
        self.assertIn("pay_type<>'voucher'", added[0])
        self.assertEqual(" ".join(added).replace(" and pay_type<>'voucher'", "").split(), removed[0].split())
