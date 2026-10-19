from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.routers.transactions import member_qr, redeem_member_qr
from app.schemas import MemberQrRedeemRequest
from app.services import meal_qr

SECRET = "test-meal-qr-secret"
USER = "11111111-2222-4333-8444-555555555555"
NOW = 1_800_000_000


class MealQrTokenTests(unittest.TestCase):
    def test_issue_is_digits_only_fixed_length_and_round_trips(self):
        code, exp = meal_qr.issue(USER, SECRET, now=NOW)
        self.assertTrue(code.isdigit())
        self.assertEqual(len(code), meal_qr.TOKEN_LENGTH)
        self.assertEqual(exp, NOW + meal_qr.TTL_SECONDS)
        claim = meal_qr.verify(code, SECRET, now=NOW + 10)
        self.assertEqual(claim.user_id, USER)
        self.assertTrue(claim.idempotency_key.startswith(f"meal-qr:{USER}:"))

    def test_each_issue_has_a_new_nonce(self):
        a, _ = meal_qr.issue(USER, SECRET, now=NOW)
        b, _ = meal_qr.issue(USER, SECRET, now=NOW)
        self.assertNotEqual(meal_qr.verify(a, SECRET, now=NOW).nonce, meal_qr.verify(b, SECRET, now=NOW).nonce)

    def test_scanner_suffix_and_prefix_are_tolerated(self):
        code, _ = meal_qr.issue(USER, SECRET, now=NOW)
        for raw in (code + "\r\n", "]Q1" + code, f"  {code}\t"):
            self.assertEqual(meal_qr.verify(raw, SECRET, now=NOW).user_id, USER)

    def test_tampered_or_wrong_secret_is_rejected(self):
        code, _ = meal_qr.issue(USER, SECRET, now=NOW)
        tampered = code[:10] + ("1" if code[10] != "1" else "2") + code[11:]
        for raw, secret in ((tampered, SECRET), (code, "other-secret")):
            with self.assertRaises(meal_qr.MealQrError) as caught:
                meal_qr.verify(raw, secret, now=NOW)
            self.assertEqual(caught.exception.code, "INVALID_MEAL_QR")

    def test_expired_code_is_rejected(self):
        code, _ = meal_qr.issue(USER, SECRET, now=NOW)
        with self.assertRaises(meal_qr.MealQrError) as caught:
            meal_qr.verify(code, SECRET, now=NOW + meal_qr.TTL_SECONDS + meal_qr.CLOCK_SKEW_SECONDS + 1)
        self.assertEqual(caught.exception.code, "MEAL_QR_EXPIRED")

    def test_store_qr_and_garbage_are_not_member_codes(self):
        for raw in ("QR-DONTO", "https://greeneatgo.vercel.app/q/abc", "", "8" * 40):
            with self.assertRaises(meal_qr.MealQrError):
                meal_qr.verify(raw, SECRET, now=NOW)


def _repo(repo_class, *, role="merchant_admin", member_role="customer", merchant_active=True):
    repo = repo_class.return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id="admin", email="m@example.com")
    admin = SimpleNamespace(id="admin", role=role, status="active", merchant_id="merchant-1")
    member = SimpleNamespace(id=USER, role=member_role, status="active", company_id="company-1" if member_role == "employee" else None, display_name="김구매")
    repo.get_profile.side_effect = lambda uid, email=None: admin if uid == "admin" else member
    repo.client.rest_get.return_value = [{"id": "merchant-1", "name": "돈토식당", "qr_token": "QR-DONTO", "status": "active"}] if merchant_active else []
    return repo


