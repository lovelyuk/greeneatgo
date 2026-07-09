from datetime import datetime, timedelta, timezone
import secrets

from fastapi import APIRouter, Depends, HTTPException

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.services.join_flow import JoinFlowError

router = APIRouter(tags=["me"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _new_invite_code() -> str:
    return f"GE-{secrets.token_hex(3).upper()}"


def _ensure_invite_code(repo: JoinRepository, company_id: str) -> str | None:
    codes = repo.client.rest_get(
        "company_invite_codes",
        {"select": "code", "company_id": f"eq.{company_id}", "is_active": "eq.true", "order": "created_at.desc", "limit": "1"},
    )
    if codes:
        return codes[0]["code"]
    for _ in range(5):
        code = _new_invite_code()
        try:
            repo.client.rest_post("company_invite_codes", {"company_id": company_id, "code": code, "is_active": True})
            return code
        except SupabaseHttpError as exc:
            if "duplicate" not in exc.body.lower() and "unique" not in exc.body.lower():
                raise
    return None


def _month_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    kst = timezone(timedelta(hours=9))
    local = now.astimezone(kst)
    return datetime(local.year, local.month, 1, tzinfo=kst).astimezone(timezone.utc)


def _employee_usage(repo: JoinRepository, user_id: str) -> dict:
    rows = repo.client.rest_get(
        "meal_transactions",
        {"select": "id,amount,kind,tx_code,meal_window,product_name,merchant_id,created_at", "user_id": f"eq.{user_id}", "order": "created_at.desc"},
    )
    month_start = _month_start_utc()
    balance = sum(int(row.get("amount") or 0) for row in rows)
    month_used = 0
    recent_spends = []
    for row in rows:
        if row.get("kind") != "spend":
            continue
        created_at = row.get("created_at")
        if created_at:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created >= month_start:
                month_used += abs(int(row.get("amount") or 0))
        if len(recent_spends) < 3:
            recent_spends.append(row)
    merchant_ids = sorted({str(row.get("merchant_id")) for row in recent_spends if row.get("merchant_id")})
    merchants = {}
    if merchant_ids:
        merchant_rows = repo.client.rest_get("merchants", {"select": "id,name", "id": f"in.({','.join(merchant_ids)})"})
        merchants = {row["id"]: row["name"] for row in merchant_rows}
    recent_transactions = [
        {
            "id": row.get("id"),
            "amount": abs(int(row.get("amount") or 0)),
            "kind": row.get("kind"),
            "title": row.get("product_name") or row.get("meal_window") or "식대 사용",
            "merchant_name": merchants.get(row.get("merchant_id"), ""),
            "created_at": row.get("created_at"),
        }
        for row in recent_spends
    ]
    return {"balance": balance, "month_used": month_used, "recent_transactions": recent_transactions}


@router.get("/me")
def me(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        auth_user = repo.auth_user_from_token(token)
        profile = repo.get_profile(auth_user.id, email=auth_user.email)
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "Supabase 처리 중 오류가 발생했어요") from exc

    if profile is None:
        return {
            "ok": True,
            "data": {
                "user_id": auth_user.id,
                "email": auth_user.email,
                "status": "no_profile",
            },
            "error": None,
        }

    invite_code = None
    usage = {"balance": None, "month_used": None, "recent_transactions": []}
    try:
        if profile.role == "company_admin" and profile.company_id:
            invite_code = _ensure_invite_code(repo, profile.company_id)
        if profile.role == "employee":
            usage = _employee_usage(repo, profile.id)
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "사용자 정보를 불러오는 중 오류가 발생했어요") from exc

    return {
        "ok": True,
        "data": {
            "user_id": profile.id,
            "email": auth_user.email,
            "display_name": profile.display_name,
            "company_id": profile.company_id,
            "merchant_id": profile.merchant_id,
            "group_id": profile.group_id,
            "role": profile.role,
            "status": profile.status,
            "invite_code": invite_code,
            "balance": usage["balance"],
            "month_used": usage["month_used"],
            "recent_transactions": usage["recent_transactions"],
        },
        "error": None,
    }
