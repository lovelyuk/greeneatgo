from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import parse_qs, unquote, urlparse


def calculate_sale_price(
    unit_price: Decimal | str | int,
    voucher_count: int,
    discount_rate: Decimal | str | int,
    discount_amount_per_voucher: Decimal | str | int = 0,
) -> Decimal:
    price = Decimal(str(unit_price))
    discount = Decimal(str(discount_rate))
    fixed_discount = Decimal(str(discount_amount_per_voucher))
    discounted_unit = price * (Decimal("100") - discount) / Decimal("100") - fixed_discount
    if (
        price <= 0 or voucher_count <= 0 or discount < 0 or discount >= 100
        or fixed_discount < 0 or (discount > 0 and fixed_discount > 0) or discounted_unit <= 0
    ):
        raise ValueError("invalid voucher product price")
    sale_price = (discounted_unit * voucher_count).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if sale_price <= 0 or sale_price > Decimal("999999999999.99"):
        raise ValueError("invalid voucher product sale price")
    return sale_price


def krw_amount(value: Decimal | str | int) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def per_voucher_price(charged_amount: Decimal | str | int, total_count: int) -> Decimal:
    if total_count <= 0:
        raise ValueError("total_count must be positive")
    return (Decimal(str(charged_amount)) / total_count).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def resolve_voucher_merchant_client(client, pilot_merchant_id: str | None) -> dict | None:
    """Resolve the only merchant exposed by the pilot voucher surface."""
    params = {"select": "id,name,status", "status": "eq.active", "limit": "1"}
    if pilot_merchant_id:
        params["id"] = f"eq.{pilot_merchant_id}"
    else:
        params["order"] = "created_at.asc,id.asc"
    rows = client.rest_get("merchants", params)
    return rows[0] if rows else None


def resolve_voucher_merchant(repo, pilot_merchant_id: str | None) -> dict | None:
    return resolve_voucher_merchant_client(repo.client, pilot_merchant_id)


def _batched_lookup(repo, table: str, *, id_field: str, ids: list[str], select: str, chunk_size: int = 100) -> list[dict]:
    rows: list[dict] = []
    for offset in range(0, len(ids), chunk_size):
        chunk = ids[offset:offset + chunk_size]
        rows.extend(repo.client.rest_get(table, params={
            "select": select,
            id_field: f"in.({','.join(chunk)})",
        }))
    return rows


def decorate_bonus_voucher_transactions(repo, rows: list[dict]) -> None:
    """Mark voucher use rows from immutable issuance order metadata.

    A zero amount is not sufficient evidence of a bonus: discounted or subsidized
    paid vouchers can also allocate to zero.  The authoritative rule is that an
    issued voucher is a bonus only when its issue index is greater than the
    purchase order's paid voucher count.
    """
    candidates = [row for row in rows if row.get("pay_type") == "voucher" and row.get("voucher_id")]
    for row in candidates:
        row["is_bonus"] = False
    if not candidates:
        return

    voucher_ids = sorted({str(row["voucher_id"]) for row in candidates})
    vouchers = _batched_lookup(
        repo,
        "vouchers",
        id_field="id",
        ids=voucher_ids,
        select="id,order_id,issue_index",
    )
    voucher_by_id = {str(row["id"]): row for row in vouchers if row.get("id")}
    order_ids = sorted({str(row["order_id"]) for row in vouchers if row.get("order_id")})
    orders = repo.client.rest_get(
        "payment_orders",
        {"select": "id,paid_voucher_count", "id": f"in.({','.join(order_ids)})"},
    ) if order_ids else []
    paid_counts = {str(row["id"]): row.get("paid_voucher_count") for row in orders if row.get("id")}

    for row in candidates:
        voucher = voucher_by_id.get(str(row["voucher_id"]))
        if not voucher:
            continue
        try:
            issue_index = int(voucher.get("issue_index"))
            paid_count = int(paid_counts[str(voucher.get("order_id"))])
        except (KeyError, TypeError, ValueError):
            continue
        row["is_bonus"] = issue_index > paid_count


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
