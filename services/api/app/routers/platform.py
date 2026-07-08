from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.schemas import InviteCreateRequest, PlatformMerchantCreateRequest
from app.services.join_flow import JoinFlowError

router = APIRouter(prefix="/admin/platform", tags=["platform"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _platform_admin(repo: JoinRepository, token: str):
    auth = repo.auth_user_from_token(token)
    actor = repo.get_profile(auth.id, email=auth.email)
    if actor is None or actor.role != "platform_admin" or actor.status != "active":
        raise JoinFlowError("FORBIDDEN", "플랫폼 운영자만 이용할 수 있어요")
    return actor


def _token() -> str:
    return secrets.token_urlsafe(32)


@router.get("/merchants")
def list_merchants(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _platform_admin(repo, token)
        rows = repo.client.rest_get(
            "merchants",
            {"select": "id,name,owner_phone,category,avg_price,qr_token,status,created_at", "order": "created_at.desc", "limit": "100"},
        )
        return {"ok": True, "data": {"items": rows}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "식당 목록을 불러오는 중 오류가 발생했어요") from exc


@router.post("/merchants")
def create_merchant(payload: PlatformMerchantCreateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _platform_admin(repo, token)
        invite_token = _token()
        row = repo.client.rest_post("merchants", {
            "name": payload.name,
            "owner_phone": payload.owner_phone,
            "category": payload.category,
            "avg_price": payload.avg_price,
            "qr_token": f"QR-{invite_token[:18]}",
            "view_token": f"VIEW-{invite_token[19:37]}",
            "status": "active",
        })[0]
        return {"ok": True, "data": row, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "식당을 등록하는 중 오류가 발생했어요") from exc


@router.post("/merchants/{merchant_id}/invite")
def invite_merchant_admin(merchant_id: str, payload: InviteCreateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _platform_admin(repo, token)
        merchants = repo.client.rest_get("merchants", {"select": "id,name", "id": f"eq.{merchant_id}", "limit": "1"})
        if not merchants:
            raise JoinFlowError("MERCHANT_NOT_FOUND", "식당을 찾을 수 없어요")
        row = repo.client.rest_post("invites", {
            "token": _token(),
            "role": "merchant_admin",
            "merchant_id": merchant_id,
            "phone": payload.phone,
            "invited_by": actor.id,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        })[0]
        # SMS/Kakao provider is not connected yet; return the token so the operator can deliver it manually.
        return {"ok": True, "data": {**row, "delivery": "manual"}, "error": None}
    except JoinFlowError as exc:
        status = 404 if str(exc.code) == "MERCHANT_NOT_FOUND" else 403
        raise _error(status, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0008_mealledger_v23.sql 적용 후 초대를 만들 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "식당관리자 초대를 만드는 중 오류가 발생했어요") from exc
