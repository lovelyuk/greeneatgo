from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RefundQuote:
    refundable: bool
    refund_amount: int
    point_amount: int
    refunded_voucher_count: int
    forfeited_voucher_count: int
    reason: str | None = None


def calculate_refund(order: dict, vouchers: list[dict], *, already_refunded: int = 0) -> RefundQuote:
    """Pure quote helper; the claim RPC repeats this under row locks at confirmation."""
    if order.get("status") != "done" or order.get("pay_type") not in {"voucher", "subsidized"}:
        return RefundQuote(False, 0, 0, 0, 0, "ORDER_NOT_REFUNDABLE")
    used = sum(1 for voucher in vouchers if voucher.get("status") == "used")
    if order["pay_type"] == "subsidized":
        paid = int(order.get("paid_voucher_count") or 1)
        paid_remaining = sum(1 for voucher in vouchers if voucher.get("status") == "unused" and int(voucher.get("issue_index") or 0) <= paid)
        bonus_remaining = sum(1 for voucher in vouchers if voucher.get("status") == "unused" and int(voucher.get("issue_index") or 0) > paid)
        if paid_remaining <= 0:
            reason = "ORDER_ALREADY_USED" if paid == 1 and used else "PAID_VOUCHERS_EXHAUSTED"
            return RefundQuote(bonus_remaining > 0, 0, 0, 0, bonus_remaining, reason)
        if not vouchers:
            return RefundQuote(False, 0, 0, 0, 0, "NO_UNUSED_VOUCHER")
        used_paid = min(max(paid - paid_remaining, 0), paid)
        # Fulfillment puts the integer-division remainder on the lowest paid
        # issue indexes, and paid indexes are consumed FIFO. Reconstruct those
        # exact snapshots rather than independently prorating card and points
        # (which can create money when both components round up).
        card_total = max(int(order.get("amount") or 0), 0)
        point_total = max(int(order.get("point_amount") or 0), 0)
        employee_total = max(int(order.get("total_employee_burden") or (card_total + point_total)), 0)
        base, remainder = divmod(employee_total, paid)
        refundable_burden = employee_total - (base * used_paid + min(used_paid, remainder))
        # A valid DB snapshot has employee_total == card_total + point_total.
        # Cap corrupted historical/input data because no exact split can exceed
        # both original components and still sum to an inconsistent larger total.
        refundable_burden = min(max(refundable_burden, 0), card_total + point_total)

        # Preserve the old deterministic point-first proration preference, but
        # constrain the final split to the conserved burden and both original
        # component totals. The card-cap adjustment makes the sum exact even for
        # defensive handling of malformed historical snapshots.
        point_refund = point_total - (point_total * used_paid // paid)
        point_refund = min(max(point_refund, 0), point_total, refundable_burden)
        card_refund = refundable_burden - point_refund
        if card_refund > card_total:
            point_refund += card_refund - card_total
            card_refund = card_total
        point_refund = min(point_refund, point_total)
        card_refund = max(refundable_burden - point_refund, 0)
        return RefundQuote(True, card_refund, point_refund, paid_remaining, bonus_remaining)

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
    original_amount = int(order.get("amount") or 0)
    used_paid = paid - paid_remaining
    conserved_refund = original_amount - (original_amount * used_paid // paid)
    balance = max(original_amount - int(already_refunded), 0)
    amount = min(conserved_refund, balance)
    return RefundQuote(True, amount, 0, paid_remaining, bonus_remaining)
