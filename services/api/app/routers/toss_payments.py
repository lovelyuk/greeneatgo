from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timezone
from html import escape

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.auth import bearer_token
from app.config import get_settings
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.schemas import TossOrderCreateRequest, TossPaymentConfirmRequest
from app.services.toss_payment import TossConfirmInput, TossPaymentError, confirm_payment, get_payment, validate_confirm_input

router = APIRouter(prefix="/toss", tags=["toss-payments"])

ORDER_SELECT = (
    "id,order_id,checkout_token,user_id,merchant_id,product_id,merchant_name,"
    "product_name,amount,status,payment_key,payment_method,approved_at,created_at,"
    "pay_type,voucher_product_id,voucher_count,voucher_purchase_price,fulfilled_at,toss_response"
)


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _json_for_script(value: object) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _customer(repo: JoinRepository, token: str):
    auth = repo.auth_user_from_token(token)
    profile = repo.get_profile(auth.id, email=auth.email)
    if profile is None or profile.status != "active" or profile.role != "customer":
        raise _error(403, "CUSTOMER_ONLY", "일반 사용자만 토스페이먼츠로 결제할 수 있어요")
    return auth, profile


@router.post("/orders")
def create_order(payload: TossOrderCreateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    settings = get_settings()
    try:
        auth, profile = _customer(repo, token)
        merchants = repo.client.rest_get(
            "merchants",
            {"select": "id,name", "qr_token": f"eq.{payload.qr_token}", "status": "eq.active", "limit": "1"},
        )
        if not merchants:
            raise _error(404, "MERCHANT_NOT_FOUND", "식당을 찾을 수 없어요")
        merchant = merchants[0]
        products = repo.client.rest_get(
            "merchant_products",
            {
                "select": "id,name,price,merchant_id,is_active",
                "id": f"eq.{payload.product_id}",
                "merchant_id": f"eq.{merchant['id']}",
                "is_active": "eq.true",
                "limit": "1",
            },
        )
        if not products:
            raise _error(404, "PRODUCT_NOT_FOUND", "판매 중인 상품을 찾을 수 없어요")
        product = products[0]
        order_id = f"GE-{uuid.uuid4().hex}"
        checkout_token = secrets.token_urlsafe(32)
        rows = repo.client.rest_post("toss_payment_orders", {
            "order_id": order_id,
            "checkout_token": checkout_token,
            "user_id": profile.id,
            "merchant_id": merchant["id"],
            "product_id": product["id"],
            "merchant_name": merchant["name"],
            "product_name": product["name"],
            "amount": int(product["price"]),
            "status": "ready",
            "pay_type": "direct",
        })
        order = rows[0]
        return {
            "ok": True,
            "data": {
                "order_id": order_id,
                "amount": order["amount"],
                "product_name": order["product_name"],
                "merchant_name": order["merchant_name"],
                "checkout_url": f"{settings.public_api_base_url}/toss/checkout/{checkout_token}",
            },
            "error": None,
        }
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        if "toss_payment_orders" in exc.body or "PGRST205" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0014_toss_consumer_payments.sql 적용이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "결제 주문 생성 중 오류가 발생했어요") from exc


