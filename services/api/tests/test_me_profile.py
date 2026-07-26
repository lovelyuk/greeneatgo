import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from app.routers.me import me, update_admin_name, update_company_profile
from app.schemas import CompanyBusinessProfileUpdateRequest, ProfileNameUpdateRequest
from app.services.join_flow import UserProfile


class AdminProfileNameTests(unittest.TestCase):
    def test_company_profile_trims_fields_and_rejects_invalid_email(self):
        payload = CompanyBusinessProfileUpdateRequest(
            name="  가온테크  ", biz_reg_no=" 214-86-12345 ",
            tax_invoice_email=" tax@gaon.example ",
        )
        self.assertEqual(payload.name, "가온테크")
        self.assertEqual(payload.biz_reg_no, "214-86-12345")
        self.assertEqual(payload.tax_invoice_email, "tax@gaon.example")
        with self.assertRaises(ValidationError):
            CompanyBusinessProfileUpdateRequest(
                name="가온테크", biz_reg_no="214-86-12345", tax_invoice_email="not-email"
            )

    @patch("app.routers.me.JoinRepository")
    def test_company_admin_updates_only_own_company_profile(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-1", email="admin@example.com")
        repo.get_profile.return_value = UserProfile(
            id="admin-1", email="admin@example.com", display_name="관리자",
            company_id="company-1", role="company_admin", status="active",
        )
        company = {
            "id": "company-1", "name": "가온테크", "biz_reg_no": "214-86-12345",
            "representative_name": "김가온", "tax_invoice_email": "tax@gaon.example",
        }
        repo.client.rest_patch.return_value = [company]
        repo.client.rest_get.return_value = [company]
        payload = CompanyBusinessProfileUpdateRequest(
            name="가온테크", biz_reg_no="214-86-12345",
            representative_name="김가온", tax_invoice_email="tax@gaon.example",
        )

        result = update_company_profile(payload, "token")

        filters = repo.client.rest_patch.call_args.args[1]
        self.assertEqual(filters, {"id": "eq.company-1"})
        self.assertEqual(result["data"]["company"]["representative_name"], "김가온")

    @patch("app.routers.me.JoinRepository")
    def test_me_includes_profile_phone(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(
            id="customer-1", email="customer@example.com"
        )
        repo.get_profile.return_value = UserProfile(
            id="customer-1", email="customer@example.com", display_name="고객",
            phone="01012345678", role="merchant_admin", status="active",
        )

        result = me("token")

        self.assertEqual(result["data"]["phone"], "01012345678")

    def test_name_is_trimmed_and_blank_name_is_rejected(self):
        self.assertEqual(ProfileNameUpdateRequest(display_name="  김관리  ").display_name, "김관리")
        with self.assertRaises(ValidationError):
            ProfileNameUpdateRequest(display_name="   ")

    @patch("app.routers.me.JoinRepository")
    def test_company_admin_can_update_own_name(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-1", email="admin@example.com")
        repo.get_profile.return_value = UserProfile(
            id="admin-1", email="admin@example.com", display_name="기존 이름",
            company_id="company-1", role="company_admin", status="active",
        )
        repo.client.rest_patch.return_value = [{"display_name": "새 이름"}]

        result = update_admin_name(ProfileNameUpdateRequest(display_name="새 이름"), "token")

        repo.client.rest_patch.assert_called_once_with(
            "app_users", {"id": "eq.admin-1"}, {"display_name": "새 이름"}
        )
        self.assertEqual(result["data"]["display_name"], "새 이름")

    @patch("app.routers.me.JoinRepository")
    def test_merchant_admin_can_update_own_name(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-2", email="owner@example.com")
        repo.get_profile.return_value = UserProfile(
            id="admin-2", email="owner@example.com", display_name="식당 관리자",
            merchant_id="merchant-1", role="merchant_admin", status="active",
        )
        repo.client.rest_patch.return_value = [{"display_name": "돈토 사장님"}]

        result = update_admin_name(ProfileNameUpdateRequest(display_name="돈토 사장님"), "token")

        self.assertEqual(result["data"]["display_name"], "돈토 사장님")

    @patch("app.routers.me.JoinRepository")
    def test_employee_can_update_only_profile_resolved_from_token(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="employee-1", email="staff@example.com")
        repo.get_profile.return_value = UserProfile(
            id="employee-1", email="staff@example.com", display_name="직원",
            company_id="company-1", role="employee", status="active",
        )
        repo.client.rest_patch.return_value = [{"display_name": "바꿀 이름"}]

        update_admin_name(ProfileNameUpdateRequest(display_name="바꿀 이름"), "token")

        repo.client.rest_patch.assert_called_once_with(
            "app_users", {"id": "eq.employee-1"}, {"display_name": "바꿀 이름"}
        )

    @patch("app.routers.me.JoinRepository")
    def test_customer_can_update_own_name(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="customer-1", email="customer@example.com")
        repo.get_profile.return_value = UserProfile(
            id="customer-1", email="customer@example.com", display_name="고객",
            role="customer", status="active",
        )
        repo.client.rest_patch.return_value = [{"display_name": "새 고객 이름"}]

        update_admin_name(ProfileNameUpdateRequest(display_name="새 고객 이름"), "token")

        repo.client.rest_patch.assert_called_once_with(
            "app_users", {"id": "eq.customer-1"}, {"display_name": "새 고객 이름"}
        )


if __name__ == "__main__":
    unittest.main()
