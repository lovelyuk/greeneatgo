import hashlib
from types import SimpleNamespace
from unittest.mock import Mock, patch

import bcrypt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.repositories.phone_auth import PhoneAuthError, PhoneAuthRepository
from app.repositories.supabase_http import AuthUser, SupabaseHttpError
from app.routers import phone_auth
from app.services.firebase_auth import (
    create_phone_custom_token,
    firebase_uid_to_internal_uuid,
    phone_firebase_uid,
    verify_firebase_auth_user,
)
from app.services.sms import SmsDeliveryError


def settings():
    return Settings("https://db.example", "anon", "service", env="test", otp_pepper="pepper", otp_bcrypt_rounds=4)


def repository(client=None, sms=None):
    return PhoneAuthRepository(client or Mock(), settings(), sms or Mock(), code_factory=lambda: 123456, token_factory=lambda: "raw-exchange-token-which-is-long-enough")


def test_send_reserves_before_bcrypt_and_sets_context_proof_hash_before_sms():
    client, sms = Mock(), Mock()
    client.rpc.side_effect = [
        {"status": "created", "verification_id": "v1"}, True, None,
    ]
    sms.send_verification_code.return_value = SimpleNamespace(message_id="provider-1")
    repo = repository(client, sms)

    assert repo.send(phone="01012345678", purpose="signup_login", request_ip="203.0.113.4") == {"expires_in": 180, "resend_after": 60}
    begin = client.rpc.call_args_list[0]
    assert begin.args[0] == "phone_auth_begin_send"
    payload = begin.args[1]
    assert payload == {
        "p_phone": "01012345678", "p_purpose": "signup_login",
        "p_request_ip": "203.0.113.4",
    }
    set_hash = client.rpc.call_args_list[1]
    assert set_hash.args[0] == "phone_auth_set_code_hash"
    hash_payload = set_hash.args[1]
    assert hash_payload["p_verification_id"] == "v1"
    assert "123456" not in repr(hash_payload)
    assert "pepper" not in repr(hash_payload)
    assert hash_payload["p_code_hash"].startswith("$2a$")
    proof = repo._code_proof(phone="01012345678", purpose="signup_login", code="123456")
    assert bcrypt.checkpw(proof.encode(), hash_payload["p_code_hash"].encode())
    sms.send_verification_code.assert_called_once_with("01012345678", "123456")


def test_failed_sms_is_consumed_once_and_sanitized():
    client, sms = Mock(), Mock()
    client.rpc.side_effect = [{"status": "created", "verification_id": "v1"}, True, None]
    sms.send_verification_code.side_effect = SmsDeliveryError()
    with pytest.raises(PhoneAuthError) as raised:
        repository(client, sms).send(phone="01012345678", purpose="signup_login", request_ip="127.0.0.1")
    assert (raised.value.status, raised.value.code) == (502, "SMS_SEND_FAILED")
    assert client.rpc.call_args_list[-1].args[1]["p_delivered"] is False
    sms.send_verification_code.assert_called_once()


def test_rejected_hash_set_consumes_reservation_without_sending_sms():
    client, sms = Mock(), Mock()
    client.rpc.side_effect = [
        {"status": "created", "verification_id": "v1"}, False, None,
    ]
    with pytest.raises(PhoneAuthError) as raised:
        repository(client, sms).send(
            phone="01012345678", purpose="signup_login", request_ip="127.0.0.1"
        )
    assert (raised.value.status, raised.value.code) == (502, "SMS_SEND_FAILED")
    assert client.rpc.call_args_list[-1].args == (
        "phone_auth_finish_send",
        {"p_verification_id": "v1", "p_provider_msg_id": None, "p_delivered": False},
    )
    sms.send_verification_code.assert_not_called()


