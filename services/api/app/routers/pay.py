from __future__ import annotations

from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.schemas import PayRequest
from app.services.payment import MerchantSnapshot, PaymentContext, prepare_payment_draft
from app.services.policy_engine import KST, MealPolicy, MealWindow, UNRESTRICTED_WINDOWS

router = APIRouter(tags=["pay"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _policy_from_row(row: dict | None) -> MealPolicy:
    if not row:
        return MealPolicy(meal_windows=UNRESTRICTED_WINDOWS)
    windows = []
    for item in row.get("meal_windows") or []:
        windows.append(MealWindow(
            name=item.get("name") or "식대",
            start=item.get("start") or "00:00",
            end=item.get("end") or "23:59",
            per_meal_limit=int(item.get("per_meal_limit") or 10_000_000),
        ))
    return MealPolicy(
        meal_windows=tuple(windows) or UNRESTRICTED_WINDOWS,
        daily_limit=row.get("daily_limit"),
        weekend_allowed=bool(row.get("weekend_allowed")),
    )


def _today_start_utc(now: datetime) -> datetime:
    local = now.astimezone(KST)
    start_local = datetime.combine(local.date(), time.min, tzinfo=KST)
    return start_local.astimezone(timezone.utc)


def _month_start_utc(now: datetime) -> datetime:
    local = now.astimezone(KST)
    start_local = datetime(local.year, local.month, 1, tzinfo=KST)
    return start_local.astimezone(timezone.utc)


def _employee_monthly_limit(repo: JoinRepository, user_id: str) -> int:
    try:
        rows = repo.client.rest_get("app_users", {"select": "monthly_limit", "id": f"eq.{user_id}", "limit": "1"})
        if rows and rows[0].get("monthly_limit") is not None:
            return int(rows[0]["monthly_limit"])
    except SupabaseHttpError as exc:
        if "monthly_limit" not in exc.body and "PGRST204" not in exc.body:
            raise
    return 200000


def _map_rpc_error(exc: SupabaseHttpError) -> HTTPException:
    body = exc.body or ""
    mapping = {
        "COMPANY_NOT_ACTIVE": (403, "COMPANY_NOT_ACTIVE", "회사 담당자 활성화 전이라 결제할 수 없어요"),
        "NOT_AFFILIATED": (403, "NOT_AFFILIATED", "이 식당은 우리 회사 제휴 식당이 아니에요"),
        "INSUFFICIENT": (400, "INSUFFICIENT", "잔액이 부족해요"),
        "INVALID_AMOUNT": (400, "INVALID_AMOUNT", "결제 금액이 올바르지 않아요"),
    }
    for key, value in mapping.items():
        if key in body:
            return _error(*value)
    if "process_meal_pay" in body or "PGRST202" in body:
        return _error(400, "MIGRATION_REQUIRED", "0009_process_meal_pay.sql 적용 후 실제 결제를 사용할 수 있어요")
    return _error(502, "SUPABASE_ERROR", "결제 처리 중 오류가 발생했어요")


@router.post("/pay")
def pay(payload: PayRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        auth = repo.auth_user_from_token(token)
        user = repo.get_profile(auth.id, email=auth.email)
        if user is None or user.status != "active" or user.role != "employee" or not user.company_id:
            raise _error(403, "FORBIDDEN", "활성 직원 계정만 결제할 수 있어요")

        merchants = repo.client.rest_get(
            "merchants",
            {"select": "id,name,lat,lng,status", "qr_token": f"eq.{payload.qr_token}", "status": "eq.active", "limit": "1"},
        )
        if not merchants:
            raise _error(404, "MERCHANT_NOT_FOUND", "식당 QR을 찾을 수 없어요")
        merchant = merchants[0]

        amount = payload.amount
        product = None
        if payload.product_id:
            products = repo.client.rest_get(
                "merchant_products",
                {"select": "id,name,price,merchant_id,is_active", "id": f"eq.{payload.product_id}", "merchant_id": f"eq.{merchant['id']}", "is_active": "eq.true", "limit": "1"},
            )
            if not products:
                raise _error(404, "PRODUCT_NOT_FOUND", "상품을 찾을 수 없어요")
            product = products[0]
            amount = int(product["price"])

        policy_rows = repo.client.rest_get(
            "meal_policies",
            {"select": "meal_windows,daily_limit,weekend_allowed", "company_id": f"eq.{user.company_id}", "group_id": "is.null", "limit": "1"},
        )
        policy = _policy_from_row(policy_rows[0] if policy_rows else None)

        tx_rows = repo.client.rest_get(
            "meal_transactions",
            {"select": "amount,kind,created_at", "user_id": f"eq.{user.id}"},
        )
        now = datetime.now(timezone.utc)
        balance = sum(int(row.get("amount") or 0) for row in tx_rows)
        today_start = _today_start_utc(now)
        month_start = _month_start_utc(now)
        spent_today = sum(
            abs(int(row.get("amount") or 0))
            for row in tx_rows
            if row.get("kind") == "spend" and datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) >= today_start
        )
        spent_month = sum(
            abs(int(row.get("amount") or 0))
            for row in tx_rows
            if row.get("kind") == "spend" and datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) >= month_start
        )
        monthly_limit = _employee_monthly_limit(repo, user.id)
        if spent_month + amount > monthly_limit:
            raise _error(400, "MONTHLY_LIMIT", f"월 한도 {monthly_limit:,}원을 초과해요")

        draft = prepare_payment_draft(PaymentContext(
            user_id=user.id,
            company_id=user.company_id,
            merchant=MerchantSnapshot(id=merchant["id"], name=merchant["name"], lat=merchant.get("lat"), lng=merchant.get("lng")),
            amount=amount,
            balance=balance,
            spent_today=spent_today,
            policy=policy,
            now=datetime.now(timezone.utc),
            gps_lat=payload.gps.lat if payload.gps else None,
            gps_lng=payload.gps.lng if payload.gps else None,
        ))
        if not draft.ok:
            raise _error(400, draft.code or "POLICY_BLOCKED", draft.message or "결제 정책에 맞지 않아요")

        result = repo.client.rpc("process_meal_pay", {
            "p_user_id": user.id,
            "p_company_id": user.company_id,
            "p_merchant_id": merchant["id"],
            "p_amount": amount,
            "p_tx_code": draft.tx_code,
            "p_meal_window": draft.meal_window,
            "p_flags": draft.flags,
            "p_idempotency_key": payload.idempotency_key,
            "p_product_id": product["id"] if product else None,
            "p_product_name": product["name"] if product else None,
            "p_product_price": product["price"] if product else None,
        })
        return {"ok": True, "data": {"merchant": merchant, "payment": result}, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _map_rpc_error(exc) from exc
