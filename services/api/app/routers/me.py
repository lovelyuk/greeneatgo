from fastapi import APIRouter, Depends, HTTPException

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.services.join_flow import JoinFlowError

router = APIRouter(tags=["me"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


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
        },
        "error": None,
    }
