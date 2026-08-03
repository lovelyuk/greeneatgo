from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from app.config import Settings
from app.services.sms import (
    MAX_RESPONSE_BYTES,
    SOLAPI_SEND_URL,
    SmsDeliveryError,
    SolapiSmsService,
    mask_phone,
    verification_message,
)


PHONE = "01012345678"
CODE = "123456"
API_KEY = "public-api-key"
API_SECRET = "provider-secret"
SENDER = "021234567"
DATE = datetime(2026, 8, 3, 1, 2, 3, 456000, tzinfo=timezone.utc)
SALT = "fixed-cryptographic-salt"


class Response:
    def __init__(self, payload: object) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]


def settings(**overrides) -> Settings:
    values = {
        "supabase_url": "https://example.supabase.co",
        "supabase_anon_key": "anon",
        "supabase_service_role_key": "role",
        "env": "test",
        "solapi_api_key": API_KEY,
        "solapi_api_secret": API_SECRET,
        "solapi_sender": SENDER,
        "sms_dry_run": False,
    }
    values.update(overrides)
    return Settings(**values)


def success_payload() -> dict:
    return {
        "groupInfo": {"groupId": "G4V20260803", "count": {"registeredFailed": 0}},
        "failedMessageList": [],
        "messageList": [{"messageId": "M4V20260803"}],
    }


def test_official_request_contract_and_deterministic_hmac():
    captured = {}

    def open_request(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response(success_payload())

    result = SolapiSmsService(
        settings(),
        clock=lambda: DATE,
        salt_factory=lambda: SALT,
        urlopen_fn=open_request,
    ).send_verification_code(PHONE, CODE)

    request = captured["request"]
    assert request.full_url == SOLAPI_SEND_URL
    assert request.get_method() == "POST"
    assert captured["timeout"] == 5
    assert json.loads(request.data) == {
        "messages": [
            {
                "to": PHONE,
                "from": SENDER,
                "text": "[돈토식당] 인증번호 123456\n타인에게 알려주지 마세요.",
            }
        ],
        "showMessageList": True,
    }
    date = "2026-08-03T01:02:03.456Z"
    signature = hmac.new(
        API_SECRET.encode(), f"{date}{SALT}".encode(), hashlib.sha256
    ).hexdigest()
    assert request.get_header("Authorization") == (
        f"HMAC-SHA256 apiKey={API_KEY}, date={date}, salt={SALT}, "
        f"signature={signature}"
    )
    assert result.message_id == "M4V20260803"
    assert result.group_id == "G4V20260803"
    assert result.dry_run is False


def test_message_helpers_are_exact_and_phone_is_masked():
    assert verification_message(CODE) == "[돈토식당] 인증번호 123456\n타인에게 알려주지 마세요."
    assert mask_phone(PHONE) == "010****5678"
    assert PHONE not in mask_phone(PHONE)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "groupInfo": {"groupId": "group", "count": {"registeredFailed": 1}},
            "failedMessageList": [],
            "messageList": [{"messageId": "must-not-be-accepted"}],
        },
        {
            "groupInfo": {"groupId": "group"},
            "failedMessageList": [{"to": PHONE, "error": "rejected"}],
            "messageList": [{"messageId": "must-not-be-accepted"}],
        },
        {
            "groupInfo": {"groupId": "group"},
            "failedMessageList": [],
            "messageList": [{}],
        },
        {
            "groupInfo": {"groupId": "group"},
            "failedMessageList": [],
            "messageList": {"arbitrary-dict-key": {}},
        },
    ],
)
def test_provider_registration_failure_or_missing_message_id_is_sanitized(payload):
    service = SolapiSmsService(settings(), urlopen_fn=lambda *_args, **_kwargs: Response(payload))

    with pytest.raises(SmsDeliveryError) as caught:
        service.send_verification_code(PHONE, CODE)

    assert str(caught.value) == "SMS delivery failed"
    assert PHONE not in str(caught.value)
    assert CODE not in str(caught.value)
    assert API_SECRET not in str(caught.value)


