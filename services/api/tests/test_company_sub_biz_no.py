"""종사업장번호 on companies, and the first invitation for a company registered without one."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.repositories.supabase_http import SupabaseHttpError
from app.routers.me import _company_profile, update_company_profile
from app.routers.merchant_admin import _company_rows, resend_company_invite
from app.schemas import CompanyBusinessProfileUpdateRequest

MISSING = SupabaseHttpError(400, '{"code":"42703","message":"column companies.sub_biz_no does not exist"}')


def _repo(rest_get):
    return SimpleNamespace(client=SimpleNamespace(rest_get=rest_get))


def test_profile_request_takes_four_digits_or_nothing():
    base = {"name": "(주)엠게임", "biz_reg_no": "114-81-93597"}
    assert CompanyBusinessProfileUpdateRequest(**base).sub_biz_no is None
    assert CompanyBusinessProfileUpdateRequest(**base, sub_biz_no="0001").sub_biz_no == "0001"
    assert CompanyBusinessProfileUpdateRequest(**base, sub_biz_no=" 0006 ").sub_biz_no == "0006"
    assert CompanyBusinessProfileUpdateRequest(**base, sub_biz_no="  ").sub_biz_no is None
    for bad in ("1", "00001", "000a"):
        with pytest.raises(ValidationError):
            CompanyBusinessProfileUpdateRequest(**base, sub_biz_no=bad)


def test_company_reads_carry_the_number_and_survive_a_missing_column():
    seen = []

    def with_column(table, params):
        seen.append(params["select"])
        return [{"id": "c1", "name": "(주)엠게임", "sub_biz_no": "0001"}]

    assert _company_rows(_repo(with_column), ["c1"])[0]["sub_biz_no"] == "0001"
    assert _company_profile(_repo(with_column), "c1")["sub_biz_no"] == "0001"
    assert all(select.endswith(",sub_biz_no") for select in seen)

    def without_column(table, params):
        if "sub_biz_no" in params["select"]:
            raise MISSING
        return [{"id": "c1", "name": "(주)엠게임"}]

    assert _company_rows(_repo(without_column), ["c1"]) == [{"id": "c1", "name": "(주)엠게임", "sub_biz_no": None}]
    assert _company_profile(_repo(without_column), "c1")["sub_biz_no"] is None

    def broken(table, params):
        raise SupabaseHttpError(500, "boom")

    with pytest.raises(SupabaseHttpError):
        _company_rows(_repo(broken), ["c1"])


@patch("app.routers.me._company_profile", return_value={"id": "c1"})
@patch("app.routers.me.JoinRepository")
def test_saving_the_profile_before_the_migration(repo_class, _profile):
    repo = repo_class.return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id="u", email=None)
    repo.get_profile.return_value = SimpleNamespace(role="company_admin", status="active", company_id="c1")
    calls = []

    def patch_row(table, params, values):
        calls.append(dict(values))
        if "sub_biz_no" in values:
            raise MISSING
        return [{"id": "c1"}]

    repo.client.rest_patch.side_effect = patch_row
    base = {"name": "(주)엠게임", "biz_reg_no": "114-81-93597"}
    # No branch number: the rest of the profile still saves.
    update_company_profile(CompanyBusinessProfileUpdateRequest(**base), "bearer")
    assert "sub_biz_no" in calls[0] and "sub_biz_no" not in calls[1]
    # A branch number cannot be dropped silently.
    with pytest.raises(HTTPException) as caught:
        update_company_profile(CompanyBusinessProfileUpdateRequest(**base, sub_biz_no="0001"), "bearer")
    assert caught.value.detail["code"] == "MIGRATION_REQUIRED"


def _resend(repo_class, *, invites, company):
    repo = repo_class.return_value
    repo.client.rest_get.side_effect = lambda table, params: invites if table == "invites" else []
    repo.client.rest_post.side_effect = lambda table, values: [{**values, "id": "inv-new"}]
    actor = SimpleNamespace(id="actor-1", email="owner@example.test")
    with patch("app.routers.merchant_admin._merchant_admin", return_value=(actor, "m1")), \
            patch("app.routers.merchant_admin._require_company_link"), \
            patch("app.routers.merchant_admin._company_rows", return_value=[company] if company else []), \
            patch("app.routers.merchant_admin._merchant_name", return_value="그린잇"), \
            patch("app.routers.merchant_admin._deliver_company_invite",
                  side_effect=lambda repo, invite, name, **kw: {**invite, "email_send_status": "sent", "to": name}) as deliver:
        return repo, deliver, resend_company_invite("c1", "bearer")


@patch("app.routers.merchant_admin.JoinRepository")
def test_a_company_registered_without_an_invitation_gets_its_first_one(repo_class):
    company = {"id": "c1", "name": "(주)론스텍", "contact_email": " Bill@Example.Test ", "contact_phone": "010-0000-0000"}
    repo, deliver, out = _resend(repo_class, invites=[], company=company)
    table, values = repo.client.rest_post.call_args.args
    assert table == "invites"
    assert (values["role"], values["company_id"], values["email"], values["invited_by"]) == ("company_admin", "c1", "bill@example.test", "actor-1")
    assert len(values["token"]) >= 32 and values["expires_at"]
    assert deliver.call_count == 1
    assert (out["data"]["created"], out["data"]["invite"]["email_send_status"], out["data"]["invite"]["to"]) == (True, "sent", "(주)론스텍")


@patch("app.routers.merchant_admin.JoinRepository")
def test_no_contact_email_means_no_invitation_is_created(repo_class):
    for company in ({"id": "c1", "name": "x", "contact_email": None}, None):
        repo_class.reset_mock()
        with pytest.raises(HTTPException) as caught:
            _resend(repo_class, invites=[], company=company)
        assert (caught.value.status_code, caught.value.detail["code"]) == (409, "INVITE_EMAIL_MISSING")
        repo_class.return_value.client.rest_post.assert_not_called()
