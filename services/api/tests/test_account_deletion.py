from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers import me as me_router


def _repo(role="customer", status="active", phone="01012345678"):
    repo = MagicMock()
    repo.auth_user_from_token.return_value = SimpleNamespace(id="u-1", email=None)
    repo.get_profile.return_value = SimpleNamespace(id="u-1", role=role, status=status, phone=phone)
    return repo


@patch.object(me_router, "_delete_login_identity")
@patch.object(me_router, "JoinRepository")
def test_buyer_deletion_anonymises_profile_and_keeps_ledger(repo_class, delete_identity):
    repo = repo_class.return_value = _repo()
    assert me_router.delete_my_account("tok")["data"] == {"deleted": True}
    patches = {c.args[0]: c.args for c in repo.client.rest_patch.call_args_list}
    assert patches["payment_orders"][1]["status"] == "eq.ready" and patches["payment_orders"][2] == {"status": "canceled"}
    assert patches["app_users"][2] == {"display_name": "탈퇴회원", "phone": None, "phone_verified_at": None,
                                       "department": None, "employee_no": None, "status": "left"}
    repo.client.rest_delete.assert_called_once_with("device_tokens", {"account_id": "eq.u-1"})
    delete_identity.assert_called_once_with(repo, "tok", "u-1", "01012345678")
    # Never deletes ledger rows.
    assert all(c.args[0] == "device_tokens" for c in repo.client.rest_delete.call_args_list)


@patch.object(me_router, "JoinRepository")
def test_admin_accounts_cannot_self_delete(repo_class):
    repo_class.return_value = _repo(role="company_admin")
    with pytest.raises(HTTPException) as exc:
        me_router.delete_my_account("tok")
    assert exc.value.status_code == 403


@patch.object(me_router, "_delete_login_identity")
@patch.object(me_router, "JoinRepository")
def test_repeat_deletion_is_idempotent(repo_class, delete_identity):
    repo = repo_class.return_value = _repo(status="left", phone=None)
    me_router.delete_my_account("tok")
    repo.client.rest_patch.assert_not_called()
    delete_identity.assert_called_once()


def test_email_account_identity_is_deleted_in_supabase():
    repo = MagicMock()
    with patch("app.services.firebase_auth.is_firebase_token", return_value=False):
        me_router._delete_login_identity(repo, "supabase-jwt", "u-1", None)
    repo.client.auth_admin_delete_user.assert_called_once_with("u-1")


def test_phone_account_identity_is_deleted_in_firebase():
    deleted = []
    fake_auth = SimpleNamespace(delete_user=lambda uid, app=None: deleted.append(uid))
    with patch("app.services.firebase_auth.is_firebase_token", return_value=True), \
         patch("firebase_admin.auth", fake_auth), patch("app.services.push_notifications._firebase_app", return_value=None):
        me_router._delete_login_identity(MagicMock(), "firebase-jwt", "u-1", "01012345678")
    assert deleted == ["phone_01012345678"]
