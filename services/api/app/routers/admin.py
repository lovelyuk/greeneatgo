from fastapi import APIRouter, Depends, HTTPException

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.schemas import JoinDecisionRequest
from app.services.join_flow import JoinFlowError

router = APIRouter(prefix="/admin", tags=["admin"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _handle_join_error(exc: JoinFlowError) -> HTTPException:
    status = 403 if str(exc.code) == "FORBIDDEN" else 400
    return _error(status, str(exc.code), exc.message)


@router.get("/join-requests")
def list_join_requests(token: str = Depends(bearer_token)):
    try:
        rows = JoinRepository().list_pending_join_requests(actor_token=token)
        return {"ok": True, "data": {"items": rows}, "error": None}
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "Supabase 처리 중 오류가 발생했어요") from exc


@router.post("/join-requests/{user_id}/approve")
def approve_join_request(user_id: str, _: JoinDecisionRequest | None = None, token: str = Depends(bearer_token)):
    try:
        row = JoinRepository().approve(actor_token=token, user_id=user_id)
        return {"ok": True, "data": row, "error": None}
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "Supabase 처리 중 오류가 발생했어요") from exc


@router.post("/join-requests/{user_id}/reject")
def reject_join_request(user_id: str, payload: JoinDecisionRequest, token: str = Depends(bearer_token)):
    if not payload.reason:
        raise _error(400, "REASON_REQUIRED", "거절 사유를 입력해 주세요")
    try:
        row = JoinRepository().reject(actor_token=token, user_id=user_id, reason=payload.reason)
        return {"ok": True, "data": row, "error": None}
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "Supabase 처리 중 오류가 발생했어요") from exc
