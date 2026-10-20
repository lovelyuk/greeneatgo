"""Tap&Pick kiosk paper receipt check.

The kiosk prints a QR whose value is the 24-hex receipt id (e.g.
6ad6e86b3bea82fef79ff23b). ``GET {base}/payment/{id}/verify`` returns
``{"result": 0}`` for a valid receipt; any other code is a rejection.
Usage (one receipt = one meal) is recorded by GreenEat, not by the kiosk.
"""
from __future__ import annotations

import json
import re
import ssl
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# 24 hex chars; scanners may add an AIM prefix (e.g. "]Q1") and CR/LF.
RECEIPT_RE = re.compile(r"^(?:\][A-Za-z]\d)?([0-9a-fA-F]{24})$")
SUCCESS = 0


class KioskReceiptError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, provider_result: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.provider_result = provider_result


@dataclass(frozen=True)
class VerifiedReceipt:
    receipt_id: str
    provider_result: int


def extract_receipt_id(raw: str) -> str | None:
    """Pull the 24-hex receipt id out of scanner input (prefix/suffix tolerant)."""
    if not raw:
        return None
    match = RECEIPT_RE.match(raw.strip())
    return match.group(1).lower() if match else None


def verify(receipt_id: str, *, base_url: str, timeout: float = 4.0, opener=None) -> VerifiedReceipt:
    opener = opener or urlopen
    if not base_url:
        raise KioskReceiptError("KIOSK_NOT_CONFIGURED", "키오스크 영수증 연동이 아직 설정되지 않았어요", 503)
    url = f"{base_url.rstrip('/')}/payment/{receipt_id}/verify"
    req = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        # Certificate verification stays ON: an invalid/expired provider
        # certificate must fail closed, never be bypassed.
        with opener(req, timeout=timeout, context=ssl.create_default_context()) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        raise KioskReceiptError("KIOSK_UNAVAILABLE", "키오스크 영수증을 확인하지 못했어요. 잠시 후 다시 찍어 주세요", 503) from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise KioskReceiptError("KIOSK_UNAVAILABLE", "키오스크 영수증을 확인하지 못했어요. 잠시 후 다시 찍어 주세요", 503) from exc
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, int) or isinstance(result, bool):
        raise KioskReceiptError("KIOSK_UNAVAILABLE", "키오스크 영수증 응답을 확인하지 못했어요", 503)
    if result == SUCCESS:
        return VerifiedReceipt(receipt_id=receipt_id, provider_result=result)
    # Only 0 is success; every other code (1000 not found, 1, …) is one message.
    raise KioskReceiptError("KIOSK_RECEIPT_INVALID", "사용할 수 없는 영수증이에요", 400, result)