def test_local_hash_failure_consumes_reservation_without_sending_sms():
    client, sms = Mock(), Mock()
    client.rpc.side_effect = [
        {"status": "created", "verification_id": "v1"}, None,
    ]
    with patch(
        "app.repositories.phone_auth.bcrypt.hashpw",
        side_effect=ValueError("local bcrypt failure"),
    ), pytest.raises(PhoneAuthError) as raised:
        repository(client, sms).send(
            phone="01012345678", purpose="signup_login", request_ip="127.0.0.1"
        )
    assert (raised.value.status, raised.value.code) == (502, "SMS_SEND_FAILED")
    assert client.rpc.call_args_list[-1].args == (
        "phone_auth_finish_send",
        {"p_verification_id": "v1", "p_provider_msg_id": None, "p_delivered": False},
    )
    sms.send_verification_code.assert_not_called()


def test_rate_limited_send_does_not_generate_hash_or_send_sms():
    client, sms, code_factory = Mock(), Mock(), Mock(return_value=123456)
    client.rpc.return_value = {"status": "cooldown", "retry_after": 17}
    repo = PhoneAuthRepository(
        client, settings(), sms, code_factory=code_factory,
        token_factory=lambda: "raw-exchange-token-which-is-long-enough",
    )
    with patch("app.repositories.phone_auth.bcrypt.hashpw") as hashpw, pytest.raises(PhoneAuthError):
        repo.send(phone="01012345678", purpose="signup_login", request_ip="127.0.0.1")
    code_factory.assert_not_called()
    hashpw.assert_not_called()
    sms.send_verification_code.assert_not_called()


def test_code_proof_is_hmac_bound_to_phone_and_purpose_and_rpc_has_no_raw_secrets():
    repo = repository()
    base = repo._code_proof(phone="01012345678", purpose="signup_login", code="123456")
    assert base != repo._code_proof(phone="01012345679", purpose="signup_login", code="123456")
    assert base != repo._code_proof(phone="01012345678", purpose="change_phone", code="123456")
    assert "123456" not in base and "pepper" not in base

    client = Mock()
    client.rpc.return_value = {"status": "expired"}
    with pytest.raises(PhoneAuthError):
        repository(client).verify(phone="01012345678", code="123456", purpose="signup_login")
    payload = client.rpc.call_args.args[1]
    assert "p_code_proof" in payload and "p_code_secret" not in payload
    secret_boundary = {key: value for key, value in payload.items() if key != "p_phone"}
    assert "123456" not in repr(secret_boundary) and "pepper" not in repr(secret_boundary)


@pytest.mark.parametrize("status,http,code,message", [
    ("expired", 400, "CODE_EXPIRED", "인증번호가 만료되었어요. 다시 받아주세요."),
    ("invalid_code", 400, "INVALID_CODE", "인증번호가 올바르지 않아요"),
    ("too_many_attempts", 429, "TOO_MANY_ATTEMPTS", "시도 횟수를 초과했어요. 인증번호를 다시 받아주세요."),
    ("unavailable", 403, "ACCOUNT_UNAVAILABLE", "이용할 수 없는 계정이에요"),
    ("ambiguous", 409, "PHONE_AMBIGUOUS", "계정 확인이 필요해요. 고객센터로 문의해 주세요."),
])
def test_verify_status_mapping(status, http, code, message):
    client = Mock()
    client.rpc.return_value = {"status": status}
    with pytest.raises(PhoneAuthError) as raised:
        repository(client).verify(phone="01012345678", code="123456", purpose="signup_login")
    assert (raised.value.status, raised.value.code) == (http, code)
    assert raised.value.message == message


def test_new_verification_returns_raw_but_stores_only_sha256():
    client = Mock()
    client.rpc.return_value = {"status": "new"}
    data = repository(client).verify(phone="01012345678", code="123456", purpose="signup_login")
    raw = data["verification_token"]
    assert data == {"status": "new", "verification_token": raw, "expires_in": 300}
    payload = client.rpc.call_args.args[1]
    assert payload["p_token_hash"] == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in repr(payload)


