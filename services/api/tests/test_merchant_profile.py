import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError
from fastapi import HTTPException

from app.routers.merchant_admin import update_merchant_profile
from app.schemas import MerchantProfileUpdateRequest
from app.services.join_flow import UserProfile


class MerchantProfileTests(unittest.TestCase):
    def test_merchant_name_is_trimmed_and_blank_name_is_rejected(self):
        self.assertEqual(MerchantProfileUpdateRequest(name="  돈토  ").name, "돈토")
        with self.assertRaises(ValidationError):
            MerchantProfileUpdateRequest(name="   ")

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
