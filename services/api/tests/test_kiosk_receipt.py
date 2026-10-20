from __future__ import annotations

import io
import json
import ssl
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError

from fastapi import HTTPException

from app.repositories.supabase_http import SupabaseHttpError
from app.routers.transactions import redeem_kiosk_receipt
from app.schemas import KioskReceiptRedeemRequest
from app.services import kiosk_receipt

RECEIPT = "6ad6e86b3bea82fef79ff23b"
BASE = "https://api.tapandpick.com"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(result=None, *, raises=None, seen=None):
    def open_(req, timeout, context):
        if seen is not None:
            seen.append((req.full_url, timeout, context))
        if raises:
            raise raises
        return _Resp(json.dumps({"result": result}).encode())
    return open_


class KioskReceiptServiceTests(unittest.TestCase):
    def test_extracts_24_hex_receipt_from_scanner_input(self):
        self.assertEqual(kiosk_receipt.extract_receipt_id(RECEIPT), RECEIPT)
        self.assertEqual(kiosk_receipt.extract_receipt_id(f"]Q1{RECEIPT.upper()}\r\n"), RECEIPT)
        self.assertIsNone(kiosk_receipt.extract_receipt_id("QR-DONTO"))
        self.assertIsNone(kiosk_receipt.extract_receipt_id(RECEIPT + "ab"), "25+ hex is not a receipt")
        self.assertIsNone(kiosk_receipt.extract_receipt_id("81" + "0" * 79))

    def test_valid_receipt_uses_verified_tls_and_the_documented_path(self):
        seen = []
        out = kiosk_receipt.verify(RECEIPT, base_url=BASE + "/", opener=_opener(0, seen=seen))
        self.assertEqual(out.provider_result, 0)
        url, timeout, ctx = seen[0]
        self.assertEqual(url, f"{BASE}/payment/{RECEIPT}/verify")
        self.assertLessEqual(timeout, 5)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED, "certificate checks must never be disabled")
        self.assertTrue(ctx.check_hostname)

    def test_result_codes(self):
        with self.assertRaises(kiosk_receipt.KioskReceiptError) as nf:
            kiosk_receipt.verify(RECEIPT, base_url=BASE, opener=_opener(1000))
        self.assertEqual(nf.exception.code, "KIOSK_RECEIPT_NOT_FOUND")
        with self.assertRaises(kiosk_receipt.KioskReceiptError) as bad:
            kiosk_receipt.verify(RECEIPT, base_url=BASE, opener=_opener(1))
        self.assertEqual((bad.exception.code, bad.exception.provider_result), ("KIOSK_RECEIPT_INVALID", 1))
        for weird in (None, "0", True):
            with self.assertRaises(kiosk_receipt.KioskReceiptError) as e:
                kiosk_receipt.verify(RECEIPT, base_url=BASE, opener=_opener(weird))
            self.assertEqual(e.exception.code, "KIOSK_UNAVAILABLE")

    def test_tls_or_network_failure_fails_closed(self):
        cert = URLError(ssl.SSLCertVerificationError("certificate has expired"))
        with self.assertRaises(kiosk_receipt.KioskReceiptError) as e:
            kiosk_receipt.verify(RECEIPT, base_url=BASE, opener=_opener(raises=cert))
        self.assertEqual((e.exception.code, e.exception.status), ("KIOSK_UNAVAILABLE", 503))

    def test_not_configured(self):
        with self.assertRaises(kiosk_receipt.KioskReceiptError) as e:
            kiosk_receipt.verify(RECEIPT, base_url="", opener=_opener(0))
        self.assertEqual(e.exception.code, "KIOSK_NOT_CONFIGURED")


def _repo(repo_class, *, role="merchant_admin", used=False):
    repo = repo_class.return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id="admin", email="m@example.com")
    repo.get_profile.return_value = SimpleNamespace(id="admin", role=role, status="active", merchant_id="merchant-1")
    repo.client.rest_get.side_effect = [
        [{"id": "merchant-1", "name": "돈토식당", "status": "active"}],
        [{"redeemed_at": "2026-10-20T03:00:00Z", "merchant_id": "merchant-1"}] if used else [],
    ]
    repo.client.rest_post.return_value = [{"redeemed_at": "2026-10-20T04:00:00Z"}]
    return repo


