from datetime import datetime, timedelta, timezone
import secrets

from fastapi import APIRouter, Depends, HTTPException

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.schemas import ProfileNameUpdateRequest
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
    limit_rows = repo.client.rest_get("app_users", {"select": "monthly_limit", "id": f"eq.{user_id}", "limit": "1"})
    monthly_limit = int((limit_rows[0].get("monthly_limit") if limit_rows else None) or 200000)
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
    point_users = repo.client.rest_get("app_users", {"select": "point_balance", "id": f"eq.{user_id}", "limit": "1"})
    point_rows = repo.client.rest_get("point_transactions", {"select": "id,type,amount,balance_after,reason,related_voucher_id,related_order_id,created_at", "user_id": f"eq.{user_id}", "order": "created_at.desc", "limit": "50"})
    return {
        "balance": balance,
        "monthly_limit": monthly_limit,
        "remaining_limit": max(monthly_limit - month_used, 0),
        "month_used": month_used,
        "recent_transactions": recent_transactions,
        "voucher_balance": None,
        "voucher_use_history": [],
        "point_balance": int(point_users[0].get("point_balance") or 0) if point_users else 0,
        "point_transactions": point_rows,
    }


def _customer_usage(repo: JoinRepository, user_id: str) -> dict:
    voucher_balance = int(repo.client.rpc("voucher_balance", {"p_user_id": user_id}) or 0)
    voucher_rows = repo.client.rest_get(
        "meal_transactions",
        {
            "select": "id,amount,kind,product_name,merchant_id,voucher_id,created_at,pay_type",
            "user_id": f"eq.{user_id}", "pay_type": "eq.voucher",
            "order": "created_at.desc", "limit": "20",
        },
    )
    direct_rows = repo.client.rest_get(
        "toss_payment_orders",
        {
            "select": "id,amount,product_name,merchant_name,approved_at,created_at,pay_type",
            "user_id": f"eq.{user_id}", "status": "eq.done", "pay_type": "eq.direct",
            "order": "approved_at.desc", "limit": "20",
        },
    )
    merchant_ids = sorted({str(row.get("merchant_id")) for row in voucher_rows if row.get("merchant_id")})
    merchants = {}
    if merchant_ids:
        merchant_rows = repo.client.rest_get("merchants", {"select": "id,name", "id": f"in.({','.join(merchant_ids)})"})
        merchants = {row["id"]: row["name"] for row in merchant_rows}
    voucher_history = [
        {
            "id": row.get("id"), "voucher_id": row.get("voucher_id"),
            "amount": abs(int(row.get("amount") or 0)), "kind": "voucher_use",
            "title": row.get("product_name") or "식권 사용",
            "merchant_name": merchants.get(row.get("merchant_id"), ""),
            "created_at": row.get("created_at"),
        }
        for row in voucher_rows
    ]
    direct_history = [
        {
            "id": row.get("id"), "amount": int(row.get("amount") or 0),
            "kind": "toss_payment", "title": row.get("product_name") or "상품 결제",
            "merchant_name": row.get("merchant_name") or "",
            "created_at": row.get("approved_at") or row.get("created_at"),
        }
        for row in direct_rows
    ]
    combined = sorted(voucher_history + direct_history, key=lambda row: row.get("created_at") or "", reverse=True)
    return {
        "balance": None, "monthly_limit": None, "remaining_limit": None, "month_used": None,
        "recent_transactions": combined[:3], "voucher_balance": voucher_balance,
        "voucher_use_history": voucher_history,
    }


@router.patch("/me")
def update_admin_name(payload: ProfileNameUpdateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        auth_user = repo.auth_user_from_token(token)
        profile = repo.get_profile(auth_user.id, email=auth_user.email)
        if profile is None:
            raise _error(404, "PROFILE_NOT_FOUND", "관리자 프로필을 찾을 수 없어요")
        if profile.role not in {"company_admin", "merchant_admin"}:
            raise _error(403, "FORBIDDEN", "업체관리자 또는 식당관리자만 이름을 수정할 수 있어요")
        rows = repo.client.rest_patch(
            "app_users",
            {"id": f"eq.{profile.id}"},
            {"display_name": payload.display_name},
        )
        if not rows:
            raise _error(404, "PROFILE_NOT_FOUND", "관리자 프로필을 찾을 수 없어요")
        return {"ok": True, "data": {"display_name": rows[0].get("display_name") or payload.display_name}, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "관리자 이름을 저장하는 중 오류가 발생했어요") from exc


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
    usage = {"balance": None, "monthly_limit": None, "remaining_limit": None, "month_used": None,
             "recent_transactions": [], "voucher_balance": None, "voucher_use_history": []}
    try:
        if profile.role == "company_admin" and profile.company_id:
            invite_code = _ensure_invite_code(repo, profile.company_id)
        if profile.role == "employee":
            usage = _employee_usage(repo, profile.id)
        elif profile.role == "customer":
            usage = _customer_usage(repo, profile.id)
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
            "account_type": "ledger" if profile.role == "employee" else ("voucher" if profile.role == "customer" else None),
            "status": profile.status,
            "invite_code": invite_code,
            "balance": usage["balance"],
            "monthly_limit": usage["monthly_limit"],
            "remaining_limit": usage["remaining_limit"],
            "month_used": usage["month_used"],
            "recent_transactions": usage["recent_transactions"],
            "voucher_balance": usage["voucher_balance"],
            "voucher_use_history": usage["voucher_use_history"],
            "point_balance": usage.get("point_balance"),
            "point_transactions": usage.get("point_transactions", []),
        },
        "error": None,
    }
