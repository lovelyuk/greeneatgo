from __future__ import annotations

import json
import secrets
import time
import uuid
from datetime import datetime, timezone
from html import escape
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from app.auth import bearer_token
from app.config import get_settings
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.voucher_products import _is_exposed, _load_products
from app.schemas import PaymentConfirmRequest, PaymentOrderCreateRequest
from app.services.kiwoom_payment import KiwoomHashInput, KiwoomPaymentError, request_payment_hash

router = APIRouter(prefix="/payments", tags=["payments"])

ORDER_SELECT = (
    "id,order_id,checkout_token,user_id,merchant_id,product_id,merchant_name,"
    "product_name,amount,status,provider_payment_key,payment_method,approved_at,created_at,"
    "pay_type,voucher_product_id,voucher_count,voucher_purchase_price,fulfilled_at,provider_response,"
    "company_id,company_subsidy_amount,restaurant_subsidy_amount,point_amount,point_reserved,"
    "requested_payment_method"
)


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _customer(repo: JoinRepository, token: str, *, allow_employee: bool = False):
    auth = repo.auth_user_from_token(token)
    profile = repo.get_profile(auth.id, email=auth.email)
    allowed = profile and profile.status == "active" and (
        profile.role == "customer" or (allow_employee and profile.role == "employee")
    )
    if not allowed:
        raise _error(403, "CUSTOMER_ONLY", "결제 가능한 사용자 계정이 아니에요")
    return auth, profile


def _ensure_voucher_order_available(repo: JoinRepository, order: dict) -> None:
    if order.get("pay_type") != "voucher":
        return
    product_id, merchant_id = order.get("voucher_product_id"), order.get("merchant_id")
    if not product_id or not merchant_id:
        raise _error(409, "INVALID_VOUCHER_ORDER", "식권 상품 정보가 없는 주문이에요")
    products, _ = _load_products(repo, {
        "id": f"eq.{product_id}", "merchant_id": f"eq.{merchant_id}",
        "status": "eq.active", "limit": "1",
    })
    if not products or not _is_exposed(products[0]):
        raise _error(409, "VOUCHER_PRODUCT_NOT_EXPOSED", "이벤트가 종료되었거나 판매가 중지된 상품이에요")


def _safe_text(value: object, limit: int) -> str:
    return str(value or "").replace("|", " ")[:limit]


