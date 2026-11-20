"""Bulk-registered staff join without an invite code (migration 0078)."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.repositories.phone_auth import PhoneAuthRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers import admin, join
from app.routers.me import _employee_invite_offer

AUTH = {"Authorization": "Bearer fixture"}
INVITE = "6f1c2d3e-4a5b-4c6d-8e7f-0a1b2c3d4e5f"
MIGRATION = Path(__file__).parents[3] / "supabase/migrations/0078_bulk_invite_auto_link.sql"


# ---------- API (database mocked) ----------

def _client(module, role="customer"):
    app = FastAPI()
    app.include_router(module.router, prefix="/v1")
    patcher = patch(f"app.routers.{module.__name__.rsplit('.', 1)[-1]}.JoinRepository")
    repo = patcher.start().return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id="user-1", email=None)
    repo.get_profile.return_value = SimpleNamespace(id="user-1", role=role, status="active", company_id="company-1")
    return TestClient(app), repo, patcher


def test_member_accepts_or_declines_only_their_own_offer():
    client, repo, patcher = _client(join)
    try:
        repo.client.rpc.return_value = {"status": "accepted", "company_name": "테스트회사"}
        response = client.post("/v1/join/bulk-invite/respond", json={"invite_id": INVITE, "accept": True}, headers=AUTH)
        assert response.json()["data"] == {"status": "accepted", "company_name": "테스트회사"}
        # The caller's id comes from the session, never from the request.
        assert repo.client.rpc.call_args.args == ("respond_employee_bulk_invite", {
            "p_user_id": "user-1", "p_invite_id": INVITE, "p_accept": True, "p_fresh_only": False})
        repo.client.rpc.return_value = {"status": "declined", "company_name": "테스트회사"}
        response = client.post("/v1/join/bulk-invite/respond", json={"invite_id": INVITE, "accept": False}, headers=AUTH)
        assert response.json()["data"]["status"] == "declined"
        assert repo.client.rpc.call_args.args[1]["p_accept"] is False
        for status, code in (("not_found", 404), ("conflict", 409), ("not_eligible", 409), ("needs_confirmation", 404)):
            repo.client.rpc.return_value = {"status": status}
            assert client.post("/v1/join/bulk-invite/respond", json={"invite_id": INVITE, "accept": True}, headers=AUTH).status_code == code
        assert client.post("/v1/join/bulk-invite/respond", json={"invite_id": "x", "accept": True}, headers=AUTH).status_code == 422
        repo.client.rpc.side_effect = SupabaseHttpError(500, "boom")
        assert client.post("/v1/join/bulk-invite/respond", json={"invite_id": INVITE, "accept": True}, headers=AUTH).status_code == 502
    finally:
        patcher.stop()


def test_me_offer_is_optional_and_tolerates_a_missing_function():
    repo = MagicMock()
    repo.client.rpc.return_value = {"invite_id": INVITE, "company_name": "테스트회사", "display_name": "김직원",
                                    "department": "개발", "employee_no": "A-1", "company_id": "c"}
    assert _employee_invite_offer(repo, "user-1") == {
        "invite_id": INVITE, "company_name": "테스트회사", "display_name": "김직원", "department": "개발"}
    repo.client.rpc.return_value = None
    assert _employee_invite_offer(repo, "user-1") is None
    repo.client.rpc.side_effect = SupabaseHttpError(404, "PGRST202 function not found")
    assert _employee_invite_offer(repo, "user-1") is None


def test_signup_links_a_fresh_account_and_never_fails_because_of_it():
    repo = PhoneAuthRepository(client=MagicMock(), settings=MagicMock(), sms=MagicMock())
    repo.client.rpc.return_value = {"status": "accepted", "company_name": "테스트회사"}
    assert repo._link_bulk_invite_on_signup("user-1") == "테스트회사"
    assert repo.client.rpc.call_args.args == ("respond_employee_bulk_invite", {
        "p_user_id": "user-1", "p_invite_id": None, "p_accept": True, "p_fresh_only": True})
    for answer in ({"status": "needs_confirmation", "company_name": "테스트회사"}, {"status": "not_found"}, None):
        repo.client.rpc.return_value = answer
        assert repo._link_bulk_invite_on_signup("user-1") is None
    repo.client.rpc.side_effect = SupabaseHttpError(404, "function not found")
    assert repo._link_bulk_invite_on_signup("user-1") is None


def test_company_admin_sees_declined_rows_and_can_reinvite_only_in_their_company():
    client, repo, patcher = _client(admin, role="company_admin")
    try:
        repo.client.rpc.return_value = True
        response = client.post(f"/v1/admin/employees/bulk-invites/bulk:{INVITE}/reinvite", headers=AUTH)
        assert response.status_code == 200
        assert repo.client.rpc.call_args.args == ("reinvite_employee_bulk_invite", {
            "p_company_id": "company-1", "p_invite_id": INVITE})
        repo.client.rpc.return_value = False
        assert client.post(f"/v1/admin/employees/bulk-invites/{INVITE}/reinvite", headers=AUTH).status_code == 404
        assert client.post("/v1/admin/employees/bulk-invites/not-a-uuid/reinvite", headers=AUTH).status_code == 404

        def rest_get(table, params):
            if table == "employee_bulk_invites":
                assert params["status"] == "in.(invited,declined)"
                return [{"id": INVITE, "display_name": "김거절", "employee_no": "A-2", "phone": "01011112222",
                         "department": None, "status": "declined", "created_at": "2026-11-20T00:00:00+00:00",
                         "declined_at": "2026-11-21T01:00:00+00:00", "declined_by": "user-9", "company_id": "company-1"}]
            return []

        repo.client.rest_get.side_effect = rest_get
        items = client.get("/v1/admin/employees", headers=AUTH).json()["data"]["items"]
        assert [(i["id"], i["is_staged"], i["status"], i["declined_at"]) for i in items] == [
            (f"bulk:{INVITE}", True, "declined", "2026-11-21T01:00:00+00:00")]
        assert "declined_by" not in items[0]
    finally:
        patcher.stop()


def test_member_endpoint_is_not_open_to_company_admins_reinvite_is_not_open_to_members():
    client, repo, patcher = _client(admin, role="customer")
    try:
        assert client.post(f"/v1/admin/employees/bulk-invites/{INVITE}/reinvite", headers=AUTH).status_code in (400, 403)
        repo.client.rpc.assert_not_called()
    finally:
        patcher.stop()


def test_migration_keeps_the_functions_server_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    for name in ("employee_bulk_invite_offer(uuid)", "respond_employee_bulk_invite(uuid, uuid, boolean, boolean)",
                 "reinvite_employee_bulk_invite(uuid, uuid)"):
        assert f"revoke all on function public.{name} from public, anon, authenticated;" in sql
        assert f"grant execute on function public.{name} to service_role;" in sql
    assert "phone_verified_at is null" in sql
