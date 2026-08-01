from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.admin_dashboard_schemas import AdminDashboardSummaryResponse
from app.auth import bearer_token
from app.repositories.admin_dashboard import AdminDashboardRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.services.join_flow import JoinFlowError, UserProfile

router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])
MAX_DASHBOARD_PERIOD_DAYS = 366


def get_admin_dashboard_repository() -> AdminDashboardRepository:
    return AdminDashboardRepository()


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _scope_not_found() -> HTTPException:
    return _error(404, "SCOPE_NOT_FOUND", "조회 범위를 찾을 수 없어요")


def _authorize_browser_scopes(actor: UserProfile, merchant_id: UUID | None, company_id: UUID | None) -> None:
    merchant = str(merchant_id) if merchant_id else None
    company = str(company_id) if company_id else None
    if actor.role == "merchant_admin":
        if merchant is None or not actor.merchant_id or merchant != actor.merchant_id:
            raise _scope_not_found()
    elif actor.role == "company_admin":
        if company is None or not actor.company_id or company != actor.company_id:
            raise _scope_not_found()
    elif actor.role == "platform_admin":
        return
    else:  # Repository enforces this too; retain a fail-closed route boundary.
        raise _error(403, "FORBIDDEN", "활성 관리자만 대시보드를 조회할 수 있어요")


def _database_error(exc: SupabaseHttpError) -> HTTPException:
    body = exc.body.lower()
    if "pgrst202" in body or ("admin_dashboard_summary" in body and "schema cache" in body):
        return _error(503, "ADMIN_DASHBOARD_MIGRATION_REQUIRED", "관리자 대시보드 데이터베이스 마이그레이션이 필요해요")
    if "admin_dashboard_scope_not_found" in body:
        return _scope_not_found()
    if "admin_dashboard_actor_forbidden" in body:
        return _error(403, "FORBIDDEN", "활성 관리자만 대시보드를 조회할 수 있어요")
    if "admin_dashboard_input_invalid" in body:
        return _error(422, "INVALID_DATE_RANGE", "조회 기간이 올바르지 않아요")
    if exc.status in (401, 403):
        return _error(401, "UNAUTHENTICATED", "로그인이 필요해요")
    return _error(502, "SUPABASE_ERROR", "관리자 대시보드를 조회하지 못했어요")


@router.get("/summary", response_model=AdminDashboardSummaryResponse)
def admin_dashboard_summary(
    period_from: date = Query(alias="from"),
    period_to: date = Query(alias="to"),
    merchant_id: UUID | None = Query(default=None),
    company_id: UUID | None = Query(default=None),
    token: str = Depends(bearer_token),
    repo: AdminDashboardRepository = Depends(get_admin_dashboard_repository),
):
    if period_from > period_to:
        raise _error(422, "INVALID_DATE_RANGE", "조회 시작일은 종료일보다 늦을 수 없어요")
    if (period_to - period_from).days + 1 > MAX_DASHBOARD_PERIOD_DAYS:
        raise _error(422, "INVALID_DATE_RANGE", f"조회 기간은 최대 {MAX_DASHBOARD_PERIOD_DAYS}일까지 선택할 수 있어요")
    try:
        actor = repo.actor(token)
        if merchant_id is None and company_id is None and actor.role != "platform_admin":
            raise _error(403, "FORBIDDEN", "전체 범위는 플랫폼 운영자만 조회할 수 있어요")
        _authorize_browser_scopes(actor, merchant_id, company_id)
        data = repo.summary(
            actor.id,
            period_from,
            period_to,
            str(merchant_id) if merchant_id else None,
            str(company_id) if company_id else None,
        )
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _error(403, "FORBIDDEN", exc.message) from exc
    except SupabaseHttpError as exc:
        raise _database_error(exc) from exc
    return {"ok": True, "data": data, "error": None}
