import base64
import json
import unittest
from unittest.mock import ANY, Mock, patch
from uuid import UUID

from firebase_admin import auth as firebase_auth
from firebase_admin import exceptions as firebase_exceptions

from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import AuthUser, SupabaseHttpError
from app.schemas import JoinRequest
from app.services.firebase_auth import firebase_uid_to_internal_uuid
from app.services.join_flow import InviteCode


def _token(issuer: str) -> str:
    def encode(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{encode({'alg': 'none'})}.{encode({'iss': issuer})}.signature"


class DualAuthTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.repository = JoinRepository(self.client)
        self.firebase_token = _token("https://securetoken.google.com/greeneatgo")

    @patch("app.services.firebase_auth.firebase_auth.verify_id_token")
    @patch("app.services.firebase_auth._firebase_app", return_value=object())
    def test_valid_firebase_token_builds_internal_auth_user(self, firebase_app, verify):
        verify.return_value = {
            "uid": "firebase-random-uid",
            "email": " person@example.com ",
            "email_verified": True,
            "phone_number": "+82 10-1234-5678",
            "name": "Person",
            "admin": True,
        }

        user = self.repository.auth_user_from_token(self.firebase_token)

        self.assertEqual(user.id, firebase_uid_to_internal_uuid("firebase-random-uid"))
        self.assertEqual(user.email, "person@example.com")
        self.assertEqual(user.metadata["phone_number"], "+82 10-1234-5678")
        self.assertNotIn("admin", user.metadata)
        verify.assert_called_once_with(
            ANY, app=firebase_app.return_value, check_revoked=True
        )
        self.client.auth_get_user.assert_not_called()

    @patch("app.services.firebase_auth.firebase_auth.verify_id_token")
    @patch("app.services.firebase_auth._firebase_app", return_value=object())
    def test_invalid_firebase_token_does_not_fallback(self, _app, verify):
        verify.side_effect = firebase_auth.InvalidIdTokenError("invalid secret")

        with self.assertRaises(SupabaseHttpError) as raised:
            self.repository.auth_user_from_token(self.firebase_token)

        self.assertEqual(raised.exception.status, 401)
        self.assertNotIn("secret", raised.exception.body)
        self.client.auth_get_user.assert_not_called()

    def test_revoked_and_disabled_firebase_tokens_are_unauthorized_without_fallback(self):
        for error in (
            firebase_auth.ExpiredIdTokenError("expired secret", RuntimeError()),
            firebase_auth.RevokedIdTokenError("revoked secret"),
            firebase_auth.UserDisabledError("disabled secret"),
        ):
            with self.subTest(error=type(error).__name__), patch(
                "app.services.firebase_auth._firebase_app", return_value=object()
            ), patch(
                "app.services.firebase_auth.firebase_auth.verify_id_token",
                side_effect=error,
            ):
                with self.assertRaises(SupabaseHttpError) as raised:
                    self.repository.auth_user_from_token(self.firebase_token)
                self.assertEqual(raised.exception.status, 401)
                self.assertNotIn("secret", raised.exception.body)
                self.client.auth_get_user.assert_not_called()

    def test_firebase_app_configuration_failure_is_503_without_fallback(self):
        with patch(
            "app.services.firebase_auth._firebase_app",
            side_effect=RuntimeError("private key secret"),
        ), patch("app.services.firebase_auth.firebase_auth.verify_id_token") as verify:
            with self.assertRaises(SupabaseHttpError) as raised:
                self.repository.auth_user_from_token(self.firebase_token)
        self.assertEqual(raised.exception.status, 503)
        self.assertNotIn("secret", raised.exception.body)
        verify.assert_not_called()
        self.client.auth_get_user.assert_not_called()

    def test_firebase_verifier_operational_failures_are_503_without_fallback(self):
        failures = (
            firebase_auth.CertificateFetchError("certificate secret", RuntimeError()),
            firebase_exceptions.UnavailableError("network secret"),
            firebase_exceptions.InternalError("internal secret"),
        )
        for error in failures:
            with self.subTest(error=type(error).__name__), patch(
                "app.services.firebase_auth._firebase_app", return_value=object()
            ), patch(
                "app.services.firebase_auth.firebase_auth.verify_id_token",
                side_effect=error,
            ):
                with self.assertRaises(SupabaseHttpError) as raised:
                    self.repository.auth_user_from_token(self.firebase_token)
                self.assertEqual(raised.exception.status, 503)
                self.assertNotIn("secret", raised.exception.body)
                self.client.auth_get_user.assert_not_called()

    @patch("app.services.firebase_auth.firebase_auth.verify_id_token")
    @patch("app.services.firebase_auth._firebase_app", return_value=object())
    def test_unverified_firebase_email_does_not_fallback(self, _app, verify):
        verify.return_value = {
            "uid": "firebase-random-uid",
            "email": "person@example.com",
            "email_verified": False,
        }
        with self.assertRaises(SupabaseHttpError) as raised:
            self.repository.auth_user_from_token(self.firebase_token)
        self.assertEqual(raised.exception.status, 401)
        self.client.auth_get_user.assert_not_called()

    @patch("app.services.firebase_auth.firebase_auth.verify_id_token")
    @patch("app.services.firebase_auth._firebase_app", return_value=object())
    def test_missing_or_blank_firebase_email_does_not_fallback(self, _app, verify):
        for email in (None, "   "):
            with self.subTest(email=email):
                verify.return_value = {
                    "uid": "firebase-random-uid",
                    "email_verified": True,
                    **({"email": email} if email is not None else {}),
                }
                with self.assertRaises(SupabaseHttpError) as raised:
                    self.repository.auth_user_from_token(self.firebase_token)
                self.assertEqual(raised.exception.status, 401)
        self.client.auth_get_user.assert_not_called()

    def test_non_firebase_token_uses_supabase(self):
        expected = AuthUser(
            id="8c966c67-1644-4f12-bb78-d7a14572d643", email="old@example.com"
        )
        self.client.auth_get_user.return_value = expected
        token = _token("https://project.supabase.co/auth/v1")

        self.assertIs(self.repository.auth_user_from_token(token), expected)
        self.client.auth_get_user.assert_called_once_with(token)

    def test_malformed_token_still_uses_supabase_verifier(self):
        expected = AuthUser(
            id="8c966c67-1644-4f12-bb78-d7a14572d643", email=None
        )
        self.client.auth_get_user.return_value = expected

        self.assertIs(self.repository.auth_user_from_token("not-a-jwt"), expected)
        self.client.auth_get_user.assert_called_once_with("not-a-jwt")

    def test_all_uids_are_case_sensitive_uuid_v5_even_when_uuid_shaped(self):
        lower = "8c966c67-1644-4f12-bb78-d7a14572d643"
        upper = lower.upper()
        self.assertNotEqual(firebase_uid_to_internal_uuid(lower), lower)
        self.assertNotEqual(
            firebase_uid_to_internal_uuid(lower),
            firebase_uid_to_internal_uuid(upper),
        )
        first = firebase_uid_to_internal_uuid("firebase-random-uid")
        self.assertEqual(first, firebase_uid_to_internal_uuid("firebase-random-uid"))
        self.assertNotEqual(first, firebase_uid_to_internal_uuid("another-uid"))
        UUID(first)

    def test_uuid_shaped_uid_does_not_collide_with_claim_preserved_id(self):
        existing_id = "8c966c67-1644-4f12-bb78-d7a14572d643"
        self.assertNotEqual(firebase_uid_to_internal_uuid(existing_id), existing_id)

    @patch("app.services.firebase_auth.firebase_auth.verify_id_token")
    @patch("app.services.firebase_auth._firebase_app", return_value=object())
    def test_canonical_custom_claim_preserves_imported_internal_id(self, _app, verify):
        internal_id = "8c966c67-1644-4f12-bb78-d7a14572d643"
        verify.return_value = {
            "uid": "new-firebase-uid",
            "email": "person@example.com",
            "email_verified": True,
            "greeneatgo_internal_id": internal_id,
        }

        user = self.repository.auth_user_from_token(self.firebase_token)

        self.assertEqual(user.id, internal_id)
        self.assertNotIn("greeneatgo_internal_id", user.metadata)

    @patch("app.services.firebase_auth.firebase_auth.verify_id_token")
    @patch("app.services.firebase_auth._firebase_app", return_value=object())
    def test_noncanonical_or_invalid_custom_claim_is_rejected(self, _app, verify):
        for claim in (
            "8C966C67-1644-4F12-BB78-D7A14572D643",
            "not-a-uuid",
            123,
        ):
            with self.subTest(claim=claim):
                verify.return_value = {
                    "uid": "new-firebase-uid",
                    "email": "person@example.com",
                    "email_verified": True,
                    "greeneatgo_internal_id": claim,
                }
                with self.assertRaises(SupabaseHttpError) as raised:
                    self.repository.auth_user_from_token(self.firebase_token)
                self.assertEqual(raised.exception.status, 401)


class FirebasePhoneJoinTests(unittest.TestCase):
    def test_join_schema_normalizes_optional_phone(self):
        payload = JoinRequest(
            invite_code=" PILOT ", display_name=" Person ", phone="010-1234-5678"
        )
        self.assertEqual(payload.phone, "01012345678")

    def test_join_schema_rejects_invalid_phone(self):
        with self.assertRaises(ValueError):
            JoinRequest(invite_code="PILOT", display_name="Person", phone="02-123-4567")

    def _repository(self, *, auth_user: AuthUser) -> tuple[Mock, JoinRepository]:
        client = Mock()
        client.rpc.return_value = []
        client.rest_get.return_value = [{"used_count": 0}]
        repository = JoinRepository(client)
        repository.auth_user_from_token = Mock(return_value=auth_user)
        repository.get_profile = Mock(return_value=None)
        repository.get_invite = Mock(
            return_value=InviteCode(code="PILOT", company_id="c1")
        )
        return client, repository

    def test_hostile_body_phone_cannot_override_trusted_legacy_activation_phone(self):
        auth_user = AuthUser(
            id="8c966c67-1644-4f12-bb78-d7a14572d643",
            email="person@example.com",
            metadata={"phone": "01099998888"},
        )
        client, repository = self._repository(auth_user=auth_user)

        repository.request_join(
            access_token=_token("https://project.supabase.co/auth/v1"),
            invite_code="PILOT",
            display_name="Person",
            phone="01012345678",
        )

        client.rpc.assert_called_once_with(
            "activate_employee_bulk_invite",
            {
                "p_user_id": auth_user.id,
                "p_company_id": "c1",
                "p_phone": "01099998888",
                "p_invite_code": "PILOT",
            },
        )
        posted_profile = client.rest_post.call_args_list[0].args[1]
        self.assertEqual(posted_profile["phone"], "01012345678")

    def test_firebase_exact_bulk_profile_match_activates_staged_employee(self):
        auth_user = AuthUser(
            id="8c966c67-1644-4f12-bb78-d7a14572d643",
            email="person@example.com",
            metadata={},
        )
        client, repository = self._repository(auth_user=auth_user)
        client.rest_get.side_effect = lambda table, _params: (
            [{"id": "staged-1"}]
            if table == "employee_bulk_invites"
            else [{"used_count": 0}]
        )
        client.rpc.return_value = {"status": "active", "bulk_invite_claimed": True}

        result = repository.request_join(
            access_token=_token("https://securetoken.google.com/greeneatgo"),
            invite_code="PILOT",
            display_name="Person",
            phone="01012345678",
        )

        self.assertEqual(result["status"], "active")
        bulk_lookup = next(
            call for call in client.rest_get.call_args_list
            if call.args[0] == "employee_bulk_invites"
        )
        self.assertEqual(
            bulk_lookup.args[1],
            {
                "select": "id",
                "company_id": "eq.c1",
                "display_name": "eq.Person",
                "phone": "eq.01012345678",
                "status": "eq.invited",
                "limit": "1",
            },
        )
        client.rpc.assert_called_once_with(
            "activate_employee_bulk_invite",
            {
                "p_user_id": auth_user.id,
                "p_company_id": "c1",
                "p_phone": "01012345678",
                "p_invite_code": "PILOT",
            },
        )
        client.rest_post.assert_not_called()

    def test_firebase_unmatched_body_profile_stays_pending(self):
        auth_user = AuthUser(
            id="8c966c67-1644-4f12-bb78-d7a14572d643",
            email="person@example.com",
            metadata={},
        )
        client, repository = self._repository(auth_user=auth_user)
        client.rest_get.side_effect = lambda table, _params: (
            [] if table == "employee_bulk_invites" else [{"used_count": 0}]
        )

        repository.request_join(
            access_token=_token("https://securetoken.google.com/greeneatgo"),
            invite_code="PILOT",
            display_name="Different Person",
            phone="01012345678",
        )

        client.rpc.assert_not_called()
        posted_profile = client.rest_post.call_args_list[0].args[1]
        self.assertEqual(posted_profile["phone"], "01012345678")
        self.assertEqual(posted_profile["status"], "pending")


if __name__ == "__main__":
    unittest.main()
