import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.routers.push_notifications import (
    _audience,
    create_notification,
    register_device_token,
)
from app.schemas import DeviceTokenRegisterRequest, NotificationCreateRequest
from app.services.join_flow import UserProfile
from app.services.push_notifications import PushSendResult, PushTarget, send_push_notifications


class _ResponseItem:
    def __init__(self, success, exception=None):
        self.success = success
        self.exception = exception


class _BatchResponse:
    def __init__(self, responses):
        self.responses = responses


class _UnregisteredError(Exception):
    code = "registration-token-not-registered"


def _notification_payload(*, target_type="all", target_count=2, device_count=2, title="공지", body="내용"):
    return NotificationCreateRequest(
        title=title,
        body=body,
        target_type=target_type,
        idempotency_key="test-idempotency-key-0001",
        expected_target_count=target_count,
        expected_device_count=device_count,
    )


class PushServiceTests(unittest.TestCase):
    def test_multicast_is_batched_at_500_and_partial_failures_continue(self):
        calls = []
        targets = [PushTarget(account_id=f"account-{index // 2}", token=f"token-{index}") for index in range(1001)]

        def sender(title, body, tokens):
            calls.append(list(tokens))
            return _BatchResponse([
                _ResponseItem(False, _UnregisteredError()) if token == "token-500" else _ResponseItem(True)
                for token in tokens
            ])

        result = send_push_notifications(title="제목", body="내용", targets=targets, send_batch=sender)

        self.assertEqual([len(batch) for batch in calls], [500, 500, 1])
        self.assertEqual(result.device_count, 1001)
        self.assertEqual(result.success_device_count, 1000)
        self.assertEqual(result.failure_device_count, 1)
        self.assertEqual(result.target_count, 501)
        self.assertEqual(result.success_count, 501)
        self.assertEqual(result.invalid_tokens, ("token-500",))

    def test_empty_target_list_does_not_call_firebase(self):
        sender = Mock()
        result = send_push_notifications(title="제목", body="내용", targets=[], send_batch=sender)
        sender.assert_not_called()
        self.assertEqual(result.target_count, 0)


class PushSchemaTests(unittest.TestCase):
    def test_notification_copy_is_trimmed_and_invalid_target_rejected(self):
        payload = _notification_payload(title="  휴무 안내 ", body="  내일 쉽니다. ")
        self.assertEqual(payload.title, "휴무 안내")
        with self.assertRaises(ValidationError):
            _notification_payload(title=" ", target_type="ledger_only")

    def test_device_token_rejects_unknown_fields(self):
        with self.assertRaises(ValidationError):
            DeviceTokenRegisterRequest.model_validate({
                "account_id": "account-123", "fcm_token": "x" * 30,
                "platform": "android", "role": "customer",
            })


class AudienceTests(unittest.TestCase):
    def _repo(self):
        client = Mock()

        def rest_get(table, params):
            if table == "app_users":
                return [{"id": "employee-1"}, {"id": "customer-1"}]
            if table == "device_tokens":
                return [
                    {"account_id": "employee-1", "fcm_token": "employee-token"},
                    {"account_id": "customer-1", "fcm_token": "customer-token-a"},
                    {"account_id": "customer-1", "fcm_token": "customer-token-b"},
                ]
            raise AssertionError(table)

        client.rest_get.side_effect = rest_get
        repo = Mock()
        repo.client = client
        return repo

    def test_all_audience_uses_only_active_employee_and_customer_roles(self):
        repo = self._repo()
        result = _audience(repo, "all")
        first_call = repo.client.rest_get.call_args_list[0]
        self.assertEqual(first_call.args[1]["role"], "in.(employee,customer)")
        self.assertEqual(first_call.args[1]["status"], "eq.active")
        self.assertEqual(result["eligible_count"], 2)
        self.assertEqual(result["target_count"], 2)
        self.assertEqual(result["device_count"], 3)

    def test_voucher_only_audience_uses_customer_role(self):
        repo = self._repo()
        _audience(repo, "voucher_only")
        self.assertEqual(repo.client.rest_get.call_args_list[0].args[1]["role"], "eq.customer")


