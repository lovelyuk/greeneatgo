from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.routers.coupons import customer_coupons
from app.routers.voucher_products import purchase
from app.schemas import VoucherPurchaseRequest
from app.services.coupon_pricing import build_quote, calculate_coupon_discount, coupon_is_valid


def coupon(**overrides):
    return {
        "id": "coupon-123", "merchant_id": "merchant-1", "name": "promotion",
        "discount_type": "percent", "discount_value": Decimal("12.5"),
        "valid_from": None, "valid_until": None, "is_active": True, **overrides,
    }


def test_coupon_math_floors_percent_and_caps_fixed_to_positive_pg_amount():
    assert calculate_coupon_discount(9999, coupon()) == 1249
    assert calculate_coupon_discount(5000, coupon(discount_type="fixed", discount_value="9000")) == 4999
    assert build_quote(
        gross_amount=10000, coupon=coupon(), requested_point_amount=2000,
        available_point_amount=1500, points_allowed=True,
    )["payment_amount"] == 7250


def test_quote_response_exposes_flutter_final_amount_alias():
    from app.routers.voucher_products import _quote_payload

    result = _quote_payload(
        product={"id": "product-123", "name": "package"},
        merchant={"id": "merchant-1", "name": "pilot"},
        gross=10000,
        coupon=coupon(),
        requested_points=1500,
        available_points=1500,
        points_allowed=True,
    )
    assert result["amount"] == result["payment_amount"] == 7250


def test_coupon_date_policy_is_inclusive_and_active():
    today = date(2026, 8, 2)
    assert coupon_is_valid(coupon(valid_from="2026-08-02", valid_until="2026-08-02"), today=today)
    assert not coupon_is_valid(coupon(valid_until="2026-08-01"), today=today)
    assert not coupon_is_valid(coupon(is_active=False), today=today)


@patch("app.routers.coupons.get_settings")
@patch("app.routers.coupons.JoinRepository")
def test_customer_coupon_catalog_is_pilot_scoped_date_filtered_and_reusable(repo_class, settings):
    repo = repo_class.return_value
    settings.return_value.pilot_merchant_id = "merchant-1"
    repo.auth_user_from_token.return_value = SimpleNamespace(id="auth", email="user@example.com")
    repo.get_profile.return_value = SimpleNamespace(id="user-1", role="customer", status="active")
    repo.client.rest_get.side_effect = [
        [{"id": "merchant-1", "name": "pilot"}],
        [coupon(), coupon(id="expired-1", valid_until="2020-01-01")],
    ]

    data = customer_coupons("token")["data"]

    assert [row["id"] for row in data["items"]] == ["coupon-123"]
    assert data["merchant"] == {"id": "merchant-1", "name": "pilot"}
    params = repo.client.rest_get.call_args_list[1].args[1]
    assert params["merchant_id"] == "eq.merchant-1"
    assert "user_id" not in params


@patch("app.routers.voucher_products.get_settings")
@patch("app.routers.voucher_products.JoinRepository")
def test_purchase_recalculates_coupon_and_persists_snapshots(repo_class, settings):
    repo = repo_class.return_value
    settings.return_value.pilot_merchant_id = "merchant-1"
    settings.return_value.public_api_base_url = "https://api.example"
    repo.auth_user_from_token.return_value = SimpleNamespace(id="auth", email="user@example.com")
    repo.get_profile.return_value = SimpleNamespace(id="user-1", role="customer", status="active")
    product = {
        "id": "product-123", "merchant_id": "merchant-1", "name": "package",
        "voucher_count": 10, "bonus_count": 1, "sale_price": 10000,
        "status": "active", "is_event": False, "tax_type": "taxable",
        "kiwoom_pay_method": "TOTAL",
    }
    repo.client.rest_get.side_effect = [
        [{"id": "merchant-1", "name": "pilot"}], [product], [coupon()],
    ]
    repo.client.rest_post.return_value = [{"id": "db-order", "amount": 8750}]

    data = purchase(VoucherPurchaseRequest(
        product_id="product-123", coupon_id="coupon-123", requested_point_amount=0,
    ), "token")["data"]

    values = repo.client.rest_post.call_args.args[1]
    assert data["amount"] == 8750
    assert values["gross_amount"] == 10000
    assert values["amount"] == 8750
    assert values["coupon_discount_amount"] == 1250
    assert values["coupon_snapshot"]["name"] == "promotion"
    assert values["requested_point_amount"] == 0


def test_coupon_migration_contains_selected_point_cap_and_idempotent_fulfillment_redemption():
    sql = open("../../infra/migrations/0059_coupon_checkout_pricing.sql", encoding="utf-8").read().lower()
    assert "coalesce(o.requested_point_amount,employee_due)" in sql
    assert "old.fulfilled_at is null and new.fulfilled_at is not null" in sql
    assert "unique(order_id)" in sql
    assert "on conflict(order_id) do nothing" in sql
    assert "complete_kiwoom_payment_notification" not in sql
