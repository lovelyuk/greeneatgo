from __future__ import annotations

import re
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


_HHMM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def _policy_from_row(row: dict | None) -> MealPolicy:
    if not row:
        return MealPolicy(meal_windows=UNRESTRICTED_WINDOWS)
    windows = []
    for item in row.get("meal_windows") or []:
        # A stored window with an unreadable time must not break every payment.
        if not all(_HHMM.fullmatch(str(item.get(key) or default)) for key, default in (("start", "00:00"), ("end", "23:59"))):
            continue
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
        "INVALID_AMOUNT": (400, "INVALID_AMOUNT", "결제 금액이 올바르지 않아요"),
        "PRICE_NOT_CONFIGURED": (400, "PRICE_NOT_CONFIGURED", "식당 계약 단가가 설정되지 않았어요"),
        "CONTRACT_PRICE_MISMATCH": (409, "CONTRACT_PRICE_MISMATCH", "계약 단가가 변경되었어요. 다시 시도해 주세요"),
        "PREPURCHASE_INVENTORY_EMPTY": (409, "PREPURCHASE_INVENTORY_EMPTY", "선구매 식권 잔여 수량이 없어요"),
        "IDEMPOTENCY_CONFLICT": (409, "IDEMPOTENCY_CONFLICT", "이미 다른 결제에 사용된 요청 키예요"),
        "TAX_TYPE_UNCLASSIFIED": (409, "TAX_TYPE_UNCLASSIFIED", "과세 유형이 설정되지 않아 결제할 수 없어요"),
        "NOT_COMPANY_MEMBER": (403, "FORBIDDEN", "활성 직원 계정만 결제할 수 있어요"),
        "MONTHLY_LIMIT": (400, "MONTHLY_LIMIT", "월 한도를 초과해요"),
        "DAILY_LIMIT": (400, "DAILY_LIMIT", "오늘 사용 한도를 초과해요"),
        "DAILY_COUNT_LIMIT": (400, "DAILY_COUNT_LIMIT", "오늘 회사 식대 사용 횟수를 넘어요"),
        "INVALID_QUANTITY": (400, "INVALID_QUANTITY", "한 번에 1~10끼까지 결제할 수 있어요"),
    }
    for key, value in mapping.items():
        if key in body:
            return _error(*value)
    if "prepurchase_enabled" in body or "process_meal_pay" in body or "PGRST202" in body:
        return _error(400, "MIGRATION_REQUIRED", "0062_merchant_company_prepurchase.sql 적용 후 실제 결제를 사용할 수 있어요")
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
        result = charge_ledger_meal(repo, user, merchant, payload.amount, payload.gps, payload.idempotency_key)
        return {"ok": True, "data": {"merchant": merchant, "payment": result}, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _map_rpc_error(exc) from exc


_POLICY_SELECT = "meal_windows,daily_limit,weekend_allowed"


def meal_policy_row(repo: JoinRepository, company_id: str, select: str = _POLICY_SELECT) -> dict | None:
    """The company's meal policy row, with `daily_count_limit` when the column exists (0083)."""
    params = {"company_id": f"eq.{company_id}", "group_id": "is.null", "limit": "1"}
    try:
        rows = repo.client.rest_get("meal_policies", {"select": f"{select},daily_count_limit", **params})
    except SupabaseHttpError as exc:
        if "daily_count_limit" not in (exc.body or ""):
            raise
        rows = repo.client.rest_get("meal_policies", {"select": select, **params})
    return rows[0] if rows else None


def daily_count_limit_of(row: dict | None) -> int | None:
    value = (row or {}).get("daily_count_limit")
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def ledger_meals_today(tx_rows: list[dict], today_start: datetime) -> int:
    """Company-ledger meals since `today_start`; a cancelled meal gives its turn back."""
    count = 0
    for row in tx_rows:
        if row.get("pay_type") != "ledger" or row.get("kind") not in ("spend", "cancel", "refund") or not row.get("created_at"):
            continue
        if datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) >= today_start:
            count += 1 if row.get("kind") == "spend" else -1
    return max(count, 0)


