from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import Settings, get_settings


SOLAPI_SEND_URL = "https://api.solapi.com/messages/v4/send-many/detail"
SMS_TIMEOUT_SECONDS = 5
MAX_RESPONSE_BYTES = 1024 * 1024
logger = logging.getLogger(__name__)


class SmsDeliveryError(RuntimeError):
    """Sanitized provider failure suitable for mapping to an HTTP 502."""

    def __init__(self) -> None:
        super().__init__("SMS delivery failed")


@dataclass(frozen=True)
class SmsDelivery:
    message_id: str
    group_id: str | None = None
    dry_run: bool = False


def verification_message(code: str) -> str:
    return f"[돈토식당] 인증번호 {code}\n타인에게 알려주지 마세요."


def mask_phone(phone: str) -> str:
    """Retain enough of a number to identify a dry-run without exposing it."""
    if len(phone) <= 4:
        return "*" * len(phone)
    if len(phone) <= 7:
        return f"{phone[:2]}{'*' * (len(phone) - 4)}{phone[-2:]}"
    return f"{phone[:3]}{'*' * (len(phone) - 7)}{phone[-4:]}"


def _utc_iso8601(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def solapi_authorization(api_key: str, api_secret: str, date: str, salt: str) -> str:
    signature = hmac.new(
        api_secret.encode("utf-8"),
        f"{date}{salt}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return (
        f"HMAC-SHA256 apiKey={api_key}, date={date}, "
        f"salt={salt}, signature={signature}"
    )


def _nonempty_string(value: Any) -> str | None:
    return value if isinstance(value, str) and bool(value.strip()) else None


def _message_ids(message_list: Any) -> list[str]:
    if isinstance(message_list, dict):
        entries = list(message_list.values())
    elif isinstance(message_list, list):
        entries = message_list
    else:
        return []

    ids: list[str] = []
    for entry in entries:
        if isinstance(entry, dict):
            message_id = _nonempty_string(entry.get("messageId"))
            if message_id:
                ids.append(message_id)
    return ids


def _has_invalid_or_positive_counter(container: dict[str, Any], keys: tuple[str, ...]) -> bool:
    """Fail closed for provider failure counters that are present but malformed."""
    for key in keys:
        if key not in container:
            continue
        value = container[key]
        # bool is an int subclass, but is not a valid provider count.
        if type(value) is not int or value < 0 or value > 0:
            return True
    return False


class SolapiSmsService:
    def __init__(
        self,
        settings: Settings,
        *,
        clock: Callable[[], datetime] | None = None,
        salt_factory: Callable[[], str] | None = None,
        urlopen_fn: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.salt_factory = salt_factory or (lambda: secrets.token_hex(16))
        self.urlopen = urlopen_fn or urlopen

    def send_verification_code(self, phone: str, code: str) -> SmsDelivery:
        if self.settings.sms_dry_run:
            if self.settings.env == "production":
                raise RuntimeError("SMS_DRY_RUN cannot be enabled in production")
            logger.info("SMS dry-run phone=%s code=%s", mask_phone(phone), code)
            return SmsDelivery(message_id="dry-run", dry_run=True)

        if not all(
            (
                self.settings.solapi_api_key,
                self.settings.solapi_api_secret,
                self.settings.solapi_sender,
            )
        ):
            raise SmsDeliveryError()

        date = _utc_iso8601(self.clock())
        salt = self.salt_factory()
        body = json.dumps(
            {
                "messages": [
                    {
                        "to": phone,
                        "from": self.settings.solapi_sender,
                        "text": verification_message(code),
                    }
                ],
                "showMessageList": True,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            SOLAPI_SEND_URL,
            data=body,
            headers={
                "Authorization": solapi_authorization(
                    self.settings.solapi_api_key,
                    self.settings.solapi_api_secret,
                    date,
                    salt,
                ),
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )

        try:
            with self.urlopen(request, timeout=SMS_TIMEOUT_SECONDS) as response:
                raw_response = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw_response) > MAX_RESPONSE_BYTES:
                    raise SmsDeliveryError()
                payload = json.loads(raw_response.decode("utf-8"))
        except SmsDeliveryError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, UnicodeError):
            raise SmsDeliveryError() from None

        if not isinstance(payload, dict):
            raise SmsDeliveryError()
        failed = payload.get("failedMessageList")
        group_info = payload.get("groupInfo")
        if not isinstance(group_info, dict) or not isinstance(failed, list) or bool(failed):
            raise SmsDeliveryError()

        # Provider registration failures can be reported only in groupInfo.
        if _has_invalid_or_positive_counter(
            group_info, ("failedCount", "registeredFailed", "failed")
        ):
            raise SmsDeliveryError()
        count = group_info.get("count")
        if isinstance(count, dict) and _has_invalid_or_positive_counter(
            count, ("failed", "registeredFailed")
        ):
            raise SmsDeliveryError()

        ids = _message_ids(payload.get("messageList"))
        if not ids:
            raise SmsDeliveryError()
        return SmsDelivery(
            message_id=ids[0],
            group_id=_nonempty_string(group_info.get("groupId")),
        )


def send_verification_sms(
    phone: str,
    code: str,
    *,
    settings: Settings | None = None,
) -> SmsDelivery:
    return SolapiSmsService(settings or get_settings()).send_verification_code(phone, code)