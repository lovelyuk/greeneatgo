from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class RefundQuote:
    refundable: bool
    refund_amount: int
    point_amount: int
    refunded_voucher_count: int
    forfeited_voucher_count: int
    reason: str | None = None


def _krw(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calculate_refund(order: dict, vouchers: list[dict], *, already_refunded: int = 0) -> RefundQuote:
    """Pure quote helper; the claim RPC repeats this under row locks at confirmation."""
    if order.get("status") != "done" or order.get("pay_type") not in {"voucher", "subsidized"}:
        return RefundQuote(False, 0, 0, 0, 0, "ORDER_NOT_REFUNDABLE")
    used = sum(1 for voucher in vouchers if voucher.get("status") == "used")
    if order["pay_type"] == "subsidized":
        if used:
            return RefundQuote(False, 0, 0, 0, 0, "ORDER_ALREADY_USED")
        unused = sum(1 for voucher in vouchers if voucher.get("status") == "unused")
        if not unused:
            return RefundQuote(False, 0, 0, 0, 0, "NO_UNUSED_VOUCHER")
        return RefundQuote(True, int(order.get("amount") or 0), int(order.get("point_amount") or 0), 1, 0)

    paid = int(order.get("paid_voucher_count") or 0)
    if paid <= 0:
        return RefundQuote(False, 0, 0, 0, 0, "INVALID_PURCHASE_SNAPSHOT")
    paid_remaining = max(paid - used, 0)
    bonus_remaining = sum(
        1 for voucher in vouchers
        if voucher.get("status") == "unused" and int(voucher.get("issue_index") or 0) > paid
    )
    if paid_remaining == 0:
        # There is no cash to return, but the remaining free benefit still has
        # to be closed as forfeited so it cannot be consumed after the order is
        # considered refunded.
        return RefundQuote(bonus_remaining > 0, 0, 0, 0, bonus_remaining, "PAID_VOUCHERS_EXHAUSTED")
    unit = _krw(Decimal(int(order.get("amount") or 0)) / Decimal(paid))
    balance = max(int(order.get("amount") or 0) - int(already_refunded), 0)
    amount = min(unit * paid_remaining, balance)
    return RefundQuote(True, amount, 0, paid_remaining, bonus_remaining)
