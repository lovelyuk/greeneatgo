from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import parse_qs, unquote, urlparse


def calculate_sale_price(unit_price: Decimal | str | int, voucher_count: int, discount_rate: Decimal | str | int) -> Decimal:
    price = Decimal(str(unit_price))
    discount = Decimal(str(discount_rate))
    if price <= 0 or voucher_count <= 0 or discount < 0 or discount >= 100:
        raise ValueError("invalid voucher product price")
    return (price * voucher_count * (Decimal("100") - discount) / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def krw_amount(value: Decimal | str | int) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def per_voucher_price(charged_amount: Decimal | str | int, total_count: int) -> Decimal:
    if total_count <= 0:
        raise ValueError("total_count must be positive")
    return (Decimal(str(charged_amount)) / total_count).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def resolve_voucher_merchant(repo, pilot_merchant_id: str | None) -> dict | None:
    """Resolve the only merchant exposed by the pilot voucher surface."""
    params = {"select": "id,name,status", "status": "eq.active", "limit": "1"}
    if pilot_merchant_id:
        params["id"] = f"eq.{pilot_merchant_id}"
    else:
        params["order"] = "created_at.asc,id.asc"
    rows = repo.client.rest_get("merchants", params)
    return rows[0] if rows else None


def parse_qr_data(qr_data: str) -> tuple[str, str]:
    """Return (lookup column, value), retaining legacy raw token and URL formats."""
    value = unquote(qr_data.strip())
    if value.startswith("restaurant:"):
        restaurant_id = value.split(":", 1)[1].strip()
        if not restaurant_id:
            raise ValueError("empty restaurant id")
        return "id", restaurant_id
    if "://" in value:
        parsed = urlparse(value)
        query = parse_qs(parsed.query)
        for key in ("qr_token", "token", "qr"):
            if query.get(key) and query[key][0]:
                return parse_qr_data(query[key][0])
        segment = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if segment:
            return parse_qr_data(segment)
        raise ValueError("empty QR URL")
    if not value:
        raise ValueError("empty QR")
    return "qr_token", value
