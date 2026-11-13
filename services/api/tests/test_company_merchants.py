from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers import company_merchants as cm

ADMIN = SimpleNamespace(id="admin-1", company_id="company-1", role="company_admin", status="active")
MID = "11111111-1111-4111-8111-111111111111"


def _repo(**tables):
    repo = MagicMock()
    repo.client.rest_get.side_effect = lambda table, params: tables.get(table, [])
    repo.client.rest_patch.return_value = [{"id": "x"}]
    return repo


@patch.object(cm, "_company_admin", return_value=ADMIN)
@patch.object(cm, "JoinRepository")
def test_search_returns_public_fields_only_and_link_state(repo_class, _admin):
    repo = _repo(merchants=[{"id": MID, "name": "A식당"}], merchant_companies=[{"merchant_id": MID, "status": "paused"}])
    repo_class.return_value = repo
    data = cm.search_merchants(q="A*,(x)", token="t")["data"]
    params = repo.client.rest_get.call_args_list[0].args[1]
    assert params["select"] == "id,name,category,address,status" and params["status"] == "eq.active"
    inner = params["name"][len("ilike.*"):-1]
    assert not any(ch in inner for ch in "*,()")
    assert data["items"][0]["link_status"] == "paused"


@patch.object(cm, "_company_admin", return_value=ADMIN)
@patch.object(cm, "JoinRepository")
def test_link_creates_active_contract_for_own_company(repo_class, _admin):
    repo = _repo(merchants=[{"id": MID, "name": "A식당"}])
    repo_class.return_value = repo
    cm.link_merchant(merchant_id=MID, token="t")
    posted = [c.args for c in repo.client.rest_post.call_args_list]
    assert ("merchant_companies", {"merchant_id": MID, "company_id": "company-1", "status": "active", "created_by": "admin-1"}) in posted
    assert ("company_merchants", {"company_id": "company-1", "merchant_id": MID, "is_active": True}) in posted


@patch.object(cm, "_company_admin", return_value=ADMIN)
@patch.object(cm, "JoinRepository")
def test_link_rejects_inactive_or_unknown_merchant(repo_class, _admin):
    repo_class.return_value = _repo(merchants=[])
    with pytest.raises(HTTPException) as exc:
        cm.link_merchant(merchant_id=MID, token="t")
    assert exc.value.status_code == 404


@patch.object(cm, "_company_admin", return_value=ADMIN)
@patch.object(cm, "JoinRepository")
def test_pause_is_scoped_to_own_company(repo_class, _admin):
    repo = _repo(company_merchants=[{"company_id": "company-1"}])
    repo_class.return_value = repo
    cm.pause_merchant(merchant_id=MID, token="t")
    first = repo.client.rest_patch.call_args_list[0].args
    assert first[0] == "merchant_companies" and first[1]["company_id"] == "eq.company-1" and first[2] == {"status": "paused"}


def test_non_company_admin_is_forbidden():
    from app.services.join_flow import JoinFlowError
    with patch.object(cm, "_company_admin", side_effect=JoinFlowError("FORBIDDEN", "x")):
        with pytest.raises(HTTPException) as exc:
            cm._actor(MagicMock(), "t")
    assert exc.value.status_code == 403
