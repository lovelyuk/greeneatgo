from __future__ import annotations

from typing import Any
from urllib.parse import urlencode, urlsplit


_RECEIPT_HOSTS = {
    "api.kiwoompay.co.kr": ("agent.kiwoompay.co.kr", True),
    "apitest.kiwoompay.co.kr": ("agenttest.kiwoompay.co.kr", False),
}


def _text(value: Any) -> str | None:
    """Return a non-empty scalar provider value, never a serialized structure."""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    result = str(value).strip()
    return result or None


def _masked_card_number(value: Any) -> str | None:
    # Provider CARDNO formatting varies. Discard everything except digits and
    # reveal only the final four; malformed short values are not presented.
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if len(digits) < 4:
        return None
    return f"****-****-****-{digits[-4:]}"


def _receipt_origin(base_url: str) -> tuple[str, bool] | None:
    """Map only the two documented API environments to receipt agents.

    Receipt links must never inherit a configurable or user-controlled host.
    Requiring an exact HTTPS API origin makes an unknown/malformed environment
    fail closed by returning no links.
    """
    if not isinstance(base_url, str) or "?" in base_url or "#" in base_url:
        return None
    try:
        parsed = urlsplit(base_url)
        invalid_origin = (
            parsed.scheme.lower() != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.path not in ("", "/")
            or bool(parsed.query)
            or bool(parsed.fragment)
        )
    except (TypeError, ValueError):
        return None
    if invalid_origin:
        return None
    mapped = _RECEIPT_HOSTS.get((parsed.hostname or "").lower())
    if mapped is None:
        return None
    receipt_host, supports_cash_receipt = mapped
    return f"https://{receipt_host}/common", supports_cash_receipt


def _receipt_urls(
    base_url: str,
    cpid: str,
    transaction_id: str | None,
    payment_method: str | None,
    cash_receipt_authorization_number: str | None,
) -> dict[str, str | None]:
    result: dict[str, str | None] = {
        "receipt_url": None,
        "cash_receipt_url": None,
        "transaction_confirmation_url": None,
    }
    mapped = _receipt_origin(base_url)
    if mapped is None or not transaction_id:
        return result

    origin, supports_cash_receipt = mapped
    transaction_query = urlencode({"DAOUTRX": transaction_id})
    approval_query = urlencode({"DAOUTRX": transaction_id, "STATUS": "A"})
    if payment_method == "CARD":
        result["receipt_url"] = f"{origin}/PayInfoPrintDirectCard.jsp?{approval_query}"
    elif payment_method == "BANK":
        result["receipt_url"] = f"{origin}/PayInfoPrintBank.jsp?{approval_query}"

    if supports_cash_receipt and payment_method == "BANK" and cash_receipt_authorization_number:
        result["cash_receipt_url"] = f"{origin}/CashRecInfoPrint.jsp?{transaction_query}"
    if cpid:
        result["transaction_confirmation_url"] = (
            f"{origin}/PayInfoPrint.jsp?{urlencode({'CPID': cpid, 'DAOUTRX': transaction_id})}"
        )
    return result


def _issued_count(order: dict[str, Any]) -> int | None:
    if order.get("pay_type") not in {"voucher", "subsidized"}:
        return None
    try:
        if order.get("voucher_count") is not None:
            return int(order["voucher_count"])
        paid = order.get("paid_voucher_count")
        bonus = order.get("bonus_voucher_count")
        if paid is not None and bonus is not None:
            return int(paid) + int(bonus)
    except (TypeError, ValueError):
        return None
    return None


def payment_receipt_method(order: dict[str, Any]) -> str | None:
    """Resolve the provider document type without relabeling the payment method."""
    method = _text(order.get("payment_method"))
    method = method.upper() if method else None
    if method in {"CARD", "BANK"}:
        return method
    payload = order.get("provider_response")
    provider = payload if isinstance(payload, dict) else {}
    payment_type = _text(provider.get("PAYMENTTYPE"))
    payment_type = payment_type.upper() if payment_type else None
    return payment_type if payment_type in {"CARD", "BANK"} else None


def payment_receipt_links(order: dict[str, Any], *, base_url: str, cpid: str) -> dict[str, str | None]:
    """Build official receipt URLs from authoritative payment-order columns."""
    payload = order.get("provider_response")
    provider = payload if isinstance(payload, dict) else {}
    receipt_method = payment_receipt_method(order)
    transaction_id = _text(order.get("provider_payment_key"))
    cash_authorization = _text(provider.get("CASHRECAUTHNO"))
    return _receipt_urls(base_url, cpid, transaction_id, receipt_method, cash_authorization)


def present_payment_completion(order: dict[str, Any], *, base_url: str, cpid: str) -> dict[str, Any]:
    """Build the public completion DTO from authoritative order columns.

    Provider payload data is allow-listed field by field. Database IDs and the
    original provider payload are deliberately never copied into the response.
    """
    payload = order.get("provider_response")
    provider = payload if isinstance(payload, dict) else {}
    method = _text(order.get("payment_method"))
    method = method.upper() if method else None
    transaction_id = _text(order.get("provider_payment_key"))
    cash_authorization = _text(provider.get("CASHRECAUTHNO"))
    receipt_method = payment_receipt_method(order)
    links = payment_receipt_links(order, base_url=base_url, cpid=cpid)
    issued_count = _issued_count(order)
    cash_receipt_status = "ISSUED" if links["cash_receipt_url"] else None
    method_label = {"CARD": "카드", "BANK": "계좌이체", "NAVERPAY": "네이버페이"}.get(method, method) if method else None

    return {
        "order_id": _text(order.get("order_id")),
        "status": _text(order.get("status")),
        "product_name": _text(order.get("product_name")),
        "merchant_name": _text(order.get("merchant_name")),
        "amount": order.get("amount"),
        "pay_type": _text(order.get("pay_type")),
        "payment": {
            "method": method,
            "method_label": method_label,
            "approved_at": order.get("approved_at"),
            "transaction_id": transaction_id,
            "issuer_name": _text(provider.get("CARDNAME")) if receipt_method == "CARD" else None,
            "masked_card_number": (
                _masked_card_number(provider.get("CARDNO")) if receipt_method == "CARD" else None
            ),
            "authorization_number": _text(provider.get("AUTHNO")),
            "bank_name": _text(provider.get("BANKNAME")) if method == "BANK" else None,
            "cash_receipt_authorization_number": (
                cash_authorization if method == "BANK" else None
            ),
            "cash_receipt_status": cash_receipt_status,
        },
        "receipts": {
            "sales_slip_url": links["receipt_url"],
            "cash_receipt_url": links["cash_receipt_url"],
            "transaction_confirmation_url": links["transaction_confirmation_url"],
        },
        "issued_count": issued_count,
        "voucher_balance": None,
        # Existing clients accept either a nested fulfillment result or these
        # same values at the top level. Keep both without querying or changing
        # fulfillment storage.
        "fulfillment": {
            "issued_count": issued_count,
            "voucher_balance": None,
        },
    }
