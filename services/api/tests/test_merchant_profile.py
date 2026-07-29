import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError
from fastapi import HTTPException

from app.repositories.supabase_http import SupabaseHttpError
from app.routers.merchant_admin import merchant_qr, update_merchant_profile
from app.schemas import MerchantProfileUpdateRequest
from app.services.join_flow import UserProfile


class MerchantProfileTests(unittest.TestCase):
    def test_merchant_name_is_trimmed_and_blank_name_is_rejected(self):
        self.assertEqual(MerchantProfileUpdateRequest(name="  돈토  ").name, "돈토")
        with self.assertRaises(ValidationError):
            MerchantProfileUpdateRequest(name="   ")
        with self.assertRaises(ValidationError):
            MerchantProfileUpdateRequest()

    def test_supplier_profile_trims_optional_fields_and_validates_email(self):
        payload = MerchantProfileUpdateRequest(
            representative_name="  이용욱  ", business_type=" 음식점업 ",
            business_item=" 한식 뷔페 ", tax_invoice_email=" tax@greeneat.example ",
            owner_phone=" 010-1234-5678 ",
        )
        self.assertEqual(payload.representative_name, "이용욱")
        self.assertEqual(payload.business_type, "음식점업")
        self.assertEqual(payload.business_item, "한식 뷔페")
        self.assertEqual(payload.owner_phone, "010-1234-5678")
        self.assertEqual(payload.tax_invoice_email, "tax@greeneat.example")
        with self.assertRaises(ValidationError):
            MerchantProfileUpdateRequest(tax_invoice_email="not-email")

    def test_deposit_information_is_optional_trimmed_and_bounded(self):
        payload = MerchantProfileUpdateRequest(
            bank_name="  그린은행  ", account_number="   ", account_holder="  이용욱  ",
        )
        self.assertEqual(payload.bank_name, "그린은행")
        self.assertIsNone(payload.account_number)
        self.assertEqual(payload.account_holder, "이용욱")
        with self.assertRaises(ValidationError):
            MerchantProfileUpdateRequest(bank_name="은" * 81)
        with self.assertRaises(ValidationError):
            MerchantProfileUpdateRequest(account_number="1" * 81)
        with self.assertRaises(ValidationError):
            MerchantProfileUpdateRequest(account_holder="주" * 81)

    @patch("app.routers.merchant_admin.JoinRepository")
    def test_merchant_admin_updates_only_linked_merchant_name(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(
            id="admin-1", email="owner@example.com"
        )
        repo.get_profile.return_value = UserProfile(
            id="admin-1", email="owner@example.com", display_name="관리자",
            merchant_id="merchant-1", role="merchant_admin", status="active",
        )
        repo.client.rest_patch.return_value = [{"id": "merchant-1", "name": "돈토"}]

        result = update_merchant_profile(
            MerchantProfileUpdateRequest(name="돈토"), "token"
        )

        repo.client.rest_patch.assert_called_once_with(
            "merchants", {"id": "eq.merchant-1"}, {"name": "돈토"}
        )
        self.assertEqual(result["data"]["name"], "돈토")

    @patch("app.routers.merchant_admin.JoinRepository")
    def test_merchant_admin_updates_supplier_profile_fields(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(
            id="admin-1", email="owner@example.com"
        )
        repo.get_profile.return_value = UserProfile(
            id="admin-1", email="owner@example.com", display_name="관리자",
            merchant_id="merchant-1", role="merchant_admin", status="active",
        )
        expected = {
            "name": "그린잇 식당", "biz_reg_no": "123-45-67890",
            "representative_name": "이용욱", "address": "서울특별시 중구",
            "business_type": "음식점업", "business_item": "한식 뷔페",
            "owner_phone": "010-1234-5678",
            "tax_invoice_email": "tax@greeneat.example",
            "bank_name": "그린은행", "account_number": "123-456-7890",
            "account_holder": "그린잇 식당",
        }
        repo.client.rest_patch.return_value = [{"id": "merchant-1", **expected}]

        result = update_merchant_profile(MerchantProfileUpdateRequest(**expected), "token")

        repo.client.rest_patch.assert_called_once_with(
            "merchants", {"id": "eq.merchant-1"}, expected
        )
        self.assertEqual(result["data"]["tax_invoice_email"], "tax@greeneat.example")

    @patch("app.routers.merchant_admin.JoinRepository")
    def test_qr_profile_keeps_existing_fields_and_marks_0050_required(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-1", email="owner@example.com")
        repo.get_profile.return_value = UserProfile(
            id="admin-1", email="owner@example.com", display_name="관리자",
            merchant_id="merchant-1", role="merchant_admin", status="active",
        )
        repo.client.rest_get.side_effect = [
            SupabaseHttpError(400, 'PGRST204 bank_name does not exist'),
            [{"id": "merchant-1", "name": "식당", "representative_name": "이용욱"}],
        ]

        result = merchant_qr("token")

        merchant = result["data"]["merchant"]
        self.assertEqual(merchant["representative_name"], "이용욱")
        self.assertIsNone(merchant["bank_name"])
        self.assertIsNone(merchant["account_number"])
        self.assertIsNone(merchant["account_holder"])
        self.assertTrue(result["data"]["migration_required"])
        fallback_select = repo.client.rest_get.call_args_list[1].args[1]["select"]
        self.assertIn("representative_name", fallback_select)
        self.assertNotIn("bank_name", fallback_select)

    @patch("app.routers.merchant_admin.JoinRepository")
    def test_deposit_patch_reports_0050_migration(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-1", email="owner@example.com")
        repo.get_profile.return_value = UserProfile(
            id="admin-1", email="owner@example.com", display_name="관리자",
            merchant_id="merchant-1", role="merchant_admin", status="active",
        )
        repo.client.rest_patch.side_effect = SupabaseHttpError(400, 'PGRST204 bank_name does not exist')

        with self.assertRaises(HTTPException) as raised:
            update_merchant_profile(MerchantProfileUpdateRequest(bank_name="그린은행"), "token")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail["code"], "MIGRATION_REQUIRED")
        self.assertIn("0050_merchant_deposit_information.sql", raised.exception.detail["message"])

    @patch("app.routers.merchant_admin.JoinRepository")
    def test_company_admin_cannot_update_merchant_name(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(
            id="company-admin-1", email="company@example.com"
        )
        repo.get_profile.return_value = UserProfile(
            id="company-admin-1", email="company@example.com", display_name="업체 관리자",
            company_id="company-1", role="company_admin", status="active",
        )

        with self.assertRaises(HTTPException) as raised:
            update_merchant_profile(MerchantProfileUpdateRequest(name="잘못된 변경"), "token")

        self.assertEqual(raised.exception.status_code, 403)
        repo.client.rest_patch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