class PushRouterTests(unittest.TestCase):
    @patch("app.routers.push_notifications.JoinRepository")
    def test_active_customer_can_register_only_own_token(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="customer-1", email="c@example.com")
        repo.get_profile.return_value = UserProfile(
            id="customer-1", email="c@example.com", display_name="고객",
            role="customer", status="active",
        )
        payload = DeviceTokenRegisterRequest(
            account_id="customer-1", fcm_token="fcm-token-abcdefghijklmnopqrstuvwxyz", platform="android"
        )

        result = register_device_token(payload, "access-token")

        repo.client.rpc.assert_called_once_with("register_device_token", {
            "p_account_id": "customer-1",
            "p_fcm_token": payload.fcm_token,
            "p_platform": "android",
        })
        self.assertTrue(result["data"]["registered"])

    @patch("app.routers.push_notifications.JoinRepository")
    def test_account_id_mismatch_is_forbidden(self, repo_class):
        repo_class.return_value.auth_user_from_token.return_value = SimpleNamespace(id="customer-1", email=None)
        payload = DeviceTokenRegisterRequest(
            account_id="customer-2", fcm_token="fcm-token-abcdefghijklmnopqrstuvwxyz", platform="android"
        )
        with self.assertRaises(HTTPException) as ctx:
            register_device_token(payload, "access-token")
        self.assertEqual(ctx.exception.status_code, 403)
        repo_class.return_value.client.rpc.assert_not_called()

    @patch("app.routers.push_notifications.send_push_notifications")
    @patch("app.routers.push_notifications._merchant_admin")
    @patch("app.routers.push_notifications._audience")
    @patch("app.routers.push_notifications.JoinRepository")
    def test_send_records_history_and_removes_only_invalid_token(
        self, repo_class, audience, merchant_admin, send_push
    ):
        repo = repo_class.return_value
        actor = SimpleNamespace(id="merchant-admin-1")
        merchant_admin.return_value = (actor, "merchant-1")
        audience.return_value = {
            "eligible_count": 2,
            "target_count": 2,
            "device_count": 2,
            "targets": [PushTarget("employee-1", "good-token"), PushTarget("customer-1", "bad-token")],
        }
        send_push.return_value = PushSendResult(2, 2, 1, 1, 1, ("bad-token",))
        repo.client.rest_post.return_value = [{"id": "notification-1", "sent_at": "2026-07-11T00:00:00Z"}]
        payload = NotificationCreateRequest(title="공지", body="내용", target_type="all")

        result = create_notification(payload, "access-token")

        repo.client.rest_delete.assert_called_once_with("device_tokens", {"fcm_token": "eq.bad-token"})
        history = repo.client.rest_post.call_args.args[1]
        self.assertEqual(history["merchant_id"], "merchant-1")
        self.assertEqual(history["target_count"], 2)
        self.assertEqual(history["success_count"], 1)
        self.assertEqual(result["data"]["failure_device_count"], 1)

    @patch("app.routers.push_notifications._merchant_admin")
    @patch("app.routers.push_notifications._audience")
    @patch("app.routers.push_notifications.JoinRepository")
    def test_zero_reachable_targets_blocks_send(self, repo_class, audience, merchant_admin):
        merchant_admin.return_value = (SimpleNamespace(id="merchant-admin-1"), "merchant-1")
        audience.return_value = {
            "eligible_count": 4, "target_count": 0, "device_count": 0, "targets": []
        }
        payload = NotificationCreateRequest(title="공지", body="내용", target_type="voucher_only")
        with self.assertRaises(HTTPException) as ctx:
            create_notification(payload, "access-token")
        self.assertEqual(ctx.exception.status_code, 400)
        repo_class.return_value.client.rest_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
