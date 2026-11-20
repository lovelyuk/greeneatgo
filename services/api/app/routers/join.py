from fastapi import APIRouter, Depends, HTTPException

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.schemas import BulkInviteResponse, JoinRequest
from app.services.join_flow import JoinFlowError

router = APIRouter(tags=["join"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


@router.post(
    "/join/request",
    summary="회사 초대코드로 직원 가입",
    description=(
        "일괄등록된 직원의 이름과 연락처가 모두 일치하면 기존 직원 슬롯을 즉시 연결하고, "
        "일치하지 않으면 회사관리자 승인 대기 상태로 등록합니다."
    ),
)
def request_join(payload: JoinRequest, token: str = Depends(bearer_token)):
    try:
        data = JoinRepository().request_join(
            access_token=token,
            invite_code=payload.invite_code,
            display_name=payload.display_name,
            phone=payload.phone,
            department=payload.department,
            employee_no=payload.employee_no,
        )
        return {"ok": True, "data": data, "error": None}
    except JoinFlowError as exc:
        raise _error(400, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "Supabase 처리 중 오류가 발생했어요") from exc


@router.post(
    "/join/bulk-invite/respond",
    summary="일괄등록된 회사의 직원 전환 수락/거절",
    description=(
        "문자 인증된 휴대폰 번호가 회사의 일괄등록 명단에 있는 개인 회원이 "
        "직원 전환을 수락하거나 거절합니다. 거절은 회사관리자 화면에 표시됩니다."
    ),
)
def respond_bulk_invite(payload: BulkInviteResponse, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        auth = repo.auth_user_from_token(token)
        profile = repo.get_profile(auth.id, email=auth.email)
        if profile is None:
            raise _error(404, "PROFILE_NOT_FOUND", "계정을 찾을 수 없어요")
        # The invite is matched to the caller's own verified number in the database;
        # the id only says which offer the member answered.
        result = repo.client.rpc("respond_employee_bulk_invite", {
            "p_user_id": profile.id, "p_invite_id": payload.invite_id,
            "p_accept": payload.accept, "p_fresh_only": False,
        })
        status = result.get("status") if isinstance(result, dict) else None
        if status in ("accepted", "declined"):
            return {"ok": True, "data": {"status": status, "company_name": result.get("company_name")}, "error": None}
        if status == "conflict":
            raise _error(409, "EMPLOYEE_CONFLICT", "같은 번호나 사번의 직원이 이미 있어요. 회사 관리자에게 문의해 주세요.")
        if status == "not_eligible":
            raise _error(409, "NOT_ELIGIBLE", "직원으로 전환할 수 있는 계정이 아니에요")
        raise _error(404, "INVITE_NOT_FOUND", "전환할 수 있는 초대가 없어요. 이미 처리됐을 수 있어요.")
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "직원 전환을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.") from exc