@patch("app.routers.transactions.get_settings", return_value=SimpleNamespace(kiosk_api_base_url=BASE))
@patch("app.routers.transactions.JoinRepository")
class RedeemKioskReceiptTests(unittest.TestCase):
    def test_valid_receipt_is_recorded_once(self, repo_class, _settings):
        repo = _repo(repo_class)
        with patch("app.services.kiosk_receipt.urlopen", _opener(0)):
            out = redeem_kiosk_receipt(KioskReceiptRedeemRequest(code=RECEIPT + "\n"), "bearer")["data"]
        self.assertEqual((out["result"], out["kind"], out["receipt_id"]), ("success", "kiosk_receipt", RECEIPT))
        table, row = repo.client.rest_post.call_args.args
        self.assertEqual(table, "kiosk_receipt_redemptions")
        self.assertEqual(row, {"receipt_id": RECEIPT, "merchant_id": "merchant-1", "redeemed_by": "admin", "provider_result": 0})

    def test_already_used_is_refused_without_calling_the_kiosk(self, repo_class, _settings):
        repo = _repo(repo_class, used=True)
        with patch("app.services.kiosk_receipt.urlopen") as kiosk:
            with self.assertRaises(HTTPException) as e:
                redeem_kiosk_receipt(KioskReceiptRedeemRequest(code=RECEIPT), "bearer")
        self.assertEqual((e.exception.status_code, e.exception.detail["code"]), (409, "KIOSK_RECEIPT_USED"))
        kiosk.assert_not_called()
        repo.client.rest_post.assert_not_called()

    def test_concurrent_second_counter_hits_the_unique_constraint(self, repo_class, _settings):
        repo = _repo(repo_class)
        repo.client.rest_post.side_effect = SupabaseHttpError(409, '{"code":"23505","message":"duplicate key"}')
        with patch("app.services.kiosk_receipt.urlopen", _opener(0)):
            with self.assertRaises(HTTPException) as e:
                redeem_kiosk_receipt(KioskReceiptRedeemRequest(code=RECEIPT), "bearer")
        self.assertEqual(e.exception.detail["code"], "KIOSK_RECEIPT_USED")

    def test_invalid_receipt_is_not_recorded(self, repo_class, _settings):
        repo = _repo(repo_class)
        with patch("app.services.kiosk_receipt.urlopen", _opener(1000)):
            with self.assertRaises(HTTPException) as e:
                redeem_kiosk_receipt(KioskReceiptRedeemRequest(code=RECEIPT), "bearer")
        self.assertEqual(e.exception.detail["code"], "KIOSK_RECEIPT_NOT_FOUND")
        repo.client.rest_post.assert_not_called()

    def test_kiosk_down_or_bad_certificate_is_not_recorded(self, repo_class, _settings):
        repo = _repo(repo_class)
        with patch("app.services.kiosk_receipt.urlopen", _opener(raises=URLError("certificate has expired"))):
            with self.assertRaises(HTTPException) as e:
                redeem_kiosk_receipt(KioskReceiptRedeemRequest(code=RECEIPT), "bearer")
        self.assertEqual((e.exception.status_code, e.exception.detail["code"]), (503, "KIOSK_UNAVAILABLE"))
        repo.client.rest_post.assert_not_called()

    def test_only_merchant_admin(self, repo_class, _settings):
        repo = _repo(repo_class, role="customer")
        with self.assertRaises(HTTPException) as e:
            redeem_kiosk_receipt(KioskReceiptRedeemRequest(code=RECEIPT), "bearer")
        self.assertEqual(e.exception.status_code, 403)
        repo.client.rest_post.assert_not_called()

    def test_member_qr_is_not_a_kiosk_receipt(self, repo_class, _settings):
        _repo(repo_class)
        with self.assertRaises(HTTPException) as e:
            redeem_kiosk_receipt(KioskReceiptRedeemRequest(code="81" + "0" * 79), "bearer")
        self.assertEqual(e.exception.detail["code"], "INVALID_KIOSK_RECEIPT")


if __name__ == "__main__":
    unittest.main()
