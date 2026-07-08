from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

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
        return {"ok": True, "data": {k: invite.get(k) for k in ("id", "role", "merchant_id", "company_id", "phone", "status", "expires_at")}, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0008_mealledger_v23.sql 적용 후 초대를 확인할 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "초대를 확인하는 중 오류가 발생했어요") from exc


@router.post("/{token}/claim")
def claim_invite(token: str, payload: InviteClaimRequest):
    repo = JoinRepository()
    try:
        invite = _valid_invite(repo, token)
        role = invite["role"]
        values = {
            "id": payload.auth_user_id,
            "display_name": payload.display_name or ("식당관리자" if role == "merchant_admin" else "회사관리자"),
            "role": role,
            "status": "active",
            "company_id": invite.get("company_id") if role == "company_admin" else None,
            "merchant_id": invite.get("merchant_id") if role == "merchant_admin" else None,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "rejected_at": None,
        }
        existing = repo.get_profile(payload.auth_user_id)
        if existing:
            user = repo.client.rest_patch("app_users", {"id": f"eq.{payload.auth_user_id}"}, values)[0]
        else:
            user = repo.client.rest_post("app_users", values)[0]
        repo.client.rest_patch("invites", {"id": f"eq.{invite['id']}"}, {"status": "claimed"})
        if role == "company_admin" and invite.get("company_id"):
            repo.client.rest_patch("companies", {"id": f"eq.{invite['company_id']}"}, {"status": "active"})
        return {"ok": True, "data": {"user": user, "invite_status": "claimed"}, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0008_mealledger_v23.sql 적용 후 초대를 claim할 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "초대 claim 중 오류가 발생했어요") from exc
