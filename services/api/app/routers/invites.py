from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.schemas import InviteClaimRequest

router = APIRouter(prefix="/invites", tags=["invites"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _valid_invite(repo: JoinRepository, token: str) -> dict:
    rows = repo.client.rest_get("invites", {"select": "*", "token": f"eq.{token}", "limit": "1"})
    if not rows:
        raise _error(404, "INVITE_NOT_FOUND", "초대를 찾을 수 없어요")
    invite = rows[0]
    if invite.get("status") != "pending":
        raise _error(400, "INVITE_NOT_PENDING", "이미 사용되었거나 만료된 초대예요")
    if _parse_dt(invite["expires_at"]) < datetime.now(timezone.utc):
        repo.client.rest_patch("invites", {"id": f"eq.{invite['id']}"}, {"status": "expired"})
        raise _error(400, "INVITE_EXPIRED", "만료된 초대예요")
    return invite


@router.get("/{token}")
def get_invite(token: str):
    repo = JoinRepository()
    try:
        invite = _valid_invite(repo, token)
        return {"ok": True, "data": {k: invite.get(k) for k in ("id", "role", "merchant_id", "company_id", "phone", "email", "status", "expires_at")}, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0008_mealledger_v23.sql 적용 후 초대를 확인할 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "초대를 확인하는 중 오류가 발생했어요") from exc


@router.post("/{token}/claim")
def claim_invite(token: str, payload: InviteClaimRequest, access_token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        invite = _valid_invite(repo, token)
        auth_user = repo.auth_user_from_token(access_token)
        if invite.get("email") and (auth_user.email or "").strip().lower() != invite["email"].strip().lower():
            raise _error(403, "INVITE_EMAIL_MISMATCH", "초대받은 이메일 계정으로 가입해 주세요")
        role = invite["role"]
        values = {
            "id": auth_user.id,
            "display_name": payload.display_name or ("식당관리자" if role == "merchant_admin" else "회사관리자"),
            "role": role,
            "status": "active",
            "company_id": invite.get("company_id") if role == "company_admin" else None,
            "merchant_id": invite.get("merchant_id") if role == "merchant_admin" else None,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "rejected_at": None,
        }
        existing = repo.get_profile(auth_user.id)
        if existing:
            raise _error(409, "USER_PROFILE_EXISTS", "이미 운영자/직원 프로필이 있는 계정이에요. 초대 수락은 새 이메일 계정으로 진행해 주세요")
        user = repo.client.rest_post("app_users", values)[0]
        accepted_at = datetime.now(timezone.utc).isoformat()
        repo.client.rest_patch("invites", {"id": f"eq.{invite['id']}"}, {"status": "accepted", "accepted_at": accepted_at})
        if role == "company_admin" and invite.get("company_id"):
            repo.client.rest_patch("companies", {"id": f"eq.{invite['company_id']}"}, {"status": "active"})
        return {"ok": True, "data": {"user": user, "invite_status": "accepted"}, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0008_mealledger_v23.sql 적용 후 초대를 claim할 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "초대 claim 중 오류가 발생했어요") from exc
