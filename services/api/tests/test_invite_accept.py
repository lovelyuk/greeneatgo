from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.repositories.supabase_http import SupabaseHttpError
from app.routers import invites
from app.schemas import InviteAcceptRequest

INVITE = {"id": "inv-1", "token": "tok", "role": "company_admin", "company_id": "c-1", "merchant_id": None,
          "email": "Boss@Example.com", "status": "pending", "expires_at": "2099-01-01T00:00:00+00:00"}


def _repo(invite=INVITE, reserve=True):
    repo = MagicMock()
    repo.client.rest_get.return_value = [dict(invite)]

    def patch_(table, params, values):
        if table == "invites" and params.get("status") == "eq.pending":
            return [{"id": "inv-1"}] if reserve else []
        return [{"id": "x"}]

    repo.client.rest_patch.side_effect = patch_
    repo.client.auth_admin_create_user.return_value = SimpleNamespace(id="u-1", email="boss@example.com")
    repo.client.rest_post.return_value = [{"id": "u-1"}]
    return repo


@patch.object(invites, "JoinRepository")
def test_accept_creates_confirmed_user_for_invited_email(repo_class):
    repo = repo_class.return_value = _repo()
    data = invites.accept_invite("tok", InviteAcceptRequest(password="longpassword", display_name="대표"))["data"]
    repo.client.auth_admin_create_user.assert_called_once_with(
        email="boss@example.com", password="longpassword", user_metadata={"display_name": "대표"})
    profile = repo.client.rest_post.call_args.args[1]
    assert profile["role"] == "company_admin" and profile["company_id"] == "c-1" and profile["merchant_id"] is None
    patches = [c.args for c in repo.client.rest_patch.call_args_list]
    assert patches[0] == ("invites", {"id": "eq.inv-1", "status": "eq.pending"}, {"status": "claimed"})
    assert any(p[0] == "invites" and p[2].get("status") == "accepted" for p in patches)
    assert data["email"] == "boss@example.com"


@patch.object(invites, "JoinRepository")
def test_invited_email_cannot_be_replaced(repo_class):
    repo = repo_class.return_value = _repo()
    with pytest.raises(HTTPException) as exc:
        invites.accept_invite("tok", InviteAcceptRequest(password="longpassword", email="other@example.com"))
    assert exc.value.detail["code"] == "INVITE_EMAIL_MISMATCH"
    repo.client.auth_admin_create_user.assert_not_called()


@patch.object(invites, "JoinRepository")
def test_one_invite_creates_at_most_one_account(repo_class):
    repo = repo_class.return_value = _repo(reserve=False)
    with pytest.raises(HTTPException) as exc:
        invites.accept_invite("tok", InviteAcceptRequest(password="longpassword"))
    assert exc.value.status_code == 409
    repo.client.auth_admin_create_user.assert_not_called()


@patch.object(invites, "JoinRepository")
def test_existing_email_releases_invite(repo_class):
    repo = repo_class.return_value = _repo()
    repo.client.auth_admin_create_user.side_effect = SupabaseHttpError(422, '{"msg":"A user with this email address has already been registered"}')
    with pytest.raises(HTTPException) as exc:
        invites.accept_invite("tok", InviteAcceptRequest(password="longpassword"))
    assert exc.value.detail["code"] == "EMAIL_ALREADY_REGISTERED"
    assert ("invites", {"id": "eq.inv-1", "status": "eq.claimed"}, {"status": "pending"}) in [c.args for c in repo.client.rest_patch.call_args_list]


@patch.object(invites, "JoinRepository")
def test_profile_failure_deletes_auth_user_and_releases_invite(repo_class):
    repo = repo_class.return_value = _repo()
    repo.client.rest_post.side_effect = SupabaseHttpError(409, "conflict")
    with pytest.raises(HTTPException):
        invites.accept_invite("tok", InviteAcceptRequest(password="longpassword"))
    repo.client.auth_admin_delete_user.assert_called_once_with("u-1")


@patch.object(invites, "JoinRepository")
def test_emailless_merchant_invite_needs_an_email(repo_class):
    repo_class.return_value = _repo(invite={**INVITE, "email": None, "role": "merchant_admin", "merchant_id": "m-1", "company_id": None})
    with pytest.raises(HTTPException) as exc:
        invites.accept_invite("tok", InviteAcceptRequest(password="longpassword"))
    assert exc.value.detail["code"] == "INVITE_EMAIL_REQUIRED"


def test_password_minimum():
    with pytest.raises(ValidationError):
        InviteAcceptRequest(password="short")