@pytest.mark.parametrize(
    ("counter_path", "malformed_value"),
    [
        (("failedCount",), True),
        (("registeredFailed",), "0"),
        (("failed",), -1),
        (("count", "failed"), False),
        (("count", "registeredFailed"), "1"),
    ],
)
def test_malformed_provider_failure_counters_fail_closed(counter_path, malformed_value):
    payload = success_payload()
    target = payload["groupInfo"]
    for key in counter_path[:-1]:
        target = target.setdefault(key, {})
    target[counter_path[-1]] = malformed_value

    with pytest.raises(SmsDeliveryError, match="^SMS delivery failed$"):
        SolapiSmsService(
            settings(), urlopen_fn=lambda *_args, **_kwargs: Response(payload)
        ).send_verification_code(PHONE, CODE)


def test_oversized_provider_response_is_bounded_and_sanitized():
    class OversizedResponse(Response):
        def __init__(self) -> None:
            self.body = b"x" * (MAX_RESPONSE_BYTES + 1)

    with pytest.raises(SmsDeliveryError, match="^SMS delivery failed$") as caught:
        SolapiSmsService(
            settings(), urlopen_fn=lambda *_args, **_kwargs: OversizedResponse()
        ).send_verification_code(PHONE, CODE)

    assert PHONE not in str(caught.value)
    assert CODE not in str(caught.value)
    assert API_SECRET not in str(caught.value)


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError(f"timeout {PHONE} {CODE} {API_SECRET}"),
        URLError(f"transport {PHONE} {CODE} {API_SECRET}"),
        HTTPError(
            SOLAPI_SEND_URL,
            400,
            f"bad {PHONE} {CODE} {API_SECRET}",
            {},
            BytesIO(f"provider body {PHONE} {CODE} {API_SECRET}".encode()),
        ),
    ],
)
def test_transport_and_timeout_exceptions_are_sanitized(failure):
    def fail(*_args, **_kwargs):
        raise failure

    with pytest.raises(SmsDeliveryError) as caught:
        SolapiSmsService(settings(), urlopen_fn=fail).send_verification_code(PHONE, CODE)

    rendered = str(caught.value)
    assert rendered == "SMS delivery failed"
    assert caught.value.__cause__ is None
    assert PHONE not in rendered
    assert CODE not in rendered
    assert API_SECRET not in rendered


def test_dry_run_logs_only_masked_phone_and_code_in_nonproduction(caplog):
    service = SolapiSmsService(settings(sms_dry_run=True, solapi_api_key="", solapi_api_secret=""))

    with caplog.at_level(logging.INFO, logger="app.services.sms"):
        result = service.send_verification_code(PHONE, CODE)

    assert result.message_id == "dry-run"
    assert result.dry_run is True
    assert "010****5678" in caplog.text
    assert CODE in caplog.text
    assert PHONE not in caplog.text
    assert API_SECRET not in caplog.text


def test_live_success_produces_no_normal_log_with_phone_code_or_secret(caplog):
    service = SolapiSmsService(
        settings(), urlopen_fn=lambda *_args, **_kwargs: Response(success_payload())
    )

    with caplog.at_level(logging.DEBUG, logger="app.services.sms"):
        service.send_verification_code(PHONE, CODE)

    assert PHONE not in caplog.text
    assert CODE not in caplog.text
    assert API_SECRET not in caplog.text


def test_production_dry_run_boot_guard_has_required_error():
    with pytest.raises(RuntimeError, match="^SMS_DRY_RUN cannot be enabled in production$"):
        settings(env="production", sms_dry_run=True)


def test_production_requires_solapi_configuration():
    with pytest.raises(RuntimeError, match="SOLAPI credentials and sender are required in production") as caught:
        settings(
            env="production",
            sms_dry_run=False,
            solapi_api_key="",
            solapi_api_secret="",
            solapi_sender="",
        )

    assert API_SECRET not in str(caught.value)


def test_missing_credentials_are_allowed_outside_production_but_send_fails_safely():
    service = SolapiSmsService(
        settings(solapi_api_key="", solapi_api_secret="", solapi_sender="")
    )

    with pytest.raises(SmsDeliveryError, match="^SMS delivery failed$"):
        service.send_verification_code(PHONE, CODE)
