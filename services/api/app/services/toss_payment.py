from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class TossPaymentError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TossConfirmInput:
    payment_key: str
    order_id: str
    amount: int


def validate_confirm_input(*, expected_order_id: str, expected_amount: int, payload: TossConfirmInput) -> None:
    if payload.order_id != expected_order_id:
        raise TossPaymentError(400, "ORDER_ID_MISMATCH", "주문번호가 일치하지 않아요")
    if payload.amount != expected_amount:
        raise TossPaymentError(400, "AMOUNT_MISMATCH", "결제 금액이 주문 금액과 일치하지 않아요")


def confirm_payment(secret_key: str, payload: TossConfirmInput) -> dict[str, Any]:
    credentials = base64.b64encode(f"{secret_key}:".encode()).decode()
    body = json.dumps({
        "paymentKey": payload.payment_key,
        "orderId": payload.order_id,
        "amount": payload.amount,
    }).encode("utf-8")
    request = Request(
        "https://api.tosspayments.com/v1/payments/confirm",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Idempotency-Key": payload.order_id,
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        text = exc.read().decode("utf-8")
        try:
            error = json.loads(text)
        except json.JSONDecodeError:
            error = {}
        raise TossPaymentError(
            exc.code,
            str(error.get("code") or "TOSS_PAYMENT_ERROR"),
            str(error.get("message") or "토스페이먼츠 결제 승인에 실패했어요"),
        ) from exc