def charge_ledger_meal(repo: JoinRepository, user, merchant: dict, amount: int, gps, idempotency_key: str,
                       quantity: int = 1) -> dict:
    """`quantity` company-ledger meals for `user` at `merchant`: policy, limits, then the RPC.

    All of them are recorded or none (one database transaction).

    Shared by the employee scanning the store QR (`/pay`, called with the
    employee's own login) and the counter scanning the employee's member QR
    (the signed QR identifies the employee). Both are charged by the same rules.
    Raises HTTPException for a refusal and SupabaseHttpError for the caller to map."""
    if user is None or user.status != "active" or user.role != "employee" or not user.company_id:
        raise _error(403, "FORBIDDEN", "활성 직원 계정만 결제할 수 있어요")
    if not 1 <= quantity <= 10:
        raise _error(400, "INVALID_QUANTITY", "한 번에 1~10끼까지 결제할 수 있어요")
    policy_row = meal_policy_row(repo, user.company_id)
    policy = _policy_from_row(policy_row)
    count_limit = daily_count_limit_of(policy_row)

    tx_rows = repo.client.rest_get(
        "normal_meal_transactions",
        {"select": "amount,kind,created_at,pay_type", "user_id": f"eq.{user.id}"},
    )
    # Meals paid with a personal voucher are not company spending (0077).
    tx_rows = [row for row in tx_rows if row.get("pay_type") != "voucher"]
    now = datetime.now(timezone.utc)
    today_start = _today_start_utc(now)
    month_start = _month_start_utc(now)
    # A meal the restaurant cancelled gives its amount back (0079).
    signed = [
        (abs(int(row.get("amount") or 0)) * (1 if row.get("kind") == "spend" else -1),
         datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")))
        for row in tx_rows if row.get("kind") in ("spend", "cancel", "refund") and row.get("created_at")
    ]
    spent_today = sum(amount_ for amount_, at in signed if at >= today_start)
    spent_month = sum(amount_ for amount_, at in signed if at >= month_start)
    monthly_limit = _employee_monthly_limit(repo, user.id)
    if spent_month + amount * quantity > monthly_limit:
        raise _error(400, "MONTHLY_LIMIT", f"월 한도 {monthly_limit:,}원을 초과해요")
    if count_limit is not None:
        used = ledger_meals_today(tx_rows, today_start)
        if used + quantity > count_limit:
            left = max(count_limit - used, 0)
            raise _error(400, "DAILY_COUNT_LIMIT", (
                f"회사 식대는 하루 {count_limit}번까지예요. 오늘은 {left}번 더 쓸 수 있어요" if left
                else f"오늘 회사 식대 사용 횟수 {count_limit}번을 모두 썼어요"))

    draft = prepare_payment_draft(PaymentContext(
        user_id=user.id,
        company_id=user.company_id,
        merchant=MerchantSnapshot(id=merchant["id"], name=merchant["name"], lat=merchant.get("lat"), lng=merchant.get("lng")),
        amount=amount,
        # The per-meal limit is judged per meal, the daily amount on all of them.
        spent_today=spent_today + amount * (quantity - 1),
        policy=policy,
        now=datetime.now(timezone.utc),
        gps_lat=gps.lat if gps else None,
        gps_lng=gps.lng if gps else None,
    ))
    if not draft.ok:
        raise _error(400, draft.code or "POLICY_BLOCKED", draft.message or "결제 정책에 맞지 않아요")

    args = {
        "p_user_id": user.id,
        "p_company_id": user.company_id,
        "p_merchant_id": merchant["id"],
        "p_amount": amount,
        "p_tx_code": draft.tx_code,
        "p_meal_window": draft.meal_window,
        "p_flags": draft.flags,
        "p_idempotency_key": idempotency_key,
    }
    try:
        # Checks the daily count under a lock and records every meal in one transaction.
        return repo.client.rpc("process_meal_pay_many", {**args, "p_quantity": quantity})
    except SupabaseHttpError as exc:
        missing = "process_meal_pay_many" in (exc.body or "") and ("PGRST202" in exc.body or "42883" in exc.body)
        if not missing:
            raise
        if quantity > 1:
            raise _error(400, "MIGRATION_REQUIRED", "여러 끼 결제는 아직 준비 중이에요") from exc
    # Migration 0083 not applied yet: one meal through the original function.
    return repo.client.rpc("process_meal_pay", {**args, "p_product_id": None, "p_product_name": None, "p_product_price": None})
