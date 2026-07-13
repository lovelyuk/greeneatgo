import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.schemas import MerchantCompanyCreateAndLinkRequest
from app.services.company_invites import send_company_invitation


class _Settings:
    resend_api_key = "server-secret"
    invite_email_from = "GreenEatGo <invite@example.com>"
    admin_app_url = "https://admin.example.com"


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return b'{"id":"email_123"}'


class CompanyInvitationTests(unittest.TestCase):
    def test_contact_email_is_required_and_phone_optional(self):
        with self.assertRaises(ValidationError):
            MerchantCompanyCreateAndLinkRequest.model_validate({"name": "Acme"})
        request = MerchantCompanyCreateAndLinkRequest(name="Acme", contact_email="OWNER@EXAMPLE.COM")
        self.assertIsNone(request.contact_phone)

    @patch("app.services.company_invites.get_settings", return_value=_Settings())
    @patch("app.services.company_invites.urlopen", return_value=_Response())
    def test_resend_request_is_server_side_and_contains_invite_link(self, urlopen, _settings):
        result = send_company_invitation(email="owner@example.com", company_name="Acme", token="secret-token")
        self.assertEqual(result.status, "sent")
        self.assertEqual(result.message_id, "email_123")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer server-secret")
        body = json.loads(request.data)
        self.assertEqual(body["to"], ["owner@example.com"])
        self.assertIn("https://admin.example.com/?invite=secret-token", body["html"])

    @patch("app.services.company_invites.get_settings")
    def test_missing_resend_key_returns_failure_instead_of_raising(self, settings):
        settings.return_value = type("S", (), {"resend_api_key": ""})()
        result = send_company_invitation(email="owner@example.com", company_name="Acme", token="token")
        self.assertEqual(result.status, "failed")
        self.assertIn("not configured", result.error or "")


if __name__ == "__main__":
    unittest.main()
