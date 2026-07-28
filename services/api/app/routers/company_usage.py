from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import bearer_token
from app.company_usage_schemas import CompanyMonthlyUsageResponse
from app.repositories.company_usage import CompanyUsageRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.services.join_flow import JoinFlowError

router = APIRouter(prefix="/admin/company-usage", tags=["company-usage"])


def get_company_usage_repository() -> CompanyUsageRepository:
    return CompanyUsageRepository()


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _database_error(exc: SupabaseHttpError) -> HTTPException:
    # PostgREST reports an absent RPC as PGRST202/404. This can occur briefly when
    # API code reaches production before migration 0040; report it explicitly and
    # never substitute dashboard mock data.
    if "PGRST202" in exc.body or (
        "company_monthly_usage" in exc.body and "schema cache" in exc.body.lower()
    ):
        return _error(
            503,
            "COMPANY_USAGE_MIGRATION_REQUIRED",
            "회사 이용 내역 데이터베이스 마이그레이션이 필요해요",
        )
    if "COMPANY_USAGE_ACTOR_FORBIDDEN" in exc.body:
        return _error(403, "FORBIDDEN", "회사관리자만 이용 내역을 조회할 수 있어요")
    if "COMPANY_USAGE_MONTH_INVALID" in exc.body or "COMPANY_USAGE_INPUT_INVALID" in exc.body:
        return _error(422, "INVALID_PERIOD_YM", "조회 월은 YYYY-MM 형식이어야 해요")
    if exc.status in (401, 403):
        return _error(401, "UNAUTHENTICATED", "로그인이 필요해요")
    return _error(502, "SUPABASE_ERROR", "회사 이용 내역을 조회하지 못했어요")


@router.get("", response_model=CompanyMonthlyUsageResponse)
def company_monthly_usage(
    ym: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    token: str = Depends(bearer_token),
    repo: CompanyUsageRepository = Depends(get_company_usage_repository),
):
    # Regex rejects malformed values; strptime also rejects impossible/calendar
    # values and non-zero-padded years without allowing a tenant-controlled ID.
    try:
        datetime.strptime(ym, "%Y-%m")
    except ValueError as exc:
        raise _error(422, "INVALID_PERIOD_YM", "조회 월은 YYYY-MM 형식이어야 해요") from exc

    try:
        actor = repo.actor(token)
        assert actor.company_id is not None
        data = repo.monthly_usage(actor.id, actor.company_id, ym)
    except JoinFlowError as exc:
        raise _error(403, "FORBIDDEN", exc.message) from exc
    except SupabaseHttpError as exc:
        raise _database_error(exc) from exc
    return {"ok": True, "data": data, "error": None}
