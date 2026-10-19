from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import bearer_token
from app.config import get_settings
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.pay import pay
from app.schemas import GPSPoint, MemberQrRedeemRequest, PayRequest, TransactionScanRequest
from app.services import meal_qr
from app.services.vouchers import parse_qr_data, resolve_voucher_merchant

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _error(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def _merchant(repo: JoinRepository, qr_data: str) -> dict:
    try:
        column, value = parse_qr_data(qr_data)
    except ValueError as exc:
        raise _error(400, "INVALID_QR", "QR을 다시 스캔해 주세요") from exc
    rows = repo.client.rest_get("merchants", {
        "select": "id,name,qr_token,avg_price,status", column: f"eq.{value}", "status": "eq.active", "limit": "1",
    })
    if not rows:
        raise _error(400, "INVALID_QR", "QR을 다시 스캔해 주세요")
    return rows[0]


def _map_rpc_error(exc: SupabaseHttpError) -> HTTPException:
    body = exc.body or ""
    if "NO_VOUCHER" in body:
        return _error(402, "NO_VOUCHER", "보유 식권이 없습니다", result="fail", reason="no_voucher")
    if "IDEMPOTENCY_CONFLICT" in body:
        return _error(409, "IDEMPOTENCY_CONFLICT", "이미 다른 결제에 사용된 요청 키예요")
    if "TAX_TYPE_UNCLASSIFIED" in body:
        return _error(409, "TAX_TYPE_UNCLASSIFIED", "과세 유형이 설정되지 않아 결제할 수 없어요")
    return _error(502, "SUPABASE_ERROR", "QR 결제를 처리하지 못했어요")


def consume_meal(repo: JoinRepository, profile, merchant: dict, idempotency_key: str, gps=None) -> dict:
    """Use one voucher (or a ledger meal) for profile at merchant.

    Shared by the buyer-scans-store-QR path and the counter-scans-member-QR path
    so both charge by exactly the same rules and RPCs."""
    if profile.role == "employee" and profile.company_id:
        links = repo.client.rest_get("merchant_companies", {
            "select": "unit_price,status,subsidy_enabled", "merchant_id": f"eq.{merchant['id']}",
            "company_id": f"eq.{profile.company_id}", "status": "eq.active", "limit": "1",
        })
        amount = int(links[0]["unit_price"]) if links and links[0].get("unit_price") is not None else None
        if amount is None or amount <= 0:
            raise _error(400, "PRICE_NOT_CONFIGURED", "식당 계약 단가가 설정되지 않았어요")
        if links[0].get("subsidy_enabled"):
            result = repo.client.rpc("consume_subsidized_voucher", {"p_user_id": profile.id, "p_company_id": profile.company_id, "p_merchant_id": merchant["id"], "p_idempotency_key": idempotency_key})
            companies = repo.client.rest_get("companies", {"select": "name", "id": f"eq.{profile.company_id}", "limit": "1"})
            return {"result": "success", "pay_type": "subsidized", "company_name": companies[0]["name"] if companies else None, "remaining": result["remaining"], "transaction": result}
        return {"ledger_amount": amount}  # ledger: caller pays with the buyer's own token
    if profile.role == "customer":
        result = repo.client.rpc("consume_voucher", {
            "p_user_id": profile.id, "p_merchant_id": merchant["id"],
            "p_idempotency_key": idempotency_key,
        })
        return {"result": "success", "pay_type": "voucher", "remaining": result["remaining"],
            "transaction": result, "merchant": {"id": merchant["id"], "name": merchant["name"]}}
    raise _error(403, "ACCOUNT_TYPE_NOT_SUPPORTED", "이 계정은 QR 결제를 사용할 수 없어요")


@router.post("/scan")
def scan(payload: TransactionScanRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        auth = repo.auth_user_from_token(token)
        profile = repo.get_profile(auth.id, email=auth.email)
        if profile is None or profile.status != "active":
            raise _error(403, "ACCOUNT_INACTIVE", "비활성화된 계정입니다")
        merchant = _merchant(repo, payload.qr_data)
        pilot_merchant = resolve_voucher_merchant(repo, get_settings().pilot_merchant_id)
        if not pilot_merchant or merchant["id"] != pilot_merchant["id"]:
            raise _error(400, "INVALID_QR", "QR을 다시 스캔해 주세요")

        used = consume_meal(repo, profile, merchant, payload.idempotency_key)
        if "ledger_amount" not in used:
            return used
        # Ledger employee (no subsidy): legacy pay path with GPS/policy checks.
        amount = used["ledger_amount"]
        legacy = pay(PayRequest(
            qr_token=merchant["qr_token"], amount=amount,
            gps=GPSPoint(lat=payload.gps.lat, lng=payload.gps.lng) if payload.gps else None,
            idempotency_key=payload.idempotency_key,
        ), token)
        companies = repo.client.rest_get("companies", {
            "select": "name", "id": f"eq.{profile.company_id}", "limit": "1",
        })
        return {"result": "success", "pay_type": "ledger",
            "company_name": companies[0]["name"] if companies else None,
            "remaining": None, "transaction": legacy["data"]["payment"]}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _map_rpc_error(exc) from exc


@router.get("/member-qr")
def member_qr(token: str = Depends(bearer_token)):
    """Issue the buyer's 60-second meal QR (shown in the app/web, read by the counter scanner)."""
    repo = JoinRepository()
    try:
        auth = repo.auth_user_from_token(token)
        profile = repo.get_profile(auth.id, email=auth.email)
    except SupabaseHttpError as exc:
        raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
    if profile is None or profile.status != "active" or profile.role not in {"customer", "employee"}:
        raise _error(403, "ACCOUNT_TYPE_NOT_SUPPORTED", "이 계정은 QR 결제를 사용할 수 없어요")
    code, expires_at = meal_qr.issue(profile.id, get_settings().meal_qr_secret)
    return {"ok": True, "data": {"code": code, "expires_at": expires_at, "ttl": meal_qr.TTL_SECONDS}, "error": None}


@router.post("/member-qr/redeem")
def redeem_member_qr(payload: MemberQrRedeemRequest, token: str = Depends(bearer_token)):
    """Restaurant counter: redeem a scanned member QR for exactly one meal at this merchant."""
    from app.routers.merchant_admin import JoinFlowError, _merchant_admin

    repo = JoinRepository()
    try:
        try:
            _, merchant_id = _merchant_admin(repo, token)
        except JoinFlowError as exc:
            raise _error(403, "FORBIDDEN", "식당관리자 계정으로 로그인해 주세요") from exc
        try:
            claim = meal_qr.verify(payload.code, get_settings().meal_qr_secret)
        except meal_qr.MealQrError as exc:
            raise _error(400, exc.code, exc.message) from exc
        merchants = repo.client.rest_get("merchants", {
            "select": "id,name,qr_token,status", "id": f"eq.{merchant_id}", "status": "eq.active", "limit": "1",
        })
        if not merchants:
            raise _error(403, "MERCHANT_NOT_ACTIVE", "식당이 활성 상태가 아니에요")
        merchant = merchants[0]
        member = repo.get_profile(claim.user_id)
        if member is None or member.status != "active":
            raise _error(403, "ACCOUNT_INACTIVE", "사용할 수 없는 회원이에요")
        used = consume_meal(repo, member, merchant, claim.idempotency_key)
        if "ledger_amount" in used:
            raise _error(400, "LEDGER_NOT_SUPPORTED", "장부 결제 회원은 앱에서 매장 QR을 찍어 주세요")
        tx = used.get("transaction") or {}
        return {
            "ok": True,
            "data": {
                "result": "success",
                "duplicate": bool(tx.get("duplicate")),
                "pay_type": used["pay_type"],
                "member_name": member.display_name,
                "remaining": used.get("remaining"),
                "amount": tx.get("total_amount", tx.get("amount")),
                "transaction_id": tx.get("id"),
                "used_at": tx.get("created_at"),
            },
            "error": None,
        }
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _map_rpc_error(exc) from exc
