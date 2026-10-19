"""Member meal QR: short-lived, signed, digits-only token shown on the buyer's phone.

The counter scanner (e.g. Newland NLS-FR2780, USB HID keyboard mode) types the
decoded QR into the restaurant's /scan page. Digits only, so a Korean IME, Caps
Lock or keyboard layout on the counter PC/tablet cannot corrupt the token.

Layout (81 digits): "81" | user uuid as 39-digit int | expiry epoch (10) |
nonce (10) | HMAC-SHA256 truncated to 64 bits as 20 digits.
No server state is needed to issue; replay is blocked by using the nonce in the
consuming RPC's idempotency key (a second redeem returns duplicate=true).
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
import uuid
from dataclasses import dataclass

VERSION = "81"
TTL_SECONDS = 60
CLOCK_SKEW_SECONDS = 5
TOKEN_LENGTH = 2 + 39 + 10 + 10 + 20
_DIGITS = re.compile(r"\d+")


class MealQrError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MealQrClaim:
    user_id: str
    nonce: str
    expires_at: int

    @property
    def idempotency_key(self) -> str:
        return f"meal-qr:{self.user_id}:{self.nonce}"


def _key(secret: str) -> bytes:
    if not secret:
        raise RuntimeError("meal QR signing secret is not configured")
    # Domain-separated so the raw secret is never used directly for this purpose.
    return hmac.new(secret.encode(), b"greeneat-meal-qr-v1", hashlib.sha256).digest()


def _sign(key: bytes, body: str) -> str:
    mac = hmac.new(key, f"GEQ|{body}".encode(), hashlib.sha256).digest()[:8]
    return str(int.from_bytes(mac, "big")).zfill(20)


def issue(user_id: str, secret: str, *, now: float | None = None) -> tuple[str, int]:
    uid = uuid.UUID(str(user_id))
    expires_at = int(now if now is not None else time.time()) + TTL_SECONDS
    nonce = str(secrets.randbelow(10**10)).zfill(10)
    body = f"{VERSION}{str(uid.int).zfill(39)}{expires_at:010d}{nonce}"
    return body + _sign(_key(secret), body), expires_at


def normalize(raw: str) -> str:
    """Scanners may add prefixes/suffixes (CR/LF, AIM ids); keep the 81-digit run."""
    runs = [run for run in _DIGITS.findall(raw or "") if len(run) >= TOKEN_LENGTH]
    for run in runs:
        start = run.find(VERSION)
        while start != -1 and start + TOKEN_LENGTH <= len(run):
            return run[start:start + TOKEN_LENGTH]
    raise MealQrError("INVALID_MEAL_QR", "회원 QR이 아니에요. 앱의 내 QR을 찍어 주세요")


def verify(raw: str, secret: str, *, now: float | None = None) -> MealQrClaim:
    token = normalize(raw)
    body, signature = token[:-20], token[-20:]
    if not hmac.compare_digest(_sign(_key(secret), body), signature):
        raise MealQrError("INVALID_MEAL_QR", "회원 QR을 확인하지 못했어요. 다시 찍어 주세요")
    uid_int = int(body[2:41])
    expires_at = int(body[41:51])
    nonce = body[51:61]
    current = int(now if now is not None else time.time())
    if current > expires_at + CLOCK_SKEW_SECONDS:
        raise MealQrError("MEAL_QR_EXPIRED", "QR 유효시간이 지났어요. 앱에서 새 QR로 다시 찍어 주세요")
    if expires_at - current > TTL_SECONDS + CLOCK_SKEW_SECONDS:
        raise MealQrError("INVALID_MEAL_QR", "회원 QR을 확인하지 못했어요. 다시 찍어 주세요")
    if uid_int >= 2**128:
        raise MealQrError("INVALID_MEAL_QR", "회원 QR을 확인하지 못했어요. 다시 찍어 주세요")
    return MealQrClaim(user_id=str(uuid.UUID(int=uid_int)), nonce=nonce, expires_at=expires_at)
