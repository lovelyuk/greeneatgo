from fastapi import APIRouter, Depends, HTTPException

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.schemas import ConsumerRegisterRequest

router = APIRouter(prefix="/consumer", tags=["consumer"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


@router.post("/register")
def register_consumer(payload: ConsumerRegisterRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        auth = repo.auth_user_from_token(token)
        profile = repo.get_profile(auth.id, email=auth.email)
        if profile is not None:
            if profile.role == "customer" and profile.status == "active":
                return {"ok": True, "data": {"role": profile.role, "status": profile.status}, "error": None}
            if profile.role == "employee" and profile.status == "rejected":
                rows = repo.client.rest_patch("app_users", {"id": f"eq.{profile.id}"}, {
                    "display_name": payload.display_name.strip(),
                    "phone": payload.phone,
                    "role": "customer",
                    "status": "active",
                    "company_id": None,
                    "group_id": None,
                    "rejected_at": None,
                })
                return {"ok": True, "data": rows[0], "error": None}
            raise _error(409, "PROFILE_EXISTS", "이미 회사 또는 식당 계정으로 등록된 사용자예요")
        rows = repo.client.rest_post("app_users", {
            "id": auth.id,
            "display_name": payload.display_name.strip(),
            "phone": payload.phone,
            "role": "customer",
            "status": "active",
            "company_id": None,
            "group_id": None,
        })
        return {"ok": True, "data": rows[0], "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        if "app_users_role_check" in exc.body or "customer" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0014_consumer_payments.sql 적용이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "일반 사용자 등록 중 오류가 발생했어요") from exc
