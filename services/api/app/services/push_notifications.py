from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from typing import Callable, Sequence

import firebase_admin
from firebase_admin import credentials, exceptions as firebase_exceptions, messaging


class PushConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PushTarget:
    account_id: str
    token: str


@dataclass(frozen=True)
class PushSendResult:
    target_count: int
    device_count: int
    success_count: int
    success_device_count: int
    failure_device_count: int
    invalid_tokens: tuple[str, ...]


BatchSender = Callable[[str, str, Sequence[str]], object]


def _service_account_info() -> dict:
    raw = (os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON") or "").strip()
    encoded = (os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON_BASE64") or "").strip()
    if encoded:
        try:
            raw = base64.b64decode(encoded, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise PushConfigurationError("Firebase 서비스 계정 Base64 값을 읽을 수 없어요") from exc
    if not raw:
        raise PushConfigurationError("Firebase 서비스 계정 환경변수가 설정되지 않았어요")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PushConfigurationError("Firebase 서비스 계정 JSON 형식이 올바르지 않아요") from exc
    if not isinstance(info, dict) or not info.get("project_id") or not info.get("private_key") or not info.get("client_email"):
        raise PushConfigurationError("Firebase 서비스 계정 JSON 필수 값이 누락됐어요")
    return info


def _firebase_app():
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app(credentials.Certificate(_service_account_info()))


def ensure_push_configured() -> None:
    _firebase_app()


def _firebase_send_batch(title: str, body: str, tokens: Sequence[str]):
    message = messaging.MulticastMessage(
        tokens=list(tokens),
        notification=messaging.Notification(title=title, body=body),
        data={"type": "announcement"},
        android=messaging.AndroidConfig(priority="high"),
        apns=messaging.APNSConfig(headers={"apns-priority": "10"}),
    )
    return messaging.send_each_for_multicast(message, app=_firebase_app())


def send_individual_point_push(*, tokens: Sequence[str], amount: int, balance: int) -> int:
    """Best effort individual notification; callers deliberately ignore failures."""
    if not tokens:
        return 0
    message = messaging.MulticastMessage(
        tokens=list(tokens),
        notification=messaging.Notification(title="복지포인트가 충전됐어요", body=f"{amount:,}P 충전 · 잔액 {balance:,}P"),
        data={"event": "point_charged", "amount": str(amount), "balance": str(balance)},
        android=messaging.AndroidConfig(priority="high"),
        apns=messaging.APNSConfig(headers={"apns-priority": "10"}),
    )
    response = messaging.send_each_for_multicast(message, app=_firebase_app())
    return int(getattr(response, "success_count", 0))


def _is_invalid_token(exception: Exception | None) -> bool:
    if exception is None:
        return False
    name = type(exception).__name__
    code = str(getattr(exception, "code", "")).lower()
    return name in {"UnregisteredError", "SenderIdMismatchError"} or code in {
        "registration-token-not-registered",
        "sender-id-mismatch",
        "invalid-argument",
    }


def send_push_notifications(
    *,
    title: str,
    body: str,
    targets: Sequence[PushTarget],
    send_batch: BatchSender | None = None,
) -> PushSendResult:
    sender = send_batch or _firebase_send_batch
    successful_accounts: set[str] = set()
    invalid_tokens: list[str] = []
    success_devices = 0
    failure_devices = 0

    for start in range(0, len(targets), 500):
        batch = targets[start:start + 500]
        try:
            response = sender(title, body, [target.token for target in batch])
        except firebase_exceptions.FirebaseError:
            failure_devices += len(batch)
            continue
        responses = list(getattr(response, "responses", ()))
        if len(responses) != len(batch):
            raise RuntimeError("FCM 응답 개수가 발송 대상 기기 수와 일치하지 않아요")
        for target, item in zip(batch, responses, strict=True):
            if bool(getattr(item, "success", False)):
                success_devices += 1
                successful_accounts.add(target.account_id)
            else:
                failure_devices += 1
                exception = getattr(item, "exception", None)
                if _is_invalid_token(exception):
                    invalid_tokens.append(target.token)

    return PushSendResult(
        target_count=len({target.account_id for target in targets}),
        device_count=len(targets),
        success_count=len(successful_accounts),
        success_device_count=success_devices,
        failure_device_count=failure_devices,
        invalid_tokens=tuple(invalid_tokens),
    )