def test_existing_custom_token_uses_canonical_internal_claim():
    client = Mock()
    client.rpc.return_value = {"status": "existing", "user_id": "8c966c67-1644-4f12-bb78-d7a14572d643", "display_name": "Kim"}
    with patch("app.repositories.phone_auth.create_phone_custom_token", return_value="firebase-token") as create:
        data = repository(client).verify(phone="01012345678", code="123456", purpose="signup_login")
    assert data == {"status": "existing", "custom_token": "firebase-token", "display_name": "Kim"}
    create.assert_called_once_with("01012345678", internal_id="8c966c67-1644-4f12-bb78-d7a14572d643")


def test_firebase_custom_token_bytes_and_new_uid_mapping():
    with patch("app.services.firebase_auth._firebase_app", return_value=object()) as app, patch("app.services.firebase_auth.firebase_auth.create_custom_token", return_value=b"token") as create:
        assert create_phone_custom_token("01012345678") == "token"
    create.assert_called_once_with("phone_01012345678", developer_claims=None, app=app.return_value)
    assert firebase_uid_to_internal_uuid(phone_firebase_uid("01012345678"))


def test_phone_custom_id_token_needs_custom_provider_but_not_email():
    claims = {"uid": "phone_01012345678", "firebase": {"sign_in_provider": "custom"}}
    with patch("app.services.firebase_auth._firebase_app", return_value=object()), patch("app.services.firebase_auth.firebase_auth.verify_id_token", return_value=claims):
        user = verify_firebase_auth_user("token")
    assert user.email is None
    assert user.id == firebase_uid_to_internal_uuid("phone_01012345678")

    claims["firebase"]["sign_in_provider"] = "phone"
    with patch("app.services.firebase_auth._firebase_app", return_value=object()), patch("app.services.firebase_auth.firebase_auth.verify_id_token", return_value=claims), pytest.raises(SupabaseHttpError):
        verify_firebase_auth_user("token")


def test_email_auth_path_remains_verified_email_only():
    claims = {"uid": "ordinary", "email": "x@example.com", "email_verified": False, "firebase": {"sign_in_provider": "custom"}}
    with patch("app.services.firebase_auth._firebase_app", return_value=object()), patch("app.services.firebase_auth.firebase_auth.verify_id_token", return_value=claims), pytest.raises(SupabaseHttpError):
        verify_firebase_auth_user("token")


def router_client(repo):
    app = FastAPI()
    app.include_router(phone_auth.router, prefix="/v1")
    app.dependency_overrides[phone_auth.get_phone_auth_repository] = lambda: repo
    app.dependency_overrides[phone_auth.get_current_phone_user] = lambda: AuthUser(id="actor", email=None)
    return TestClient(app)


def test_router_normalizes_phone_uses_socket_host_and_envelope():
    repo = Mock()
    repo.send.return_value = {"expires_in": 180, "resend_after": 60}
    response = router_client(repo).post("/v1/auth/phone/send", json={"phone": "010-1234-5678", "purpose": "signup_login"})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "data": {"expires_in": 180, "resend_after": 60}, "error": None}
    assert repo.send.call_args.kwargs["request_ip"] == "testclient"
    repo.send.assert_called_once_with(phone="01012345678", purpose="signup_login", request_ip="testclient")


def test_router_exact_sms_502_and_rate_retry_detail():
    repo = Mock()
    repo.send.side_effect = PhoneAuthError(502, "SMS_SEND_FAILED", "문자를 보내지 못했어요. 잠시 후 다시 시도해 주세요.")
    response = router_client(repo).post("/v1/auth/phone/send", json={"phone": "01012345678", "purpose": "signup_login"})
    assert response.status_code == 502
    assert response.json()["detail"] == {"code": "SMS_SEND_FAILED", "message": "문자를 보내지 못했어요. 잠시 후 다시 시도해 주세요."}

    repo.send.side_effect = PhoneAuthError(429, "RATE_LIMITED", "잠시 후 다시 시도해 주세요", retry_after=37)
    response = router_client(repo).post("/v1/auth/phone/send", json={"phone": "01012345678", "purpose": "signup_login"})
    assert response.json()["detail"]["retry_after"] == 37


