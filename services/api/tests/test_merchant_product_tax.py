from unittest.mock import patch

from app.routers.merchant_admin import create_merchant_product, list_legacy_tax_reviews, list_merchant_products, update_merchant_product
from app.schemas import MerchantProductCreateRequest, MerchantProductUpdateRequest


@patch("app.routers.merchant_admin._merchant_admin", return_value=(object(), "merchant-1"))
@patch("app.routers.merchant_admin.JoinRepository")
def test_merchant_product_create_sets_server_tenant_and_tax(repo_class, _admin):
    repo = repo_class.return_value
    repo.client.rest_post.return_value = [{"id": "product-1", "tax_type": "taxable"}]
    result = create_merchant_product(MerchantProductCreateRequest(name=" meal ", price=9000, tax_type="taxable"), "token")
    table, values = repo.client.rest_post.call_args.args
    assert table == "merchant_products"
    assert values["merchant_id"] == "merchant-1"
    assert values["tax_type"] == "taxable"
    assert values["name"] == "meal"
    assert result["data"]["tax_type"] == "taxable"


@patch("app.routers.merchant_admin._merchant_admin", return_value=(object(), "merchant-1"))
@patch("app.routers.merchant_admin.JoinRepository")
def test_merchant_product_read_and_update_are_tenant_scoped(repo_class, _admin):
    repo = repo_class.return_value
    repo.client.rest_get.side_effect = [
        [{"id": "product-1", "merchant_id": "merchant-1", "tax_type": "tax_free"}],
        [{"id": "product-1"}],
    ]
    repo.client.rest_patch.return_value = [{"id": "product-1", "tax_type": "taxable"}]

    listed = list_merchant_products("token")
    assert listed["data"]["items"][0]["tax_type"] == "tax_free"
    list_params = repo.client.rest_get.call_args_list[0].args[1]
    assert list_params["merchant_id"] == "eq.merchant-1"
    assert "tax_type" in list_params["select"]

    updated = update_merchant_product("product-1", MerchantProductUpdateRequest(tax_type="taxable"), "token")
    lookup = repo.client.rest_get.call_args_list[1].args[1]
    patch_filters = repo.client.rest_patch.call_args.args[1]
    patch_values = repo.client.rest_patch.call_args.args[2]
    assert lookup["merchant_id"] == "eq.merchant-1"
    assert patch_filters == {"id": "eq.product-1", "merchant_id": "eq.merchant-1"}
    assert patch_values["tax_type"] == "taxable"
    assert updated["data"]["tax_type"] == "taxable"


@patch("app.routers.merchant_admin._merchant_admin", return_value=(object(), "merchant-1"))
@patch("app.routers.merchant_admin.JoinRepository")
def test_legacy_payment_review_list_passes_bounded_page_and_server_tenant(repo_class, _admin):
    repo = repo_class.return_value
    repo.client.rpc.return_value = {
        "items": [{"inbox_id": "review-51"}], "total": 101,
        "limit": 50, "offset": 50, "has_more": True,
    }
    result = list_legacy_tax_reviews(limit=50, offset=50, token="tenant-a-token")
    repo.client.rpc.assert_called_once_with("list_legacy_tax_reviews", {
        "p_merchant_id": "merchant-1", "p_limit": 50, "p_offset": 50,
    })
    assert result["data"]["total"] == 101
    assert result["data"]["has_more"] is True