@patch("app.routers.transactions.get_settings", return_value=SimpleNamespace(meal_qr_secret=SECRET, pilot_merchant_id=None))
@patch("app.routers.transactions.JoinRepository")
class RedeemMemberQrTests(unittest.TestCase):
    def test_merchant_redeems_one_voucher_with_nonce_bound_idempotency(self, repo_class, _settings):
        repo = _repo(repo_class)
        repo.client.rpc.return_value = {"id": "tx-1", "remaining": 4, "duplicate": False, "total_amount": 7000, "created_at": "2026-10-19T03:00:00Z"}
        code, _ = meal_qr.issue(USER, SECRET)
        out = redeem_member_qr(MemberQrRedeemRequest(code=code), "bearer")["data"]
        name, args = repo.client.rpc.call_args.args
        self.assertEqual(name, "consume_voucher")
        self.assertEqual(args["p_user_id"], USER)
        self.assertEqual(args["p_merchant_id"], "merchant-1")
        self.assertEqual(args["p_idempotency_key"], meal_qr.verify(code, SECRET).idempotency_key)
        self.assertEqual((out["remaining"], out["member_name"], out["amount"], out["duplicate"]), (4, "김구매", 7000, False))

    def test_same_code_twice_reuses_the_key_so_the_rpc_dedupes(self, repo_class, _settings):
        repo = _repo(repo_class)
        repo.client.rpc.return_value = {"id": "tx-1", "remaining": 4, "duplicate": True}
        code, _ = meal_qr.issue(USER, SECRET)
        redeem_member_qr(MemberQrRedeemRequest(code=code), "bearer")
        redeem_member_qr(MemberQrRedeemRequest(code=code + "\n"), "bearer")
        keys = {c.args[1]["p_idempotency_key"] for c in repo.client.rpc.call_args_list}
        self.assertEqual(len(keys), 1)

    def test_only_merchant_admin_can_redeem(self, repo_class, _settings):
        repo = _repo(repo_class, role="customer")
        code, _ = meal_qr.issue(USER, SECRET)
        with self.assertRaises(HTTPException) as caught:
            redeem_member_qr(MemberQrRedeemRequest(code=code), "bearer")
        self.assertEqual(caught.exception.status_code, 403)
        repo.client.rpc.assert_not_called()

    def test_forged_code_never_reaches_the_rpc(self, repo_class, _settings):
        repo = _repo(repo_class)
        code, _ = meal_qr.issue(USER, "attacker-secret")
        with self.assertRaises(HTTPException) as caught:
            redeem_member_qr(MemberQrRedeemRequest(code=code), "bearer")
        self.assertEqual(caught.exception.detail["code"], "INVALID_MEAL_QR")
        repo.client.rpc.assert_not_called()

    def test_ledger_employee_is_refused_without_charging(self, repo_class, _settings):
        repo = _repo(repo_class, member_role="employee")
        repo.client.rest_get.side_effect = [
            [{"id": "merchant-1", "name": "돈토식당", "qr_token": "QR-DONTO", "status": "active"}],
            [{"unit_price": 8300, "status": "active", "subsidy_enabled": False}],
        ]
        code, _ = meal_qr.issue(USER, SECRET)
        with self.assertRaises(HTTPException) as caught:
            redeem_member_qr(MemberQrRedeemRequest(code=code), "bearer")
        self.assertEqual(caught.exception.detail["code"], "LEDGER_NOT_SUPPORTED")
        repo.client.rpc.assert_not_called()

    def test_subsidized_employee_uses_subsidized_rpc(self, repo_class, _settings):
        repo = _repo(repo_class, member_role="employee")
        repo.client.rest_get.side_effect = [
            [{"id": "merchant-1", "name": "돈토식당", "qr_token": "QR-DONTO", "status": "active"}],
            [{"unit_price": 8300, "status": "active", "subsidy_enabled": True}],
            [{"name": "테스트회사"}],
        ]
        repo.client.rpc.return_value = {"id": "tx-2", "remaining": 9, "duplicate": False}
        code, _ = meal_qr.issue(USER, SECRET)
        out = redeem_member_qr(MemberQrRedeemRequest(code=code), "bearer")["data"]
        self.assertEqual(repo.client.rpc.call_args.args[0], "consume_subsidized_voucher")
        self.assertEqual(out["pay_type"], "subsidized")


@patch("app.routers.transactions.get_settings", return_value=SimpleNamespace(meal_qr_secret=SECRET))
@patch("app.routers.transactions.JoinRepository")
class IssueMemberQrTests(unittest.TestCase):
    def test_buyer_gets_a_verifiable_code_without_secret_material(self, repo_class, _settings):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id=USER, email="b@example.com")
        repo.get_profile.return_value = SimpleNamespace(id=USER, role="customer", status="active")
        data = member_qr("bearer")["data"]
        self.assertEqual(meal_qr.verify(data["code"], SECRET).user_id, USER)
        self.assertEqual(data["ttl"], meal_qr.TTL_SECONDS)
        self.assertNotIn(SECRET, repr(data))

    def test_admin_accounts_cannot_issue(self, repo_class, _settings):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="a", email="a@example.com")
        repo.get_profile.return_value = SimpleNamespace(id="a", role="merchant_admin", status="active")
        with self.assertRaises(HTTPException) as caught:
            member_qr("bearer")
        self.assertEqual(caught.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
