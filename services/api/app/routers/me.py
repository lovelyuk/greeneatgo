from fastapi import APIRouter, Depends, HTTPException
import secrets

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.services.join_flow import JoinFlowError

router = APIRouter(tags=["me"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _new_invite_code() -> str:
    return f"GE-{secrets.token_hex(3).upper()}"


def _ensure_invite_code(repo: JoinRepository, company_id: str) -> str | None:
    codes = repo.client.rest_get(
        "company_invite_codes",
        {"select": "code", "company_id": f"eq.{company_id}", "is_active": "eq.true", "order": "created_at.desc", "limit": "1"},
    )
    if codes:
        return codes[0]["code"]
    for _ in range(5):
        code = _new_invite_code()
        try:
            repo.client.rest_post("company_invite_codes", {"company_id": company_id, "code": code, "is_active": True})
            return code
        except SupabaseHttpError as exc:
            if "duplicate" not in exc.body.lower() and "unique" not in exc.body.lower():
                raise
    return None


@router.get("/me")
def me(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        auth_user = repo.auth_user_from_token(token)
        profile = repo.get_profile(auth_user.id, email=auth_user.email)
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "Supabase 처리 중 오류가 발생했어요") from exc

    if profile is None:
        return {
            "ok": True,
            "data": {
                "user_id": auth_user.id,
                "email": auth_user.email,
                "status": "no_profile",
            },
            "error": None,
        }

    invite_code = None
    if profile.role == "company_admin" and profile.company_id:
        invite_code = _ensure_invite_code(repo, profile.company_id)

    return {
        "ok": True,
        "data": {
            "user_id": profile.id,
            "email": auth_user.email,
            "display_name": profile.display_name,
            "company_id": profile.company_id,
            "merchant_id": profile.merchant_id,
            "group_id": profile.group_id,
            "role": profile.role,
            "status": profile.status,
            "invite_code": invite_code,
        },
        "error": None,
    }
