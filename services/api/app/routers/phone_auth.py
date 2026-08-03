"""Phone OTP v1.1 routes.

Successful payloads use the repository-wide ``{ok, data, error}`` envelope.
Errors intentionally follow the existing FastAPI ``HTTPException.detail`` shape
(``{code, message, retry_after?}``); this router does not install a global error
handler or alter contracts for unrelated APIs.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.phone_auth import PhoneAuthError, PhoneAuthRepository
from app.repositories.supabase_http import AuthUser, SupabaseHttpError
from app.schemas import PhoneChangeRequest, PhoneSendRequest, PhoneSignupRequest, PhoneVerifyRequest

router = APIRouter(prefix="/auth/phone", tags=["phone-auth"])


def get_phone_auth_repository() -> PhoneAuthRepository:
    return PhoneAuthRepository()


def get_current_phone_user(token: str = Depends(bearer_token)) -> AuthUser:
    try:
        return JoinRepository().auth_user_from_token(token)
    except SupabaseHttpError as exc:
        if exc.status == 503:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "FIREBASE_UNAVAILABLE",
                    "message": "인증 서비스를 일시적으로 이용할 수 없어요",
                },
            ) from exc
        raise HTTPException(status_code=401, detail={"code": "UNAUTHENTICATED", "message": "로그인이 필요해요"}) from exc


def _raise(exc: PhoneAuthError) -> None:
    detail: dict[str, object] = {"code": exc.code, "message": exc.message}
    if exc.retry_after is not None:
        detail["retry_after"] = exc.retry_after
    raise HTTPException(status_code=exc.status, detail=detail) from exc


def _service_error(exc: SupabaseHttpError) -> None:
    status = 503 if exc.status == 503 else 502
    code = "FIREBASE_UNAVAILABLE" if status == 503 else "PHONE_AUTH_ERROR"
    message = "인증 서비스를 일시적으로 이용할 수 없어요" if status == 503 else "휴대폰 인증 처리 중 오류가 발생했어요"
    raise HTTPException(status_code=status, detail={"code": code, "message": message}) from exc


def _valid_phone(phone: str) -> str:
    """Validate after normalization without changing errors for other APIs."""
    if re.fullmatch(r"010[0-9]{8}", phone) is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PHONE", "message": "올바른 휴대폰 번호를 입력해 주세요."},
        )
    return phone


@router.post("/send")
def send_code(payload: PhoneSendRequest, request: Request, repo: PhoneAuthRepository = Depends(get_phone_auth_repository)):
    try:
        request_ip = request.client.host if request.client is not None else "0.0.0.0"
        data = repo.send(phone=_valid_phone(payload.phone), purpose=payload.purpose, request_ip=request_ip)
        return {"ok": True, "data": data, "error": None}
    except PhoneAuthError as exc:
        _raise(exc)
    except SupabaseHttpError as exc:
        _service_error(exc)


@router.post("/verify")
def verify_code(payload: PhoneVerifyRequest, repo: PhoneAuthRepository = Depends(get_phone_auth_repository)):
    try:
        data = repo.verify(phone=_valid_phone(payload.phone), code=payload.code, purpose=payload.purpose)
        return {"ok": True, "data": data, "error": None}
    except PhoneAuthError as exc:
        _raise(exc)
    except SupabaseHttpError as exc:
        _service_error(exc)


@router.post("/signup")
def signup(payload: PhoneSignupRequest, repo: PhoneAuthRepository = Depends(get_phone_auth_repository)):
    try:
        data = repo.signup(verification_token=payload.verification_token, display_name=payload.display_name)
        return {"ok": True, "data": data, "error": None}
    except PhoneAuthError as exc:
        _raise(exc)
    except SupabaseHttpError as exc:
        _service_error(exc)


@router.post("/change")
def change_phone(
    payload: PhoneChangeRequest,
    user: AuthUser = Depends(get_current_phone_user),
    repo: PhoneAuthRepository = Depends(get_phone_auth_repository),
):
    try:
        data = repo.change(verification_token=payload.verification_token, actor_id=user.id)
        return {"ok": True, "data": data, "error": None}
    except PhoneAuthError as exc:
        _raise(exc)
    except SupabaseHttpError as exc:
        _service_error(exc)
