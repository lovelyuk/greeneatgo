import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from app.routers.consumer import register_consumer
from app.schemas import ConsumerRegisterRequest
from app.services.join_flow import UserProfile


class ConsumerRegisterTests(unittest.TestCase):
    def test_phone_is_normalized_and_invalid_phone_is_rejected(self):
        payload = ConsumerRegisterRequest(
            display_name="  일반 고객  ", phone=" 010-1234 5678 "
        )
        self.assertEqual(payload.display_name, "일반 고객")
        self.assertEqual(payload.phone, "01012345678")

        with self.assertRaises(ValidationError):
            ConsumerRegisterRequest(display_name="고객")  # type: ignore[call-arg]
        for phone in ("", "0101234567", "01112345678", "010-1234-abcd"):
            with self.subTest(phone=phone), self.assertRaises(ValidationError):
                ConsumerRegisterRequest(display_name="고객", phone=phone)

    @patch("app.routers.consumer.JoinRepository")
    def test_new_customer_insert_persists_phone(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(
            id="customer-1", email="customer@example.com"
        )
        repo.get_profile.return_value = None
        repo.client.rest_post.return_value = [
            {"role": "customer", "status": "active"}
        ]

        register_consumer(
            ConsumerRegisterRequest(display_name="고객", phone="010-1234-5678"),
            "token",
        )

        repo.client.rest_post.assert_called_once_with(
            "app_users",
            {
                "id": "customer-1",
                "display_name": "고객",
                "phone": "01012345678",
                "role": "customer",
                "status": "active",
                "company_id": None,
                "group_id": None,
            },
        )

    @patch("app.routers.consumer.JoinRepository")
    def test_rejected_employee_patch_persists_phone(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(
            id="employee-1", email="employee@example.com"
        )
        repo.get_profile.return_value = UserProfile(
            id="employee-1",
            email="employee@example.com",
            display_name="기존 직원",
            phone="01000000000",
            role="employee",
            status="rejected",
        )
        repo.client.rest_patch.return_value = [
            {"role": "customer", "status": "active"}
        ]

        register_consumer(
            ConsumerRegisterRequest(display_name="새 고객", phone="010 9876 5432"),
            "token",
        )

        patch_body = repo.client.rest_patch.call_args.args[2]
        self.assertEqual(patch_body["phone"], "01098765432")
        self.assertEqual(patch_body["display_name"], "새 고객")
        self.assertEqual(patch_body["role"], "customer")

    @patch("app.routers.consumer.JoinRepository")
    def test_active_customer_registration_remains_idempotent(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(
            id="customer-1", email="customer@example.com"
        )
        repo.get_profile.return_value = UserProfile(
            id="customer-1",
            email="customer@example.com",
            display_name="고객",
            role="customer",
            status="active",
        )

        result = register_consumer(
            ConsumerRegisterRequest(display_name="고객", phone="01012345678"),
            "token",
        )

        self.assertTrue(result["ok"])
        repo.client.rest_post.assert_not_called()
        repo.client.rest_patch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
