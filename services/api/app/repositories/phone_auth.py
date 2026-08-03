from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any, Callable

import bcrypt

from app.config import Settings, get_settings
from app.repositories.supabase_http import SupabaseHttpClient, SupabaseHttpError
from app.services.firebase_auth import (
    create_phone_custom_token,
    firebase_uid_to_internal_uuid,
    phone_firebase_uid,
)
from app.services.sms import SolapiSmsService


class PhoneAuthError(RuntimeError):
    def __init__(self, status: int, code: str, message: str, *, retry_after: int | None = None):
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after


@dataclass(frozen=True)
class PhoneAuthRepository:
    client: SupabaseHttpClient
    settings: Settings
    sms: Any
    code_factory: Callable[[], int]
    token_factory: Callable[[], str]

    def __init__(
        self,
        client: SupabaseHttpClient | None = None,
        settings: Settings | None = None,
        sms: Any | None = None,
        *,
        code_factory: Callable[[], int] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        settings = settings or get_settings()
        object.__setattr__(self, "client", client or SupabaseHttpClient(settings))
        object.__setattr__(self, "settings", settings)
        object.__setattr__(self, "sms", sms or SolapiSmsService(settings))
        object.__setattr__(self, "code_factory", code_factory or (lambda: secrets.randbelow(900000) + 100000))
        object.__setattr__(self, "token_factory", token_factory or (lambda: secrets.token_urlsafe(32)))

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _code_proof(self, *, phone: str, purpose: str, code: str) -> str:
        """Bind an OTP to its exact login context without exposing the pepper to SQL."""
        context = b"greeneatgo-phone-otp-proof-v1\x00" + b"\x00".join(
            value.encode("utf-8") for value in (phone, purpose, code)
        )
        return hmac.new(
            self.settings.otp_pepper.encode("utf-8"), context, hashlib.sha256
        ).hexdigest()

    def _consume_failed_send(self, verification_id: str) -> None:
        try:
            self.client.rpc("phone_auth_finish_send", {
                "p_verification_id": verification_id,
                "p_provider_msg_id": None,
                "p_delivered": False,
            })
        except SupabaseHttpError:
            # Undelivered rows remain unverifiable even if consuming encounters
            # a transient database failure.
            pass

    def send(self, *, phone: str, purpose: str, request_ip: str) -> dict[str, int]:
        result = self.client.rpc("phone_auth_begin_send", {
            "p_phone": phone, "p_purpose": purpose, "p_request_ip": request_ip,
        })
        if result.get("status") != "created":
            retry = int(result.get("retry_after") or 60)
            raise PhoneAuthError(429, "RATE_LIMITED", "잠시 후 다시 시도해 주세요", retry_after=retry)
        verification_id = result["verification_id"]
        try:
            code = f"{self.code_factory():06d}"
            code_proof = self._code_proof(phone=phone, purpose=purpose, code=code)
            code_hash = bcrypt.hashpw(
                code_proof.encode(),
                bcrypt.gensalt(rounds=self.settings.otp_bcrypt_rounds),
            ).decode().replace("$2b$", "$2a$", 1)
            hash_set = self.client.rpc("phone_auth_set_code_hash", {
                "p_verification_id": verification_id, "p_code_hash": code_hash,
            })
            if hash_set is not True:
                raise SupabaseHttpError(502, "OTP hash reservation was not pending")
            delivery = self.sms.send_verification_code(phone, code)
        except Exception:
            # Once a rate-limit slot has been reserved, every local/provider
            # failure must make it permanently unverifiable before returning.
            self._consume_failed_send(verification_id)
            raise PhoneAuthError(502, "SMS_SEND_FAILED", "문자를 보내지 못했어요. 잠시 후 다시 시도해 주세요.") from None
        self.client.rpc("phone_auth_finish_send", {
            "p_verification_id": verification_id, "p_provider_msg_id": delivery.message_id, "p_delivered": True,
        })
        return {"expires_in": 180, "resend_after": 60}

    def verify(self, *, phone: str, code: str, purpose: str) -> dict[str, Any]:
        raw_token = self.token_factory()
        result = self.client.rpc("phone_auth_verify", {
            "p_phone": phone, "p_purpose": purpose,
            "p_code_proof": self._code_proof(phone=phone, purpose=purpose, code=code),
            "p_token_hash": self._token_hash(raw_token),
        })
        status = result.get("status")
        if status == "expired":
            raise PhoneAuthError(400, "CODE_EXPIRED", "인증번호가 만료되었어요. 다시 받아주세요.")
        if status == "invalid_code":
            raise PhoneAuthError(400, "INVALID_CODE", "인증번호가 올바르지 않아요")
        if status == "too_many_attempts":
            raise PhoneAuthError(429, "TOO_MANY_ATTEMPTS", "시도 횟수를 초과했어요. 인증번호를 다시 받아주세요.")
        if status == "unavailable":
            raise PhoneAuthError(403, "ACCOUNT_UNAVAILABLE", "이용할 수 없는 계정이에요")
        if status == "ambiguous":
            raise PhoneAuthError(409, "PHONE_AMBIGUOUS", "계정 확인이 필요해요. 고객센터로 문의해 주세요.")
        if status == "existing":
            user_id = result["user_id"]
            return {
                "status": "existing",
                "custom_token": create_phone_custom_token(phone, internal_id=user_id),
                "display_name": result.get("display_name"),
            }
        if status == "new":
            return {"status": "new", "verification_token": raw_token, "expires_in": 300}
        if status == "verified" and purpose == "change_phone":
            return {"status": "verified", "verification_token": raw_token, "expires_in": 300}
        raise PhoneAuthError(502, "PHONE_AUTH_ERROR", "휴대폰 인증 처리 중 오류가 발생했어요")

    def signup(self, *, verification_token: str, display_name: str) -> dict[str, Any]:
        token_hash = self._token_hash(verification_token)
        probe = self.client.rpc("phone_auth_signup", {
            "p_token_hash": token_hash, "p_display_name": display_name,
        })
        status = probe.get("status")
        if status == "invalid_token":
            raise PhoneAuthError(400, "INVALID_VERIFICATION_TOKEN", "인증 정보가 만료됐거나 이미 사용됐어요")
        if status == "invalid_name":
            raise PhoneAuthError(400, "INVALID_NAME", "이름은 1자 이상 20자 이하로 입력해 주세요")
        if status == "unavailable":
            raise PhoneAuthError(403, "ACCOUNT_UNAVAILABLE", "이용할 수 없는 계정이에요")
        if status == "ambiguous":
            raise PhoneAuthError(409, "PHONE_AMBIGUOUS", "계정 확인이 필요해요. 고객센터로 문의해 주세요.")
        if status == "id_conflict":
            raise PhoneAuthError(409, "ACCOUNT_ID_CONFLICT", "계정 정보를 안전하게 연결할 수 없어요. 고객센터로 문의해 주세요.")
        if status != "ok" or not probe.get("phone") or not probe.get("user_id"):
            raise PhoneAuthError(502, "PHONE_AUTH_ERROR", "휴대폰 가입 처리 중 오류가 발생했어요")
        phone = probe["phone"]
        account_id = str(probe["user_id"])
        deterministic_id = firebase_uid_to_internal_uuid(phone_firebase_uid(phone))
        return {
            "custom_token": create_phone_custom_token(
                phone,
                internal_id=None if account_id == deterministic_id else account_id,
            ),
            "account_id": account_id,
        }

    def change(self, *, verification_token: str, actor_id: str) -> dict[str, Any]:
        result = self.client.rpc("phone_auth_change", {
            "p_token_hash": self._token_hash(verification_token), "p_actor_id": actor_id,
        })
        status = result.get("status")
        if status == "invalid_token":
            raise PhoneAuthError(400, "INVALID_VERIFICATION_TOKEN", "인증 정보가 만료됐거나 이미 사용됐어요")
        if status == "conflict":
            raise PhoneAuthError(409, "PHONE_ALREADY_IN_USE", "이미 다른 계정에서 사용 중인 휴대폰 번호예요")
        if status == "not_found":
            raise PhoneAuthError(404, "ACCOUNT_NOT_FOUND", "계정을 찾을 수 없어요")
        if status == "forbidden":
            raise PhoneAuthError(403, "FORBIDDEN", "휴대폰 번호를 변경할 권한이 없어요")
        if status != "ok":
            raise PhoneAuthError(502, "PHONE_AUTH_ERROR", "휴대폰 번호 변경 중 오류가 발생했어요")
        return {"phone": result["phone"]}