@router.post("/orders")
def create_order(payload: PaymentOrderCreateRequest, token: str = Depends(bearer_token)):
    repo, settings = JoinRepository(), get_settings()
    try:
        _, profile = _customer(repo, token)
        merchants = repo.client.rest_get("merchants", {
            "select": "id,name", "qr_token": f"eq.{payload.qr_token}",
            "status": "eq.active", "limit": "1",
        })
        if not merchants:
            raise _error(404, "MERCHANT_NOT_FOUND", "식당을 찾을 수 없어요")
        merchant = merchants[0]
        products = repo.client.rest_get("merchant_products", {
            "select": "id,name,price,merchant_id,is_active", "id": f"eq.{payload.product_id}",
            "merchant_id": f"eq.{merchant['id']}", "is_active": "eq.true", "limit": "1",
        })
        if not products:
            raise _error(404, "PRODUCT_NOT_FOUND", "판매 중인 상품을 찾을 수 없어요")
        product, order_id, checkout_token = products[0], f"GE-{uuid.uuid4().hex}", secrets.token_urlsafe(32)
        order = repo.client.rest_post("payment_orders", {
            "order_id": order_id, "checkout_token": checkout_token, "user_id": profile.id,
            "merchant_id": merchant["id"], "product_id": product["id"],
            "merchant_name": merchant["name"], "product_name": product["name"],
            "amount": int(product["price"]), "status": "ready", "pay_type": "direct",
            "requested_payment_method": "TOTAL",
        })[0]
        return {"ok": True, "data": {
            "order_id": order_id, "amount": order["amount"], "product_name": order["product_name"],
            "merchant_name": order["merchant_name"],
            "checkout_url": f"{settings.public_api_base_url}/payments/checkout/{checkout_token}",
        }, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        if "payment_orders" in exc.body or "PGRST205" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "결제 DB 마이그레이션 적용이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "결제 주문 생성 중 오류가 발생했어요") from exc


@router.get("/checkout/{checkout_token}", response_class=HTMLResponse)
def checkout(checkout_token: str):
    repo, settings = JoinRepository(), get_settings()
    if not settings.kiwoompay_cpid:
        raise _error(503, "KIWOOMPAY_NOT_CONFIGURED", "키움페이 가맹점 ID가 설정되지 않았어요")
    try:
        rows = repo.client.rest_get("payment_orders", {
            "select": ORDER_SELECT, "checkout_token": f"eq.{checkout_token}",
            "status": "eq.ready", "limit": "1",
        })
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "결제 주문을 불러오지 못했어요") from exc
    if not rows:
        raise _error(404, "ORDER_NOT_FOUND", "결제할 주문이 없거나 이미 처리됐어요")
    order = rows[0]
    _ensure_voucher_order_available(repo, order)
    pay_method = str(order.get("requested_payment_method") or "TOTAL")
    if pay_method not in {"TOTAL", "BANK"}:
        raise _error(409, "INVALID_PAYMENT_METHOD", "주문 결제수단 설정이 올바르지 않아요")
    try:
        secure_hash = request_payment_hash(settings.kiwoompay_base_url, KiwoomHashInput(
            cpid=settings.kiwoompay_cpid, order_id=order["order_id"], amount=int(order["amount"]),
            pay_method=pay_method,
        ))
    except KiwoomPaymentError as exc:
        raise _error(exc.status if 400 <= exc.status < 500 else 502, exc.code, exc.message) from exc

    order_id = _safe_text(order["order_id"], 50)
    amount = str(int(order["amount"]))
    success_url = f"{settings.public_api_base_url}/payments/redirect/success?orderId={order_id}&amount={amount}"
    fail_url = f"{settings.public_api_base_url}/payments/redirect/fail?orderId={order_id}"
    close_url = f"{settings.public_api_base_url}/payments/redirect/close?orderId={order_id}"
    fields = {
        "PAYMETHOD": pay_method, "TYPE": "W", "CPID": settings.kiwoompay_cpid,
        "ORDERNO": order_id, "PRODUCTTYPE": "2", "AMOUNT": amount,
        "PRODUCTNAME": _safe_text(order["product_name"], 50),
        "PRODUCTCODE": _safe_text(order.get("product_id") or order.get("voucher_product_id") or "GE", 10),
        "USERID": _safe_text(order["user_id"], 30), "KIWOOM_ENC": secure_hash,
        "RETURNURL": success_url, "HOMEURL": success_url,
        "FAILURL": fail_url, "CLOSEURL": close_url,
        "APPURL": settings.kiwoompay_app_url, "DIRECTRESULTFLAG": "Y",
    }
    hidden = "".join(
        f'<input type="hidden" name="{escape(key)}" value="{escape(str(value), quote=True)}">'
        for key, value in fields.items()
    )
    action = escape(f"{settings.kiwoompay_base_url}/pay/linkEnc", quote=True)
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<style>html,body{{margin:0;background:#fff}}form{{display:none}}</style></head>
<body><form id="payment" method="post" action="{action}" accept-charset="EUC-KR">{hidden}</form>
<script type="text/javascript" charset="EUC-KR">document.charset='EUC-KR';document.getElementById('payment').submit();</script></body></html>""")


def _decode_form(raw: bytes) -> dict[str, str]:
    for encoding in ("utf-8", "euc-kr", "cp949"):
        try:
            parsed = parse_qs(raw.decode(encoding), keep_blank_values=True)
            return {key: values[-1] for key, values in parsed.items()}
        except UnicodeDecodeError:
            pass
    return {}


def _notification_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "")


def _ack(success: bool, status_code: int = 200) -> Response:
    result = "SUCCESS" if success else "FAIL"
    return Response(f"<html><body><RESULT>{result}</RESULT></body></html>", status_code=status_code, media_type="text/html")


async def _notification(request: Request) -> Response:
    settings, repo = get_settings(), JoinRepository()
    source_ip = _notification_ip(request)
    if source_ip not in {"127.0.0.1", "::1", "testclient"} and source_ip not in settings.kiwoompay_notification_ips:
        return _ack(False, 403)
    values = dict(request.query_params)
    if request.method == "POST":
        values.update(_decode_form(await request.body()))
    try:
        if values.get("CPID") != settings.kiwoompay_cpid:
            return _ack(False, 400)
        pay_method = str(values.get("PAYMETHOD") or "")
        if pay_method.endswith("CANCEL") or pay_method == "CARD_CANCEL":
            return _ack(True)
        order_id, transaction_id = values.get("ORDERNO"), values.get("DAOUTRX")
        if not order_id or not transaction_id:
            return _ack(False, 400)
        rows = repo.client.rest_get("payment_orders", {
            "select": ORDER_SELECT, "order_id": f"eq.{order_id}", "limit": "1",
        })
        if not rows:
            return _ack(False, 404)
        order = rows[0]
        if int(values.get("AMOUNT") or 0) != int(order["amount"]):
            return _ack(False, 409)
        requested_method = str(order.get("requested_payment_method") or "TOTAL")
        if requested_method == "BANK" and pay_method != "BANK":
            return _ack(False, 409)
        if order.get("status") == "done":
            return _ack(order.get("provider_payment_key") == transaction_id, 200 if order.get("provider_payment_key") == transaction_id else 409)
        approved_at = datetime.now(timezone.utc).isoformat()
        provider_response = {**values, "source_ip": source_ip}
        if order.get("pay_type") in {"voucher", "subsidized"}:
            repo.client.rpc("fulfill_voucher_order" if order.get("pay_type") == "voucher" else "fulfill_subsidized_order", {
                "p_order_id": order["id"], "p_provider_payment_key": transaction_id,
                "p_payment_method": pay_method, "p_provider_response": provider_response,
                "p_approved_at": approved_at,
            })
        else:
            updated = repo.client.rest_patch("payment_orders", {
                "id": f"eq.{order['id']}", "status": "eq.ready",
            }, {
                "status": "done", "provider_payment_key": transaction_id,
                "payment_method": pay_method, "provider_response": provider_response,
                "approved_at": approved_at, "updated_at": approved_at,
            })
            if not updated:
                return _ack(False, 409)
        return _ack(True)
    except (SupabaseHttpError, ValueError, TypeError):
        return _ack(False, 500)


@router.get("/notification")
async def notification_get(request: Request):
    return await _notification(request)


@router.post("/notification")
async def notification_post(request: Request):
    return await _notification(request)


@router.post("/confirm")
def confirm(payload: PaymentConfirmRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, profile = _customer(repo, token, allow_employee=True)
        rows = repo.client.rest_get("payment_orders", {
            "select": ORDER_SELECT, "order_id": f"eq.{payload.order_id}",
            "user_id": f"eq.{profile.id}", "limit": "1",
        })
        if not rows:
            raise _error(404, "ORDER_NOT_FOUND", "결제 주문을 찾을 수 없어요")
        order = rows[0]
        if int(order["amount"]) != payload.amount:
            raise _error(400, "AMOUNT_MISMATCH", "결제 금액이 주문 금액과 일치하지 않아요")
        if order.get("status") != "done":
            for _ in range(8):
                time.sleep(1)
                refreshed = repo.client.rest_get("payment_orders", {
                    "select": ORDER_SELECT, "order_id": f"eq.{payload.order_id}",
                    "user_id": f"eq.{profile.id}", "limit": "1",
                })
                if refreshed and refreshed[0].get("status") == "done":
                    order = refreshed[0]
                    break
        if order.get("status") != "done":
            raise _error(409, "PAYMENT_PENDING", "결제 승인 확인 중이에요. 잠시 후 다시 확인해 주세요")
        return {"ok": True, "data": order, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "결제 승인 결과를 확인하지 못했어요") from exc


@router.get("/redirect/success", response_class=HTMLResponse)
def redirect_success():
    return HTMLResponse("<h1>결제 승인 확인 중입니다. 앱으로 돌아가 주세요.</h1>")


@router.get("/redirect/fail", response_class=HTMLResponse)
def redirect_fail():
    return HTMLResponse("<h1>결제에 실패했어요. 앱으로 돌아가 다시 시도해 주세요.</h1>")


@router.get("/redirect/close", response_class=HTMLResponse)
def redirect_close():
    return HTMLResponse("<h1>결제가 취소되었어요. 앱으로 돌아가 주세요.</h1>")