@router.get("/checkout/{checkout_token}", response_class=HTMLResponse)
def checkout(checkout_token: str):
    repo = JoinRepository()
    settings = get_settings()
    try:
        rows = repo.client.rest_get(
            "toss_payment_orders",
            {"select": ORDER_SELECT, "checkout_token": f"eq.{checkout_token}", "status": "eq.ready", "limit": "1"},
        )
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "결제 주문을 불러오지 못했어요") from exc
    if not rows:
        raise _error(404, "ORDER_NOT_FOUND", "결제할 주문이 없거나 이미 처리됐어요")
    order = rows[0]
    success_url = f"{settings.public_api_base_url}/toss/redirect/success"
    fail_url = f"{settings.public_api_base_url}/toss/redirect/fail"
    client_key = _json_for_script(settings.toss_client_key)
    customer_key = _json_for_script(f"customer-{order['user_id']}")
    amount = int(order["amount"])
    order_id = _json_for_script(order["order_id"])
    order_name = _json_for_script(order["product_name"])
    success = _json_for_script(success_url)
    fail = _json_for_script(fail_url)
    merchant_name = escape(str(order["merchant_name"]))
    product_name = escape(str(order["product_name"]))
    auto_start = "true" if order.get("pay_type") == "voucher" else "false"
    return HTMLResponse(f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>그린잇 상품 결제</title><script src="https://js.tosspayments.com/v2/standard"></script>
<style>body{{margin:0;background:#f3fbf4;color:#14351f;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}main{{max-width:560px;margin:auto;padding:18px 14px 40px}}.summary{{background:white;border:1px solid #cdebd5;border-radius:22px;padding:18px;margin-bottom:14px}}h1{{font-size:22px;margin:0 0 6px}}p{{margin:5px 0;color:#5c7a66}}strong{{font-size:24px;color:#15a05a}}button{{width:100%;border:0;border-radius:16px;padding:17px;background:#2fb865;color:white;font-size:17px;font-weight:800;margin-top:20px}}button:disabled{{opacity:.5}}#error{{display:none;color:#b42318;background:#feeceb;border-radius:12px;padding:12px;margin-top:12px}}</style></head>
<body><main><section class="summary"><h1>{merchant_name}</h1><p>{product_name}</p><strong>{amount:,}원</strong></section><div id="payment-method"></div><div id="agreement"></div><div id="error"></div><button id="pay" disabled>결제하기</button></main>
<script>
(async()=>{{
 const button=document.getElementById('pay'), error=document.getElementById('error'), autoStart={auto_start};
 try {{
  const tossPayments=TossPayments({client_key});
  const isWidgetKey=String({client_key}).includes('_gck_');
  if(isWidgetKey) {{
   const widgets=tossPayments.widgets({{customerKey:{customer_key}}});
   await widgets.setAmount({{currency:'KRW',value:{amount}}});
   await Promise.all([widgets.renderPaymentMethods({{selector:'#payment-method',variantKey:'DEFAULT'}}),widgets.renderAgreement({{selector:'#agreement',variantKey:'AGREEMENT'}})]);
   button.disabled=false;
   button.addEventListener('click',async()=>{{button.disabled=true;try{{await widgets.requestPayment({{orderId:{order_id},orderName:{order_name},successUrl:{success},failUrl:{fail}}});}}catch(e){{error.style.display='block';error.textContent=e.message||'결제창을 열지 못했어요';button.disabled=false;}}}});
  }} else {{
   document.getElementById('payment-method').innerHTML='<section class="summary"><b>카드·간편결제</b><p>토스페이먼츠 결제창에서 결제수단을 선택합니다.</p></section>';
   const payment=tossPayments.payment({{customerKey:{customer_key}}});
   const startPayment=async()=>{{button.disabled=true;try{{await payment.requestPayment({{method:'CARD',amount:{{currency:'KRW',value:{amount}}},orderId:{order_id},orderName:{order_name},successUrl:{success},failUrl:{fail}}});}}catch(e){{error.style.display='block';error.textContent=e.message||'결제창을 열지 못했어요';button.style.display='block';button.disabled=false;}}}};
   button.addEventListener('click',startPayment);
   if(autoStart){{button.style.display='none';await startPayment();}}else{{button.disabled=false;}}
  }}
 }} catch(e) {{error.style.display='block';error.textContent=e.message||'결제화면을 불러오지 못했어요';}}
}})();
</script></body></html>""")


@router.post("/confirm")
def confirm(payload: TossPaymentConfirmRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    settings = get_settings()
    try:
        _, profile = _customer(repo, token)
        rows = repo.client.rest_get(
            "toss_payment_orders",
            {"select": ORDER_SELECT, "order_id": f"eq.{payload.order_id}", "user_id": f"eq.{profile.id}", "limit": "1"},
        )
        if not rows:
            raise _error(404, "ORDER_NOT_FOUND", "결제 주문을 찾을 수 없어요")
        order = rows[0]
        confirm_input = TossConfirmInput(payload.payment_key, payload.order_id, payload.amount)
        validate_confirm_input(
            expected_order_id=order["order_id"],
            expected_amount=int(order["amount"]),
            payload=confirm_input,
        )
        if order["status"] == "done":
            if order.get("payment_key") != payload.payment_key:
                raise TossPaymentError(409, "PAYMENT_KEY_MISMATCH", "이미 다른 결제키로 승인된 주문이에요")
            payment = order.get("toss_response") or {
                "status": "DONE", "paymentKey": order.get("payment_key"),
                "method": order.get("payment_method"), "approvedAt": order.get("approved_at"),
            }
        else:
            payment = confirm_payment(settings.toss_secret_key, confirm_input)
            if payment.get("status") != "DONE":
                raise TossPaymentError(400, "PAYMENT_NOT_DONE", "즉시 승인된 결제만 식당 이용이 가능해요")
        approved_at = payment.get("approvedAt") or order.get("approved_at") or datetime.now(timezone.utc).isoformat()
        if order.get("pay_type") == "voucher":
            fulfillment = repo.client.rpc("fulfill_voucher_order", {
                "p_order_id": order["id"],
                "p_payment_key": payment.get("paymentKey") or payload.payment_key,
                "p_payment_method": payment.get("method"),
                "p_toss_response": payment,
                "p_approved_at": approved_at,
            })
            return {"ok": True, "data": {**order, **fulfillment, "fulfillment": fulfillment}, "error": None}
        if order["status"] == "done":
            return {"ok": True, "data": order, "error": None}
        updated = repo.client.rest_patch(
            "toss_payment_orders",
            {"id": f"eq.{order['id']}"},
            {
                "status": "done",
                "payment_key": payment.get("paymentKey"),
                "payment_method": payment.get("method"),
                "toss_response": payment,
                "approved_at": approved_at,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )[0]
        return {"ok": True, "data": updated, "error": None}
    except HTTPException:
        raise
    except TossPaymentError as exc:
        try:
            repo.client.rest_patch(
                "toss_payment_orders",
                {"order_id": f"eq.{payload.order_id}", "status": "eq.ready"},
                {"failure_code": exc.code, "failure_message": exc.message, "updated_at": datetime.now(timezone.utc).isoformat()},
            )
        except SupabaseHttpError:
            pass
        raise _error(exc.status if 400 <= exc.status < 500 else 502, exc.code, exc.message) from exc
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "결제 승인 결과 저장 중 오류가 발생했어요") from exc


@router.get("/redirect/success", response_class=HTMLResponse)
def redirect_success():
    return HTMLResponse("<h1>앱으로 돌아가 결제를 완료해 주세요.</h1>")


@router.get("/redirect/fail", response_class=HTMLResponse)
def redirect_fail():
    return HTMLResponse("<h1>결제가 취소되었어요. 앱으로 돌아가 다시 시도해 주세요.</h1>")


@router.post("/webhook")
def webhook(payload: dict = Body(...)):
    """Recovery only: authorization still happens through server-side /confirm."""
    repo = JoinRepository()
    settings = get_settings()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    payment_key = data.get("paymentKey") if isinstance(data, dict) else None
    if not payment_key or not isinstance(payment_key, str):
        return {"ok": True, "data": {"ignored": True}, "error": None}
    try:
        payment = get_payment(settings.toss_secret_key, payment_key)
        # The body is never used as payment truth; all fields below came from authenticated Toss GET.
        if payment.get("status") != "DONE":
            return {"ok": True, "data": {"ignored": True, "status": payment.get("status")}, "error": None}
        order_id = payment.get("orderId")
        amount = payment.get("totalAmount") if payment.get("totalAmount") is not None else payment.get("balanceAmount")
        rows = repo.client.rest_get("toss_payment_orders", {"select": ORDER_SELECT, "order_id": f"eq.{order_id}", "limit": "1"})
        if not rows:
            raise _error(404, "ORDER_NOT_FOUND", "복구할 주문을 찾을 수 없어요")
        order = rows[0]
        validate_confirm_input(expected_order_id=order["order_id"], expected_amount=int(order["amount"]), payload=TossConfirmInput(payment_key, str(order_id), int(amount or 0)))
        if payment.get("paymentKey") != payment_key:
            raise _error(400, "PAYMENT_KEY_MISMATCH", "결제키가 일치하지 않아요")
        approved_at = payment.get("approvedAt") or datetime.now(timezone.utc).isoformat()
        if order.get("pay_type") == "voucher":
            fulfillment = repo.client.rpc("fulfill_voucher_order", {
                "p_order_id": order["id"], "p_payment_key": payment_key,
                "p_payment_method": payment.get("method"), "p_toss_response": payment,
                "p_approved_at": approved_at,
            })
            return {"ok": True, "data": {"recovered": True, "fulfillment": fulfillment}, "error": None}
        if order.get("status") != "done":
            repo.client.rest_patch("toss_payment_orders", {"id": f"eq.{order['id']}", "status": "eq.ready"}, {
                "status": "done", "payment_key": payment_key, "payment_method": payment.get("method"),
                "toss_response": payment, "approved_at": approved_at, "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        return {"ok": True, "data": {"recovered": True}, "error": None}
    except HTTPException:
        raise
    except TossPaymentError as exc:
        raise _error(exc.status if 400 <= exc.status < 500 else 502, exc.code, exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "웹훅 복구 처리 중 오류가 발생했어요") from exc
