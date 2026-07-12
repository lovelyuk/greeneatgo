from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import bearer_token
from app.config import get_settings
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.pay import pay
from app.schemas import GPSPoint, PayRequest, TransactionScanRequest
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

        if profile.role == "employee" and profile.company_id:
            links = repo.client.rest_get("merchant_companies", {
                "select": "unit_price,status,subsidy_enabled", "merchant_id": f"eq.{merchant['id']}",
                "company_id": f"eq.{profile.company_id}", "status": "eq.active", "limit": "1",
            })
            amount = int(links[0]["unit_price"]) if links and links[0].get("unit_price") is not None else None
            if amount is None or amount <= 0:
                raise _error(400, "PRICE_NOT_CONFIGURED", "식당 계약 단가가 설정되지 않았어요")
            if links[0].get("subsidy_enabled"):
                result = repo.client.rpc("consume_subsidized_voucher", {"p_user_id": profile.id, "p_company_id": profile.company_id, "p_merchant_id": merchant["id"], "p_idempotency_key": payload.idempotency_key})
                companies = repo.client.rest_get("companies", {"select": "name", "id": f"eq.{profile.company_id}", "limit": "1"})
                return {"result": "success", "pay_type": "subsidized", "company_name": companies[0]["name"] if companies else None, "remaining": result["remaining"], "transaction": result}
            legacy = pay(PayRequest(
                qr_token=merchant["qr_token"], amount=amount, product_id=None,
                gps=GPSPoint(lat=payload.gps.lat, lng=payload.gps.lng) if payload.gps else None,
                idempotency_key=payload.idempotency_key,
            ), token)
            companies = repo.client.rest_get("companies", {
                "select": "name", "id": f"eq.{profile.company_id}", "limit": "1",
            })
            return {"result": "success", "pay_type": "ledger",
                "company_name": companies[0]["name"] if companies else None,
                "remaining": None, "transaction": legacy["data"]["payment"]}

        if profile.role == "customer":
            result = repo.client.rpc("consume_voucher", {
                "p_user_id": profile.id, "p_merchant_id": merchant["id"],
                "p_idempotency_key": payload.idempotency_key,
            })
            return {"result": "success", "pay_type": "voucher", "remaining": result["remaining"],
                "transaction": result, "merchant": {"id": merchant["id"], "name": merchant["name"]}}

        raise _error(403, "ACCOUNT_TYPE_NOT_SUPPORTED", "이 계정은 QR 결제를 사용할 수 없어요")
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        if "NO_VOUCHER" in (exc.body or ""):
            raise _error(402, "NO_VOUCHER", "보유 식권이 없습니다", result="fail", reason="no_voucher") from exc
        if "IDEMPOTENCY_CONFLICT" in (exc.body or ""):
            raise _error(409, "IDEMPOTENCY_CONFLICT", "이미 다른 결제에 사용된 요청 키예요") from exc
        raise _error(502, "SUPABASE_ERROR", "QR 결제를 처리하지 못했어요") from exc
