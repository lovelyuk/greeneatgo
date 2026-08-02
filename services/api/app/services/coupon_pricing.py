from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
from typing import Any


def coupon_is_valid(coupon: dict[str, Any], *, today: date | None = None) -> bool:
    current = today or datetime.now(timezone(timedelta(hours=9))).date()
    if not coupon.get("is_active"):
        return False

    def parsed(value: object) -> date | None:
        if isinstance(value, date):
            return value
        if isinstance(value, str) and value:
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        return None

    valid_from = parsed(coupon.get("valid_from"))
    valid_until = parsed(coupon.get("valid_until"))
    return not ((valid_from is not None and current < valid_from) or (valid_until is not None and current > valid_until))


def coupon_snapshot(coupon: dict[str, Any]) -> dict[str, Any]:
    """Return only immutable promotion facts needed to explain an order."""
    return {
        "id": str(coupon["id"]),
        "merchant_id": str(coupon["merchant_id"]),
        "name": str(coupon["name"]),
        "discount_type": str(coupon["discount_type"]),
        "discount_value": str(coupon["discount_value"]),
        "valid_from": coupon.get("valid_from"),
        "valid_until": coupon.get("valid_until"),
    }


def calculate_coupon_discount(gross_amount: int, coupon: dict[str, Any] | None) -> int:
    """Calculate a whole-KRW discount while retaining a positive pre-point total.

    Promotion coupons never create a zero-priced order themselves. This is
    especially important for ordinary voucher purchases, which must always enter
    the external PG with a positive amount. Subsidized employees may subsequently
    reduce the remaining amount to zero with their points.
    """
    if gross_amount <= 0:
        raise ValueError("gross_amount must be positive")
    if coupon is None:
        return 0
    value = Decimal(str(coupon["discount_value"]))
    discount_type = coupon.get("discount_type")
    if discount_type == "percent":
        discount = int((Decimal(gross_amount) * value / Decimal("100")).to_integral_value(rounding=ROUND_FLOOR))
    elif discount_type == "fixed":
        discount = int(value.to_integral_value(rounding=ROUND_FLOOR))
    else:
        raise ValueError("unsupported coupon discount type")
    return max(0, min(discount, gross_amount - 1))


def build_quote(
    *,
    gross_amount: int,
    coupon: dict[str, Any] | None,
    requested_point_amount: int | None,
    available_point_amount: int,
    points_allowed: bool,
) -> dict[str, Any]:
    discount = calculate_coupon_discount(gross_amount, coupon)
    after_coupon = gross_amount - discount
    available = max(int(available_point_amount), 0) if points_allowed else 0
    if points_allowed:
        requested = available if requested_point_amount is None else requested_point_amount
        point_amount = max(0, min(int(requested), available, after_coupon))
    else:
        point_amount = 0
    return {
        "gross_amount": gross_amount,
        "coupon_id": str(coupon["id"]) if coupon else None,
        "coupon_discount_amount": discount,
        "amount_after_coupon": after_coupon,
        "requested_point_amount": requested_point_amount,
        "available_point_amount": available,
        "point_amount": point_amount,
        "payment_amount": after_coupon - point_amount,
    }
