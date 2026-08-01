from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from app.routers.boards import ReviewCreate, _mask, create_review, delete_announcement, reviews, update_review


def repo_with_customer():
    repo = Mock()
    repo.auth_user_from_token.return_value = SimpleNamespace(id="user-1", email="u@example.com")
    repo.get_profile.return_value = SimpleNamespace(id="user-1", role="customer", status="active")
    repo.client.settings.supabase_url = "https://example.supabase.co"
    return repo


def test_mask_never_returns_full_name():
    assert _mask("홍길동") == "홍*동님"
    assert _mask("김수") == "김*님"
    assert _mask("박") == "박*님"


@patch("app.routers.boards.JoinRepository")
def test_review_rejects_transaction_not_owned(repo_class):
    repo = repo_with_customer(); repo_class.return_value = repo
    repo.client.rest_get.return_value = [{"id": 7, "user_id": "other", "merchant_id": "m-1", "kind": "spend"}]
    with pytest.raises(HTTPException) as exc:
        create_review(ReviewCreate(transaction_id=7, rating=5), "token")
    assert exc.value.status_code == 403
    repo.client.rest_post.assert_not_called()


@patch("app.routers.boards.JoinRepository")
def test_review_requires_completed_spend(repo_class):
    repo = repo_with_customer(); repo_class.return_value = repo
    repo.client.rest_get.return_value = [{"id": 7, "user_id": "user-1", "merchant_id": "m-1", "kind": "refund"}]
    with pytest.raises(HTTPException) as exc:
        create_review(ReviewCreate(transaction_id=7, rating=5), "token")
    assert exc.value.status_code == 422


@patch("app.routers.boards.JoinRepository")
def test_duplicate_transaction_returns_conflict(repo_class):
    from app.repositories.supabase_http import SupabaseHttpError
    repo = repo_with_customer(); repo_class.return_value = repo
    repo.client.rest_get.return_value = [{"id": 7, "user_id": "user-1", "merchant_id": "m-1", "kind": "spend"}]
    repo.client.rest_post.side_effect = SupabaseHttpError(409, "23505 duplicate")
    with pytest.raises(HTTPException) as exc:
        create_review(ReviewCreate(transaction_id=7, rating=5), "token")
    assert exc.value.status_code == 409


@patch("app.routers.boards._pilot_merchant", return_value={"id": "m-1"})
@patch("app.routers.boards.JoinRepository")
def test_public_average_excludes_hidden_by_query(repo_class, _merchant):
    repo = repo_class.return_value
    repo.client.rest_get.side_effect = [
        [{"id": "r1", "account_id": "u1", "rating": 5, "content": None, "status": "visible"}],
        [{"id": "u1", "display_name": "홍길동"}],
    ]
    result = reviews()["data"]
    assert result["average_rating"] == 5.0
    assert result["items"][0]["author_name"] == "홍*동님"
    assert repo.client.rest_get.call_args_list[0].args[1]["status"] == "eq.visible"


@patch("app.routers.boards._merchant_admin", return_value=(SimpleNamespace(id="admin"), "m-1"))
@patch("app.routers.boards.JoinRepository")
def test_admin_patch_is_tenant_scoped(repo_class, _admin):
    repo = repo_class.return_value
    repo.client.rest_patch.return_value = [{"id": "r1", "account_id": "u1", "status": "hidden"}]
    repo.client.rest_get.return_value = [{"id": "u1", "display_name": "홍길동"}]
    update_review("r1", __import__("app.routers.boards", fromlist=["ReviewUpdate"]).ReviewUpdate(status="hidden"), "token")
    params = repo.client.rest_patch.call_args.args[1]
    assert params == {"id": "eq.r1", "merchant_id": "eq.m-1"}


@patch("app.routers.boards._pilot_merchant", return_value={"id": "m-1"})
@patch("app.routers.boards.JoinRepository")
def test_authenticated_author_can_see_own_hidden_review(repo_class, _merchant):
    repo = repo_with_customer(); repo_class.return_value = repo
    repo.client.rest_get.side_effect = [
        [
            {"id": "visible", "account_id": "other", "rating": 5, "status": "visible"},
            {"id": "hidden-own", "account_id": "user-1", "rating": 1, "status": "hidden"},
        ],
        [
            {"id": "other", "display_name": "홍길동"},
            {"id": "user-1", "display_name": "김수"},
        ],
    ]

    result = reviews("token")["data"]

    query = repo.client.rest_get.call_args_list[0].args[1]
    assert query["or"] == "(status.eq.visible,account_id.eq.user-1)"
    assert result["review_count"] == 1
    assert result["average_rating"] == 5.0
    own = next(item for item in result["items"] if item["id"] == "hidden-own")
    assert own["is_own"] is True
    assert own["status"] == "hidden"
    assert own["account_id"] is None


@patch("app.routers.boards._merchant_admin", return_value=(SimpleNamespace(id="admin"), "m-1"))
@patch("app.routers.boards.JoinRepository")
def test_announcement_delete_is_tenant_scoped(repo_class, _admin):
    repo = repo_class.return_value
    repo.client.rest_delete.return_value = [{"id": "notice-1"}]

    result = delete_announcement("notice-1", "token")

    assert result["data"] == {"deleted": True, "id": "notice-1"}
    assert repo.client.rest_delete.call_args.args == (
        "announcements", {"id": "eq.notice-1", "merchant_id": "eq.m-1"},
    )
