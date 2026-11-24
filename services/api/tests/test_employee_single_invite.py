"""Company admin adds one employee by hand and removes a not-yet-joined row."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.repositories.supabase_http import SupabaseHttpError
from app.routers import admin

AUTH = {"Authorization": "Bearer fixture"}
INVITE = "6f1c2d3e-4a5b-4c6d-8e7f-0a1b2c3d4e5f"


@pytest.fixture
def harness():
    app = FastAPI()
    app.include_router(admin.router, prefix="/v1")
    with patch("app.routers.admin.JoinRepository") as repo_class:
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-1", email=None)
        repo.get_profile.return_value = SimpleNamespace(id="admin-1", role="company_admin", status="active", company_id="company-1")
        existing = {"app_users": [{"phone": "01011110000", "employee_no": "E001"}],
                    "employee_bulk_invites": [{"phone": "01022220000", "employee_no": "E002"}]}
        repo.client.rest_get.side_effect = lambda table, params: existing.get(table, [])
        repo.client.rpc.return_value = 1
        yield TestClient(app), repo


def test_one_employee_is_stored_like_one_bulk_row(harness):
    client, repo = harness
    response = client.post("/v1/admin/employees/invites", headers=AUTH,
                           json={"name": " 김신입 ", "phone": "010-3333-4444", "department": "영업팀", "employee_no": "E100"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["invite"] == {
        "display_name": "김신입", "phone": "01033334444", "department": "영업팀", "employee_no": "E100", "status": "invited"}
    assert repo.client.rpc.call_args.args == ("confirm_employee_bulk_invites", {
        "p_company_id": "company-1",
        "p_rows": [{"department": "영업팀", "display_name": "김신입", "employee_no": "E100", "phone": "01033334444"}]})


def test_optional_fields_can_be_left_empty_and_the_number_is_generated(harness):
    client, repo = harness
    response = client.post("/v1/admin/employees/invites", headers=AUTH, json={"name": "박신입", "phone": "01055556666"})
    assert response.status_code == 200, response.text
    row = repo.client.rpc.call_args.args[1]["p_rows"][0]
    assert row["department"] is None and row["employee_no"] and row["employee_no"] not in {"E001", "E002"}


@pytest.mark.parametrize("body, message", [
    ({"name": "김", "phone": "010-12-34"}, "전화번호 형식을 확인해 주세요 (예: 010-1234-5678)"),
    ({"name": "김", "phone": "02-123-4567"}, "전화번호 형식을 확인해 주세요 (예: 010-1234-5678)"),
    ({"name": "김", "phone": "010-1111-0000"}, "이미 등록된 번호예요"),      # already an employee
    ({"name": "김", "phone": "01022220000"}, "이미 등록된 번호예요"),        # already registered, not joined
    ({"name": "김", "phone": "01077778888", "employee_no": "E002"}, "이미 등록된 사번이에요"),
    ({"name": "   ", "phone": "01077778888"}, "이름을 입력해 주세요"),
])
def test_bad_or_duplicate_input_is_refused_before_anything_is_stored(harness, body, message):
    client, repo = harness
    response = client.post("/v1/admin/employees/invites", headers=AUTH, json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["message"] == message
    repo.client.rpc.assert_not_called()


def test_a_duplicate_caught_by_the_database_is_reported_not_crashed(harness):
    client, repo = harness
    repo.client.rpc.side_effect = SupabaseHttpError(400, '{"message":"DUPLICATE_PHONE"}')
    response = client.post("/v1/admin/employees/invites", headers=AUTH, json={"name": "김", "phone": "01077778888"})
    assert (response.status_code, response.json()["detail"]["code"]) == (422, "EMPLOYEE_INVITE_INVALID")
    repo.client.rpc.side_effect = SupabaseHttpError(500, "boom")
    assert client.post("/v1/admin/employees/invites", headers=AUTH, json={"name": "김", "phone": "01077778888"}).status_code == 502
    for bad in ({}, {"name": "김"}, {"name": "김", "phone": "01077778888", "role": "company_admin"}):
        assert client.post("/v1/admin/employees/invites", headers=AUTH, json=bad).status_code == 422


def test_delete_removes_only_an_unclaimed_row_of_the_admins_company(harness):
    client, repo = harness
    repo.client.rest_delete.return_value = [{"id": INVITE}]
    response = client.delete(f"/v1/admin/employees/bulk-invites/bulk:{INVITE}", headers=AUTH)
    assert response.status_code == 200, response.text
    assert repo.client.rest_delete.call_args.args == ("employee_bulk_invites", {
        "id": f"eq.{INVITE}", "company_id": "eq.company-1", "status": "in.(invited,declined)"})
    # Already joined, another company's row, or gone: nothing matched.
    repo.client.rest_delete.return_value = []
    assert client.delete(f"/v1/admin/employees/bulk-invites/{INVITE}", headers=AUTH).status_code == 404
    repo.client.rest_delete.reset_mock()
    assert client.delete("/v1/admin/employees/bulk-invites/not-a-uuid", headers=AUTH).status_code == 404
    repo.client.rest_delete.assert_not_called()


@pytest.mark.parametrize("role", ["customer", "employee", "merchant_admin"])
def test_only_a_company_admin_can_add_or_delete(harness, role):
    client, repo = harness
    repo.get_profile.return_value = SimpleNamespace(id="u", role=role, status="active", company_id="company-1")
    assert client.post("/v1/admin/employees/invites", headers=AUTH, json={"name": "김", "phone": "01077778888"}).status_code in (400, 403)
    assert client.delete(f"/v1/admin/employees/bulk-invites/{INVITE}", headers=AUTH).status_code in (400, 403)
    repo.client.rpc.assert_not_called()
    repo.client.rest_delete.assert_not_called()
