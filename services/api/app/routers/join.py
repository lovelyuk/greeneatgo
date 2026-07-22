from fastapi import APIRouter, Depends, HTTPException

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.schemas import JoinRequest
from app.services.join_flow import JoinFlowError

router = APIRouter(tags=["join"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


@router.post("/join/request")
def request_join(payload: JoinRequest, token: str = Depends(bearer_token)):
    try:
        data = JoinRepository().request_join(
            access_token=token,
            invite_code=payload.invite_code,
            display_name=payload.display_name,
            phone=payload.phone,
        )
        return {"ok": True, "data": data, "error": None}
    except JoinFlowError as exc:
        raise _error(400, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "Supabase 처리 중 오류가 발생했어요") from exc