def test_current_phone_user_maps_firebase_outage_to_operational_503():
    app = FastAPI()
    app.include_router(phone_auth.router, prefix="/v1")
    app.dependency_overrides[phone_auth.get_phone_auth_repository] = Mock
    with patch(
        "app.routers.phone_auth.JoinRepository.auth_user_from_token",
        side_effect=SupabaseHttpError(503, "firebase unavailable"),
    ):
        response = TestClient(app).post(
            "/v1/auth/phone/change",
            headers={"Authorization": "Bearer token"},
            json={"verification_token": "a" * 24},
        )
    assert response.status_code == 503
    assert response.json() == {"detail": {
        "code": "FIREBASE_UNAVAILABLE",
        "message": "인증 서비스를 일시적으로 이용할 수 없어요",
    }}


def test_change_uses_authenticated_actor_and_verify_default_purpose():
    repo = Mock()
    repo.change.return_value = {"phone": "01099998888"}
    repo.verify.return_value = {"verification_token": "x"}
    client = router_client(repo)
    assert client.post("/v1/auth/phone/change", json={"verification_token": "a" * 24}).status_code == 200
    repo.change.assert_called_once_with(verification_token="a" * 24, actor_id="actor")
    client.post("/v1/auth/phone/verify", json={"phone": "01012345678", "code": "123456"})
    repo.verify.assert_called_once_with(phone="01012345678", code="123456", purpose="signup_login")


@pytest.mark.parametrize("path,body", [
    ("send", {"phone": "abc010-123", "purpose": "signup_login"}),
    ("verify", {"phone": "not-a-phone", "code": "123456", "purpose": "change_phone"}),
])
def test_invalid_normalized_phone_is_local_http_400_contract(path, body):
    repo = Mock()
    response = router_client(repo).post(f"/v1/auth/phone/{path}", json=body)
    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "INVALID_PHONE", "message": "올바른 휴대폰 번호를 입력해 주세요."}}
    repo.send.assert_not_called()
    repo.verify.assert_not_called()


def test_change_phone_verify_has_distinct_status_and_token():
    client = Mock()
    client.rpc.return_value = {"status": "verified"}
    data = repository(client).verify(phone="01012345678", code="123456", purpose="change_phone")
    assert data == {
        "status": "verified",
        "verification_token": "raw-exchange-token-which-is-long-enough",
        "expires_in": 300,
    }


def test_signup_exact_contract_and_imported_id_claim_only_when_needed():
    phone = "01012345678"
    deterministic = firebase_uid_to_internal_uuid(phone_firebase_uid(phone))
    client = Mock()
    client.rpc.return_value = {"status": "ok", "phone": phone, "user_id": deterministic}
    with patch("app.repositories.phone_auth.create_phone_custom_token", return_value="token") as create:
        assert repository(client).signup(verification_token="v" * 24, display_name="Kim") == {
            "custom_token": "token", "account_id": deterministic,
        }
    create.assert_called_once_with(phone, internal_id=None)

    imported = "8c966c67-1644-4f12-bb78-d7a14572d643"
    client.rpc.return_value = {"status": "ok", "phone": phone, "user_id": imported}
    with patch("app.repositories.phone_auth.create_phone_custom_token", return_value="token") as create:
        result = repository(client).signup(verification_token="v" * 24, display_name="Kim")
    assert result["account_id"] == imported
    create.assert_called_once_with(phone, internal_id=imported)


@pytest.mark.parametrize("status,http,code", [
    ("invalid_name", 400, "INVALID_NAME"),
    ("unavailable", 403, "ACCOUNT_UNAVAILABLE"),
    ("ambiguous", 409, "PHONE_AMBIGUOUS"),
    ("id_conflict", 409, "ACCOUNT_ID_CONFLICT"),
    ("unexpected", 502, "PHONE_AUTH_ERROR"),
])
def test_signup_safe_status_mapping(status, http, code):
    client = Mock()
    client.rpc.return_value = {"status": status}
    with pytest.raises(PhoneAuthError) as raised:
        repository(client).signup(verification_token="v" * 24, display_name="Kim")
    assert (raised.value.status, raised.value.code) == (http, code)
