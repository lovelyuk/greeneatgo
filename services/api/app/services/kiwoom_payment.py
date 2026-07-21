from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class KiwoomPaymentError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class KiwoomHashInput:
    cpid: str
    order_id: str
    amount: int
    payment_type: str = "W"
    pay_method: str = "TOTAL"


def _decode_response(raw: bytes, charset: str | None = None) -> str:
    for encoding in (charset, "utf-8", "euc-kr", "cp949"):
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def _json_response(response: Any) -> dict[str, Any]:
    charset = response.headers.get_content_charset() if getattr(response, "headers", None) else None
    text = _decode_response(response.read(), charset)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise KiwoomPaymentError(502, "KIWOOMPAY_INVALID_RESPONSE", "키움페이 응답 형식이 올바르지 않아요") from exc
    if not isinstance(value, dict):
        raise KiwoomPaymentError(502, "KIWOOMPAY_INVALID_RESPONSE", "키움페이 응답 형식이 올바르지 않아요")
    return value


def _request_json(
    url: str,
    payload: dict[str, str],
    *,
    headers: dict[str, str] | None = None,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(encoding)
    request = Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": f"application/json;charset={encoding.upper()}", **(headers or {})},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return _json_response(response)
    except HTTPError as exc:
        text = _decode_response(exc.read(), exc.headers.get_content_charset() if exc.headers else None)
        try:
            error = json.loads(text)
        except json.JSONDecodeError:
            error = {}
        raise KiwoomPaymentError(
            exc.code,
            str(error.get("RESULTCODE") or error.get("code") or "KIWOOMPAY_HTTP_ERROR"),
            str(error.get("ERRORMESSAGE") or error.get("message") or "키움페이 요청에 실패했어요"),
        ) from exc
    except URLError as exc:
        raise KiwoomPaymentError(502, "KIWOOMPAY_NETWORK_ERROR", "키움페이에 연결하지 못했어요") from exc


def request_payment_hash(base_url: str, payload: KiwoomHashInput) -> str:
    if payload.amount <= 0:
        raise KiwoomPaymentError(400, "INVALID_AMOUNT", "결제 금액이 올바르지 않아요")
    response = _request_json(
        f"{base_url.rstrip('/')}/pay/hash",
        {
            "PAYMETHOD": payload.pay_method,
            "TYPE": payload.payment_type,
            "CPID": payload.cpid,
            "ORDERNO": payload.order_id,
            "AMOUNT": str(payload.amount),
        },
    )
    if str(response.get("RESULTCODE")) != "0000" or not response.get("KIWOOM_ENC"):
        raise KiwoomPaymentError(
            502,
            str(response.get("RESULTCODE") or "KIWOOMPAY_HASH_FAILED"),
            str(response.get("ERRORMESSAGE") or "키움페이 결제 보안값을 발급하지 못했어요"),
        )
    return str(response["KIWOOM_ENC"])


def _validate_cancel_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "kiwoompay.co.kr" or host.endswith(".kiwoompay.co.kr")):
        raise KiwoomPaymentError(502, "KIWOOMPAY_INVALID_CANCEL_URL", "키움페이 취소 URL 검증에 실패했어요")


def cancel_payment(
    base_url: str,
    authorization_key: str,
    cpid: str,
    transaction_id: str,
    cancel_amount: int,
    *,
    pay_method: str = "CARD",
    cancel_reason: str = "구매주문환불",
    tax_free_amount: int | None = None,
) -> dict[str, Any]:
    if cancel_amount <= 0:
        raise KiwoomPaymentError(400, "INVALID_CANCEL_AMOUNT", "환불 금액이 올바르지 않아요")
    if tax_free_amount is not None and not 0 <= tax_free_amount <= cancel_amount:
        raise KiwoomPaymentError(400, "INVALID_TAX_FREE_AMOUNT", "비과세 환불 금액이 올바르지 않아요")
    if not authorization_key:
        raise KiwoomPaymentError(503, "KIWOOMPAY_AUTH_NOT_CONFIGURED", "키움페이 취소 인증키가 설정되지 않았어요")

    ready = _request_json(
        f"{base_url.rstrip('/')}/pay/ready",
        {"CPID": cpid, "PAYMETHOD": pay_method, "CANCELREQ": "Y"},
        headers={"Authorization": authorization_key},
        encoding="euc-kr",
    )
    return_url, token = str(ready.get("RETURNURL") or ""), str(ready.get("TOKEN") or "")
    if not return_url or not token:
        raise KiwoomPaymentError(502, "KIWOOMPAY_CANCEL_READY_FAILED", "키움페이 취소 준비에 실패했어요")
    _validate_cancel_url(return_url)

    body = {
        "CPID": cpid,
        "TRXID": transaction_id,
        "AMOUNT": str(cancel_amount),
        "CANCELREASON": cancel_reason.replace("|", " ")[:20],
    }
    if tax_free_amount is not None:
        body["TAXFREEAMT"] = str(tax_free_amount)
    result = _request_json(
        return_url,
        body,
        headers={"Authorization": authorization_key, "TOKEN": token},
        encoding="euc-kr",
    )
    if str(result.get("RESULTCODE")) != "0000":
        raise KiwoomPaymentError(
            502,
            str(result.get("RESULTCODE") or "KIWOOMPAY_CANCEL_FAILED"),
            str(result.get("ERRORMESSAGE") or "키움페이 환불에 실패했어요"),
        )
    if str(result.get("TOKEN") or "") != token:
        raise KiwoomPaymentError(502, "KIWOOMPAY_TOKEN_MISMATCH", "키움페이 취소 응답 검증에 실패했어요")
    if int(result.get("AMOUNT") or 0) != cancel_amount:
        raise KiwoomPaymentError(502, "KIWOOMPAY_CANCEL_AMOUNT_MISMATCH", "키움페이 실제 환불 금액이 요청과 달라요")
    return result
