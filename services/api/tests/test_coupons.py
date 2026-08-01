from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.routers.coupons import (
    CouponCreateRequest,
    CouponUpdateRequest,
    create_coupon,
    delete_coupon,
    update_coupon,
)


@patch("app.routers.coupons._merchant_admin", return_value=(SimpleNamespace(id="admin-1"), "merchant-1"))
@patch("app.routers.coupons.JoinRepository")
def test_coupon_create_is_tenant_and_actor_scoped(repo_class, _merchant_admin):
    repo = repo_class.return_value
    repo.client.rest_post.return_value = [{"id": "coupon-1", "name": "점심 10%"}]

    result = create_coupon(CouponCreateRequest.model_validate({
        "name": " 점심 10% ", "discount_type": "percent", "discount_value": "10",
    }), "token")

    assert result["data"]["id"] == "coupon-1"
    table, values = repo.client.rest_post.call_args.args
    assert table == "merchant_coupons"
    assert values["merchant_id"] == "merchant-1"
    assert values["created_by"] == "admin-1"
    assert values["name"] == "점심 10%"


def test_coupon_policy_rejects_invalid_percent_and_period():
    with pytest.raises(ValidationError):
        CouponCreateRequest.model_validate({"name": "무료", "discount_type": "percent", "discount_value": 100})
    with pytest.raises(ValidationError):
        CouponCreateRequest.model_validate({
            "name": "기간 오류", "discount_type": "fixed", "discount_value": 1000,
            "valid_from": "2026-08-10", "valid_until": "2026-08-01",
        })


@patch("app.routers.coupons._merchant_admin", return_value=(SimpleNamespace(id="admin-1"), "merchant-1"))
@patch("app.routers.coupons.JoinRepository")
def test_coupon_update_validates_merged_policy_and_is_tenant_scoped(repo_class, _merchant_admin):
    repo = repo_class.return_value
    repo.client.rest_get.return_value = [{
        "id": "coupon-1", "name": "천원 할인", "discount_type": "fixed",
        "discount_value": "1000", "valid_from": None, "valid_until": None,
        "is_active": True,
    }]
    repo.client.rest_patch.return_value = [{"id": "coupon-1", "is_active": False}]

    update_coupon("coupon-1", CouponUpdateRequest(is_active=False), "token")

    assert repo.client.rest_get.call_args.args[1]["merchant_id"] == "eq.merchant-1"
    assert repo.client.rest_patch.call_args.args[1] == {
        "id": "eq.coupon-1", "merchant_id": "eq.merchant-1",
    }
    assert repo.client.rest_patch.call_args.args[2]["is_active"] is False


@patch("app.routers.coupons._merchant_admin", return_value=(SimpleNamespace(id="admin-1"), "merchant-1"))
@patch("app.routers.coupons.JoinRepository")
def test_coupon_delete_is_tenant_scoped(repo_class, _merchant_admin):
    repo = repo_class.return_value
    repo.client.rest_delete.return_value = [{"id": "coupon-1"}]

    result = delete_coupon("coupon-1", "token")

    assert result["data"] == {"deleted": True, "id": "coupon-1"}
    assert repo.client.rest_delete.call_args.args == (
        "merchant_coupons", {"id": "eq.coupon-1", "merchant_id": "eq.merchant-1"},
    )
