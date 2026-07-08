from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

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


@router.get("/settlements")
def list_settlements(ym: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"), token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor_auth = repo.auth_user_from_token(token)
        actor = repo.get_profile(actor_auth.id, email=actor_auth.email)
        if actor is None or actor.role != "company_admin" or actor.status != "active" or not actor.company_id:
            raise JoinFlowError("FORBIDDEN", "회사관리자만 조회할 수 있어요")

        period_ym = ym or datetime.now().strftime("%Y-%m")
        rows = repo.client.rest_get(
            "settlements",
            {
                "select": "id,company_id,merchant_id,period_ym,tx_count,total_amount,status,paid_at",
                "company_id": f"eq.{actor.company_id}",
                "period_ym": f"eq.{period_ym}",
                "order": "status.asc",
            },
        )
        total_amount = sum(int(row.get("total_amount") or 0) for row in rows)
        tx_count = sum(int(row.get("tx_count") or 0) for row in rows)
        paid_count = sum(1 for row in rows if row.get("status") == "paid")
        return {
            "ok": True,
            "data": {
                "period_ym": period_ym,
                "single_merchant": True,
                "items": rows,
                "summary": {
                    "settlement_count": len(rows),
                    "paid_count": paid_count,
                    "tx_count": tx_count,
                    "total_amount": total_amount,
                },
            },
            "error": None,
        }
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "정산 데이터를 불러오는 중 오류가 발생했어요") from exc
