import unittest

from pydantic import ValidationError

from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import AuthUser, SupabaseHttpClient
from app.schemas import JoinRequest


class FakeJoinClient(SupabaseHttpClient):
    def __init__(self):
        self.app_user_patch = None
        self.rpc_calls = []

    def rest_get(self, table, params, **_kwargs):
        if table == "app_users":
            return [{
                "id": "customer-1",
                "email": "customer@example.com",
                "display_name": "기존 고객",
                "phone": "01012345678",
                "company_id": None,
                "merchant_id": None,
                "group_id": None,
                "role": "customer",
                "status": "active",
            }]
        if table == "company_invite_codes":
            if params.get("select") == "used_count":
                return [{"used_count": 0}]
            return [{
                "code": "PILOT",
                "company_id": "company-1",
                "default_group_id": "group-1",
                "expires_at": None,
                "max_uses": 10,
                "used_count": 0,
                "is_active": True,
            }]
        return []

    def rest_patch(self, table, params, values):
        if table == "app_users":
            self.app_user_patch = values
        return [values]

    def rest_post(self, table, rows, **_kwargs):
        return [rows]

    def rpc(self, function_name, payload):
        self.rpc_calls.append((function_name, payload))
        return {"status": "active"}


class JoinRequestSchemaTests(unittest.TestCase):
    def test_optional_employee_fields_are_trimmed_and_old_clients_still_validate(self):
        legacy = JoinRequest(
            invite_code=" PILOT ", display_name=" 기존 고객 ", phone="010-1234-5678"
        )
        self.assertIsNone(legacy.department)
        self.assertIsNone(legacy.employee_no)
        current = JoinRequest(
            invite_code=" PILOT ",
            display_name=" 기존 고객 ",
            phone="010-1234-5678",
            department="  플랫폼팀  ",
            employee_no="  E-100  ",
        )
        self.assertEqual(current.department, "플랫폼팀")
        self.assertEqual(current.employee_no, "E-100")

    def test_employee_field_limits_blank_values_and_extra_fields_are_rejected(self):
        invalid_payloads = (
            {"department": "   "},
            {"department": "가" * 121},
            {"employee_no": " "},
            {"employee_no": "1" * 41},
            {"unexpected": "blocked"},
        )
        for extra in invalid_payloads:
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                JoinRequest(
                    invite_code="PILOT",
                    display_name="기존 고객",
                    phone="01012345678",
                    **extra,
                )


class JoinRepositoryCustomerConversionTests(unittest.TestCase):
    def test_active_customer_is_persisted_pending_with_employee_details_without_rpc(self):
        client = FakeJoinClient()
        repository = JoinRepository(client)
        repository.auth_user_from_token = lambda access_token: AuthUser(
            id="customer-1", email="customer@example.com", metadata={"phone": "01012345678"}
        )

        result = repository.request_join(
            access_token="customer-token",
            invite_code="PILOT",
            display_name="위조된 이름",
            phone="01099999999",
            department="플랫폼팀",
            employee_no="E-100",
        )

        self.assertEqual(result["status"], "pending")
        self.assertIsNotNone(client.app_user_patch)
        assert client.app_user_patch is not None
        self.assertEqual(client.app_user_patch["department"], "플랫폼팀")
        self.assertEqual(client.app_user_patch["employee_no"], "E-100")
        self.assertEqual(client.app_user_patch["display_name"], "기존 고객")
        self.assertEqual(client.app_user_patch["phone"], "01012345678")
        self.assertEqual(client.app_user_patch["role"], "employee")
        self.assertEqual(client.app_user_patch["status"], "pending")
        self.assertEqual(client.rpc_calls, [])


if __name__ == "__main__":
    unittest.main()
