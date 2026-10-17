from __future__ import annotations

import ipaddress
import json
import logging
import time
from html import escape
from typing import Annotated, Literal
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from app.services.local_abandonment import LOCAL_SELECT, OPERATOR_SELECT, local_recovery
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.auth import bearer_token
from app.config import get_settings
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.voucher_products import _expire_stale_subsidized_orders, _is_exposed, _load_products
from app.schemas import PaymentConfirmRequest
from app.services.kiwoom_payment import KiwoomHashInput, KiwoomPaymentError, request_payment_hash
from app.services.payment_completion import present_payment_completion

router = APIRouter(prefix="/payments", tags=["payments"])
short_redirect_router = APIRouter(include_in_schema=False)
logger = logging.getLogger(__name__)

# Existing Kiwoom API/result handling consistently defines 0000 as success.
# Deployed result notifications may omit RESULTCODE, so absence remains
# compatible while an explicit non-success value can never approve an order.
KIWOOM_NOTIFICATION_SUCCESS_CODES = frozenset({"0000"})
KIWOOM_NOTIFICATION_STORED_FIELDS = frozenset({
    "CPID",
    "PAYMETHOD",
    "DAOUTRX",
    "ORDERNO",
    "AMOUNT",
    "SETTDATE",
    "CANCELDATE",
    "PAYMENTTYPE",
    "RESULTCODE",
    "AUTHNO",
    "ALLOTMON",
    "NOINTFLAG",
    "CARDCODE",
    "CARDNAME",
    "CARDNO",
    "BANKNAME",
    "CASHRECAUTHNO",
})

ORDER_SELECT = (
    "id,order_id,checkout_token,user_id,merchant_id,product_id,merchant_name,"
    "product_name,amount,status,provider_payment_key,payment_method,approved_at,created_at,"
    "pay_type,voucher_product_id,voucher_count,voucher_purchase_price,fulfilled_at,provider_response,"
    "company_id,company_subsidy_amount,restaurant_subsidy_amount,point_amount,point_reserved,"
    "requested_payment_method,paid_voucher_count,bonus_voucher_count,total_employee_burden,checkout_started_at,tax_type,tax_review_required,"
    "gross_amount,coupon_id,coupon_discount_amount,coupon_snapshot,requested_point_amount"
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


def _require_order_tax_classified(order: dict) -> None:
    """Block every provider-backed order unless its immutable tax snapshot is classified."""
    if order.get("tax_type") not in {"taxable", "tax_free"}:
        raise _error(409, "TAX_TYPE_UNCLASSIFIED", "과세 유형이 설정되지 않은 주문은 결제할 수 없어요")


def _ensure_voucher_order_available(repo: JoinRepository, order: dict) -> None:
    if order.get("pay_type") not in {"voucher", "subsidized"}:
        return
    product_id, merchant_id = order.get("voucher_product_id"), order.get("merchant_id")
    legacy_subsidized = (
        order.get("pay_type") == "subsidized"
        and product_id is None
        and int(order.get("voucher_count") or 0) == 1
        and int(order.get("paid_voucher_count") or 0) == 1
        and int(order.get("bonus_voucher_count") or 0) == 0
    )
    if legacy_subsidized:
        # Orders created before migration 0032 had no voucher product. Their
        # one-paid/no-bonus snapshot is the compatibility marker; do not weaken
        # product availability checks for any package-shaped order.
        return
    if not product_id or not merchant_id:
        raise _error(409, "INVALID_VOUCHER_ORDER", "식권 상품 정보가 없는 주문이에요")
    products, _ = _load_products(repo, {
        "id": f"eq.{product_id}", "merchant_id": f"eq.{merchant_id}",
        "status": "eq.active", "limit": "1",
    })
    if not products or not _is_exposed(products[0]):
        raise _error(409, "VOUCHER_PRODUCT_NOT_EXPOSED", "이벤트가 종료되었거나 판매가 중지된 상품이에요")


def _enforce_subsidized_order_expiry(repo: JoinRepository, order: dict) -> dict:
    """Let PostgreSQL expire ready subsidized orders, then return fresh state.

    The RPC uses database ``now()`` and the inclusive 30-minute boundary. It is
    called for every ready subsidized order rather than trusting a client time or
    risking clock skew between API and database.
    """
    if order.get("pay_type") != "subsidized" or order.get("status") != "ready":
        return order
    _expire_stale_subsidized_orders(repo, str(order["user_id"]))
    rows = repo.client.rest_get("payment_orders", {
        "select": ORDER_SELECT, "id": f"eq.{order['id']}", "limit": "1",
    })
    if not rows:
        raise _error(404, "ORDER_NOT_FOUND", "결제 주문을 찾을 수 없어요")
    refreshed = rows[0]
    if refreshed.get("status") == "canceled":
        raise _error(409, "ORDER_EXPIRED", "결제 가능 시간이 만료된 주문이에요")
    if refreshed.get("status") != "ready":
        raise _error(409, "ORDER_NOT_READY", "이미 처리되었거나 결제할 수 없는 주문이에요")
    return refreshed


def _safe_text(value: object, limit: int) -> str:
    return str(value or "").replace("|", " ")[:limit]



def _checkout_return_urls(settings, return_nonce: str | None) -> tuple[str, str, str]:
    """Correlation only: configured merchant origin, no token or financial data."""
    if return_nonce is None:
        base = urlsplit(settings.public_api_base_url)
        origin = f"{base.scheme}://{base.netloc}"
        return f"{origin}/p", f"{origin}/f", f"{origin}/c"
    try:
        base = urlsplit(settings.admin_app_url)
        if (base.scheme not in {'https', 'http'} or not base.hostname
                or base.username is not None or base.password is not None
                or base.query or base.fragment or base.path not in {'', '/'}
                or any(ord(c) < 33 or ord(c) > 126 for c in settings.admin_app_url)
                or '\\' in settings.admin_app_url):
            raise ValueError('invalid merchant origin')
        # Access port to reject malformed configured ports before admission.
        base.port
        origin = f"{base.scheme}://{base.netloc}"
        urls = tuple(f"{origin}/payment-return#{kind}.{return_nonce}"
                     for kind in ('success', 'fail', 'cancel'))
        if any(len(url) > 100 for url in urls):
            raise ValueError('provider return URL too long')
        return urls[0], urls[1], urls[2]
    except (ValueError, AttributeError):
        raise _error(503, 'CHECKOUT_RETURN_NOT_CONFIGURED', '결제창 복귀 설정이 올바르지 않아요') from None


@router.get("/checkout/{checkout_token}", response_class=HTMLResponse)
def checkout(checkout_token: str, return_nonce: Annotated[str | None, Query(pattern=r'^[0-9a-f]{32}$', min_length=32, max_length=32)] = None):
    repo, settings = JoinRepository(), get_settings()
    success_url, fail_url, close_url = _checkout_return_urls(settings, return_nonce)
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
    order = _enforce_subsidized_order_expiry(repo, rows[0])
    _require_order_tax_classified(order)
    _ensure_voucher_order_available(repo, order)
    pay_method = str(order.get("requested_payment_method") or "TOTAL")
    if pay_method not in {"TOTAL", "BANK"}:
        raise _error(409, "INVALID_PAYMENT_METHOD", "주문 결제수단 설정이 올바르지 않아요")
    try:
        # The committed row-lock admission fences finalization and repeat entry
        # for direct, voucher and subsidized orders before contacting the PG.
        repo.client.rpc('admit_payment_checkout', {'p_order_id': order['id']})
    except SupabaseHttpError as exc:
        raise _error(409, 'ORDER_NOT_READY', '이미 처리되었거나 결제할 수 없는 주문이에요') from exc
    try:
        secure_hash = request_payment_hash(settings.kiwoompay_base_url, KiwoomHashInput(
            cpid=settings.kiwoompay_cpid, order_id=order["order_id"], amount=int(order["amount"]),
            pay_method=pay_method,
        ))
    except KiwoomPaymentError as exc:
        raise _error(exc.status if 400 <= exc.status < 500 else 502, exc.code, exc.message) from exc

    try:
        repo.client.rpc('assert_payment_checkout_active', {'p_order_id': order['id']})
    except SupabaseHttpError as exc:
        raise _error(409, 'ORDER_NOT_READY', '이미 처리되었거나 결제할 수 없는 주문이에요') from exc
    order_id = _safe_text(order["order_id"], 50)
    amount = str(int(order["amount"]))
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


@router.post("/checkout/{checkout_token}/sdk")
def checkout_sdk(checkout_token: str, token: str = Depends(bearer_token),
                 return_nonce: Annotated[str | None, Query(pattern=r'^[0-9a-f]{32}$', min_length=32, max_length=32)] = None):
    """Issue one owner-bound PC TOTAL payload, never a BANK-to-TOTAL fallback."""
    repo, settings = JoinRepository(), get_settings()
    success_url, fail_url, close_url = _checkout_return_urls(settings, return_nonce)
    try:
        _, profile = _customer(repo, token, allow_employee=True)
        rows = repo.client.rest_get("payment_orders", {
            "select": ORDER_SELECT, "checkout_token": f"eq.{checkout_token}",
            "user_id": f"eq.{profile.id}", "status": "eq.ready", "limit": "1",
        })
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인 정보가 올바르지 않아요") from exc
        raise _error(502, "SUPABASE_ERROR", "결제 주문을 불러오지 못했어요") from exc
    if not rows:
        raise _error(404, "ORDER_NOT_FOUND", "결제할 주문이 없거나 이미 처리됐어요")
    order = rows[0]
    pay_method = str(order.get("requested_payment_method") or "TOTAL")
    if pay_method == "BANK":
        raise _error(409, "SDK_PAYMENT_METHOD_UNSUPPORTED", "계좌이체 전용 주문은 기존 결제창을 이용해 주세요")
    if pay_method != "TOTAL":
        raise _error(409, "INVALID_PAYMENT_METHOD", "주문 결제수단 설정이 올바르지 않아요")

    # Exact API origins only: no normalization, suffix matching, or DEV default.
    sdk_mode = {
        "https://api.kiwoompay.co.kr": "REAL",
        "https://apitest.kiwoompay.co.kr": "DEV",
    }.get(settings.kiwoompay_base_url)
    cpid = settings.kiwoompay_cpid
    if not sdk_mode or not isinstance(cpid, str) or len(cpid) != 8 or not cpid.isascii() or not cpid.isalnum():
        raise _error(503, "KIWOOMPAY_SDK_NOT_CONFIGURED", "PC 결제창 설정이 올바르지 않아요")

    def valid_text(value: object, limit: int) -> bool:
        return (isinstance(value, str) and bool(value.strip()) and len(value) <= limit
                and "|" not in value and all(ord(char) >= 32 and ord(char) != 127 for char in value))

    try:
        order = _enforce_subsidized_order_expiry(repo, order)
        _require_order_tax_classified(order)
        _ensure_voucher_order_available(repo, order)
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "결제 주문을 확인하지 못했어요") from exc
    raw_amount = order.get("amount")
    if (isinstance(raw_amount, bool) or not isinstance(raw_amount, (int, str))
            or not 1 <= len(str(raw_amount)) <= 10
            or not str(raw_amount).isascii() or not str(raw_amount).isdigit()
            or not 0 < int(raw_amount) <= 9999999999):
        raise _error(409, "INVALID_SDK_CHECKOUT", "결제 주문 정보가 올바르지 않아요")
    amount = int(raw_amount)
    # ORDERNO must be identical in hash and form; never truncate or sanitize it.
    order_id = order.get("order_id")
    product_name = _safe_text(order.get("product_name"), 50)
    user_id = _safe_text(order.get("user_id"), 30)
    if not valid_text(order_id, 50) or not valid_text(product_name, 50) or not valid_text(user_id, 30):
        raise _error(409, "INVALID_SDK_CHECKOUT", "결제 주문 정보가 올바르지 않아요")
    public_base = urlsplit(settings.public_api_base_url)
    fields = {
        "PAYMETHOD": "TOTAL", "TYPE": "P", "CPID": cpid,
        "ORDERNO": order_id, "PRODUCTTYPE": "2", "AMOUNT": str(amount),
        "PRODUCTNAME": product_name,
        "PRODUCTCODE": _safe_text(order.get("product_id") or order.get("voucher_product_id") or "GE", 10),
        "USERID": user_id, "RETURNURL": success_url, "HOMEURL": success_url,
        "FAILURL": fail_url, "CLOSEURL": close_url,
        "APPURL": settings.kiwoompay_app_url, "DIRECTRESULTFLAG": "Y",
    }
    if (public_base.scheme not in {"http", "https"} or not public_base.netloc
            or public_base.username or public_base.password
            or any(not valid_text(fields[key], 100) for key in ("RETURNURL", "HOMEURL", "FAILURL", "CLOSEURL"))
            or not isinstance(fields["APPURL"], str) or len(fields["APPURL"]) > 100
            or (fields["APPURL"] and not valid_text(fields["APPURL"], 100))):
        raise _error(503, "KIWOOMPAY_SDK_NOT_CONFIGURED", "PC 결제창 설정이 올바르지 않아요")
    try:
        # Same 0064 row-lock, committed single-entry boundary as native GET.
        repo.client.rpc("admit_payment_checkout", {"p_order_id": order["id"]})
    except SupabaseHttpError as exc:
        raise _error(409, "ORDER_NOT_READY", "이미 처리되었거나 결제할 수 없는 주문이에요") from exc
    try:
        secure_hash = request_payment_hash(settings.kiwoompay_base_url, KiwoomHashInput(
            cpid=cpid, order_id=order_id, amount=amount, payment_type="P", pay_method="TOTAL",
        ), strict_response=True)
    except KiwoomPaymentError as exc:
        # Provider messages/codes can contain raw data; expose only a fixed error.
        raise _error(502, "KIWOOMPAY_HASH_FAILED", "키움페이 결제 보안값을 발급하지 못했어요") from exc
    if not valid_text(secure_hash, 1000) or any(char.isspace() for char in secure_hash):
        raise _error(502, "KIWOOMPAY_INVALID_RESPONSE", "키움페이 응답 형식이 올바르지 않아요")
    try:
        repo.client.rpc("assert_payment_checkout_active", {"p_order_id": order["id"]})
    except SupabaseHttpError as exc:
        raise _error(409, "ORDER_NOT_READY", "이미 처리되었거나 결제할 수 없는 주문이에요") from exc
    fields["KIWOOM_ENC"] = secure_hash
    return JSONResponse({"ok": True, "data": {"sdk_mode": sdk_mode, "fields": fields}, "error": None},
                        headers={"Cache-Control": "no-store"})


def _decode_form(raw: bytes) -> dict[str, str]:
    # Kiwoom's notification contract is EUC-KR. Prefer its Windows superset
    # before UTF-8 so byte sequences valid in both encodings keep their Korean
    # meaning instead of silently becoming an unrelated Unicode character.
    for encoding in ("cp949", "euc-kr", "utf-8"):
        try:
            payload = raw.decode("ascii") if raw.isascii() else raw.decode(encoding)
            parsed = parse_qs(
                payload,
                keep_blank_values=True,
                encoding=encoding,
                errors="strict",
            )
            return {key: values[-1] for key, values in parsed.items()}
        except UnicodeDecodeError:
            pass
    return {}


TRUSTED_LOCAL_PEERS = frozenset({"127.0.0.1", "::1", "testclient"})


def _notification_ip(request: Request) -> str:
    # Vercel ingress delivers the real caller as the socket peer (verified:
    # forged X-Forwarded-For/X-Real-IP/X-Vercel-Forwarded-For are overwritten), so
    # request.client.host is the authoritative, unspoofable source (the access
    # log shows the true Kiwoom IP there). X-Forwarded-For instead trails an
    # internal proxy hop (e.g. a 10.x address) that must never be mistaken for
    # the caller. Only when the peer is a loopback/test sentinel do we honour the
    # forwarded chain, since those legitimately front a real caller (and inject a
    # simulated source IP in tests). A direct attacker therefore cannot smuggle an
    # allowed IP through a forged X-Forwarded-For header.
    peer = request.client.host if request.client else ""
    if peer in TRUSTED_LOCAL_PEERS:
        forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
        if forwarded:
            return str(ipaddress.ip_address(forwarded[-1]))
        return peer
    return str(ipaddress.ip_address(peer))


def _ack(success: bool, status_code: int = 200) -> Response:
    result = "SUCCESS" if success else "FAIL"
    return Response(f"<html><body><RESULT>{result}</RESULT></body></html>", status_code=status_code, media_type="text/html")


def _log_notification_outcome(event: str, reason: str, *, level: int = logging.WARNING) -> None:
    """Log a callback outcome without attaching provider or request data."""
    logger.log(level, "%s reason=%s", event, reason, extra={"reason": reason})


def _is_successful_notification_outcome(values: dict[str, str]) -> bool:
    """Return whether a callback can represent an approval."""
    pay_method = str(values.get("PAYMETHOD") or "").strip().upper()
    if pay_method.endswith("CANCEL") or pay_method == "CARD_CANCEL":
        return False
    if "RESULTCODE" not in values:
        return True
    return str(values["RESULTCODE"]).strip() in KIWOOM_NOTIFICATION_SUCCESS_CODES


def _masked_card_number_for_storage(value: object) -> str | None:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if len(digits) < 4:
        return None
    return f"****-****-****-{digits[-4:]}"


def _normalized_notification_payload(values: dict[str, str], source_ip: str) -> dict[str, str]:
    """Persist only fields required for reconciliation and receipt presentation.

    Kiwoom sends callback data in a GET query and can include a full card PAN plus
    customer identifiers. Those values are not needed to fulfill an order and
    must never enter the durable inbox or payment-order provider snapshot.
    """
    normalized: dict[str, str] = {"source_ip": source_ip}
    for key in KIWOOM_NOTIFICATION_STORED_FIELDS:
        if key not in values:
            continue
        value = str(values[key] or "").strip()
        if key == "CARDNO":
            masked = _masked_card_number_for_storage(value)
            if masked:
                normalized[key] = masked
        elif value:
            normalized[key] = value[:200]
    return normalized


async def _notification(request: Request) -> Response:
    settings, repo = get_settings(), JoinRepository()
    try:
        source_ip = _notification_ip(request)
    except ValueError:
        _log_notification_outcome("kiwoom_notification_rejected", "invalid_source_ip")
        return _ack(False, 400)
    if source_ip not in TRUSTED_LOCAL_PEERS and source_ip not in settings.kiwoompay_notification_ips:
        _log_notification_outcome("kiwoom_notification_rejected", "source_ip_not_allowed")
        return _ack(False, 403)
    values = dict(request.query_params)
    if request.method == "POST":
        values.update(_decode_form(await request.body()))
    try:
        if values.get("CPID") != settings.kiwoompay_cpid:
            _log_notification_outcome("kiwoom_notification_rejected", "cpid_mismatch")
            return _ack(False, 400)
        pay_method = str(values.get("PAYMETHOD") or "")
        if not _is_successful_notification_outcome(values):
            # Receipt is ACKed only after durable storage, never as order
            # finality. BANK_CANCEL legitimately omits ORDERNO.
            repo.client.rpc('record_kiwoom_nonapproval_notification', {
                'p_cpid': values['CPID'], 'p_provider_order_id': values.get('ORDERNO'),
                'p_provider_transaction_id': values.get('DAOUTRX'),
                'p_amount': int(values.get('AMOUNT') or 0), 'p_payment_method': pay_method,
                'p_payload': _normalized_notification_payload(values, source_ip), 'p_source_ip': source_ip,
            })
            _log_notification_outcome("kiwoom_notification_acknowledged", "explicit_failure_or_cancel")
            return _ack(True)
        order_id, transaction_id = values.get("ORDERNO"), values.get("DAOUTRX")
        if not order_id or not transaction_id:
            _log_notification_outcome("kiwoom_notification_rejected", "missing_keys")
            return _ack(False, 400)
        rows = repo.client.rest_get("payment_orders", {
            "select": ORDER_SELECT, "order_id": f"eq.{order_id}", "limit": "1",
        })
        if not rows:
            _log_notification_outcome("kiwoom_notification_rejected", "order_not_found")
            return _ack(False, 404)
        order = rows[0]
        if int(values.get("AMOUNT") or 0) != int(order["amount"]):
            _log_notification_outcome("kiwoom_notification_rejected", "amount_mismatch")
            return _ack(False, 409)
        requested_method = str(order.get("requested_payment_method") or "TOTAL")
        if requested_method == "BANK" and pay_method != "BANK":
            _log_notification_outcome("kiwoom_notification_rejected", "method_mismatch")
            return _ack(False, 409)
        if not pay_method:
            _log_notification_outcome("kiwoom_notification_rejected", "missing_method")
            return _ack(False, 400)
        legacy_subsidized = (
            order.get("voucher_product_id") is None
            and int(order.get("voucher_count") or 0) == 1
            and int(order.get("paid_voucher_count") or 0) == 1
            and int(order.get("bonus_voucher_count") or 0) == 0
        )
        if (order.get("status") == "ready" and order.get("pay_type") == "subsidized"
                and int(order.get("amount") or 0) > 0 and not order.get("checkout_started_at")
                and not legacy_subsidized):
            _log_notification_outcome("kiwoom_notification_rejected", "checkout_boundary")
            return _ack(False, 409)
        provider_response = _normalized_notification_payload(values, source_ip)
        # Kiwoom's validated result notification is the final approval. The RPC
        # repeats every stored-order check, persists the durable inbox record,
        # completes payment, and fulfills assets in one database transaction.
        repo.client.rpc("complete_kiwoom_payment_notification", {
            "p_order_id": order["id"], "p_provider_order_id": order_id,
            "p_cpid": values["CPID"], "p_amount": int(order["amount"]),
            "p_payment_method": pay_method, "p_provider_transaction_id": transaction_id,
            "p_payload": provider_response, "p_source_ip": source_ip,
        })
        return _ack(True)
    except HTTPException as exc:
        _log_notification_outcome("kiwoom_notification_failed", "unexpected", level=logging.ERROR)
        return _ack(False, exc.status_code)
    except SupabaseHttpError as exc:
        if "TAX_TYPE_UNCLASSIFIED" in exc.body:
            _log_notification_outcome("kiwoom_notification_failed", "tax", level=logging.ERROR)
            return _ack(False, 409)
        _log_notification_outcome("kiwoom_notification_failed", "supabase", level=logging.ERROR)
        return _ack(False, 500)
    except (ValueError, TypeError):
        _log_notification_outcome("kiwoom_notification_failed", "value", level=logging.ERROR)
        return _ack(False, 500)
    except Exception:
        _log_notification_outcome("kiwoom_notification_failed", "unexpected", level=logging.ERROR)
        return _ack(False, 500)


@router.get("/notification")
async def notification_get(request: Request):
    return await _notification(request)


@router.post("/notification")
async def notification_post(request: Request):
    return await _notification(request)


class LocalAbandonmentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    amount: int = Field(gt=0, strict=True)
    acknowledge_provider_uncertainty: StrictBool | None = None
    explicit_checkout_cancel_intent: StrictBool | None = None
    checkout_return_ended: Literal['sdk_frame_fail', 'mobile_fail'] | None = None

    @model_validator(mode='after')
    def explicit_local_authorization(self):
        # Do not silently assert the old warning checkbox on the cancel path.
        supplied = self.model_fields_set
        if supplied == {'amount', 'acknowledge_provider_uncertainty'} and self.acknowledge_provider_uncertainty is True:
            return self
        if supplied == {'amount', 'explicit_checkout_cancel_intent'} and self.explicit_checkout_cancel_intent is True:
            return self
        if supplied == {'amount', 'checkout_return_ended'} and self.checkout_return_ended is not None:
            return self
        raise ValueError('Exactly one explicit local-stop authorization required')


@router.post('/orders/{order_id}/abandon')
def abandon_order(
    payload: LocalAbandonmentRequest,
    order_id: str = Path(min_length=6, max_length=64, pattern=r'^[A-Za-z0-9_-]+$'),
    token: str = Depends(bearer_token),
):
    """Owner explicitly stops local checkout, not external payment/refund."""
    repo = JoinRepository()
    try:
        _, profile = _customer(repo, token, allow_employee=True)
        args = {
            'p_order_id': order_id, 'p_user_id': str(profile.id), 'p_amount': payload.amount,
            'p_acknowledge_provider_uncertainty': payload.acknowledge_provider_uncertainty,
        }
        if payload.checkout_return_ended is not None:
            args['p_explicit_checkout_cancel_intent'] = False
            args['p_checkout_return_ended'] = payload.checkout_return_ended
            repo.client.rpc('abandon_owned_payment_order_intent', args)
        elif payload.explicit_checkout_cancel_intent is True:
            args['p_explicit_checkout_cancel_intent'] = True
            repo.client.rpc('abandon_owned_payment_order_intent', args)
        else:
            repo.client.rpc('abandon_owned_payment_order', args)
        # Read back the exact owner/order/amount; do not invent a terminal DTO
        # from the request or assume write success means durable local receipt.
        result = recovery(order_id=order_id, amount=payload.amount, token=token)
        if not result['data'].get('local_abandonment'):
            raise _error(503, 'LOCAL_ABANDONMENT_UNAVAILABLE', '주문 중단 결과를 확인하지 못했어요. 상태를 다시 확인해 주세요')
        return result
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, 'UNAUTHENTICATED', '로그인 정보가 올바르지 않아요') from exc
        for code, status in [('ORDER_NOT_FOUND', 404), ('AMOUNT_MISMATCH', 400),
                             ('OWNER_NOT_ELIGIBLE', 403), ('ORDER_HAS_PAYMENT_OR_RESOURCE_HISTORY', 409),
                             ('COUPON_RESERVATION_CONFLICT', 409), ('RESERVATION_OWNERSHIP_CONFLICT', 409)]:
            if code in exc.body:
                raise _error(status, code, '주문을 중단할 수 없어요. 주문 상태를 다시 확인해 주세요') from exc
        raise _error(503, 'LOCAL_ABANDONMENT_UNAVAILABLE', '주문 상태를 확인하지 못했어요. 다시 확인해 주세요') from exc
    except Exception as exc:
        raise _error(503, 'LOCAL_ABANDONMENT_UNAVAILABLE', '주문 상태를 확인하지 못했어요. 다시 확인해 주세요') from exc


@router.get('/local-abandonments')
def local_abandonment_history(
    limit: int = Query(default=20, ge=1, le=50), token: str = Depends(bearer_token),
):
    """Bounded owner-only history survives retiring the active checkout intent."""
    repo = JoinRepository()
    try:
        _, profile = _customer(repo, token, allow_employee=True)
        receipts = repo.client.rest_get('payment_order_local_abandonments', {
            'select': LOCAL_SELECT, 'user_id': f'eq.{profile.id}',
            'order': 'requested_at.desc,id.desc', 'limit': str(limit),
        })
        operator_receipts = repo.client.rest_get('payment_order_operator_local_stops', {
            'select': OPERATOR_SELECT, 'user_id': f'eq.{profile.id}',
            'order': 'requested_at.desc,id.desc', 'limit': str(limit),
        })
        from datetime import datetime
        receipts = sorted(receipts + operator_receipts,
                          key=lambda row: (datetime.fromisoformat(row['requested_at'].replace('Z', '+00:00')), row['id']),
                          reverse=True)[:limit]
        orders = []
        seen = set()
        for receipt in receipts:
            if receipt['order_id'] in seen:
                raise ValueError('Conflicting local history receipts')
            seen.add(receipt['order_id'])
            rows = repo.client.rest_get('payment_orders', {
                'select': ORDER_SELECT, 'id': f"eq.{receipt['order_id']}",
                'user_id': f'eq.{profile.id}', 'amount': f"eq.{receipt['amount']}", 'limit': '1',
            })
            if not rows:
                raise ValueError('Missing owned local order')
            data = local_recovery(repo, rows[0], str(profile.id))
            if data is None:
                raise ValueError('Missing local receipt')
            orders.append(data)
        return {'ok': True, 'data': {'orders': orders}, 'error': None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, 'UNAUTHENTICATED', '로그인 정보가 올바르지 않아요') from exc
        raise _error(503, 'LOCAL_HISTORY_UNAVAILABLE', '중단한 주문 내역을 확인하지 못했어요') from exc
    except Exception as exc:
        raise _error(503, 'LOCAL_HISTORY_UNAVAILABLE', '중단한 주문 내역을 확인하지 못했어요') from exc


@router.get("/recovery")
def recovery(
    order_id: str = Query(min_length=6, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    amount: int = Query(gt=0),
    token: str = Depends(bearer_token),
):
    """Recover one owned positive-payment order without creating or approving it.

    A local canceled/failed state alone is not proof that a provider cannot charge.
    Only an immutable owner-scoped local receipt authorizes retiring local intent;
    it retains unknown provider finality and is overridden by late-charge history.
    0064 durably quarantines non-ready/second approvals without fulfillment/refund.
    Recovery never offers another payable entry or contacts the provider.
    """
    repo, settings = JoinRepository(), get_settings()
    try:
        _, profile = _customer(repo, token, allow_employee=True)
        rows = repo.client.rest_get("payment_orders", {
            "select": ORDER_SELECT, "order_id": f"eq.{order_id}",
            "user_id": f"eq.{profile.id}", "limit": "1",
        })
        if not rows:
            raise _error(404, "ORDER_NOT_FOUND", "결제 주문을 찾을 수 없어요")
        order = rows[0]
        if int(order["amount"]) != amount:
            raise _error(400, "AMOUNT_MISMATCH", "결제 금액이 주문 금액과 일치하지 않아요")
        status = order.get("status")
        data = {
            "order_id": order_id, "amount": amount,
            "status": status if status in {
                "ready", "done", "failed", "canceled", "refund_processing", "refunded",
            } else "unknown",
            "recovery_action": "reconcile", "checkout_url": None, "resumable": False,
        }
        if status == "done":
            _require_order_tax_classified(order)
            data["recovery_action"] = "complete"
            data["completion"] = present_payment_completion(
                order, base_url=settings.kiwoompay_base_url, cpid=settings.kiwoompay_cpid,
            )
        elif status in {'failed', 'canceled'}:
            closures = repo.client.rest_get('payment_order_closures', {
                'select': 'id,evidence_sha256,outcome,closed_at',
                'order_id': f"eq.{order['id']}", 'user_id': f'eq.{profile.id}',
                'amount': f'eq.{amount}', 'outcome': f'eq.{status}', 'limit': '1',
            })
            if closures:
                from app.services.payment_closure import public_closure
                closure = public_closure(closures[0], status)
                if closure:
                    late_approvals = repo.client.rest_get('payment_callback_discrepancies', {
                        'select': 'id', 'order_id': f"eq.{order['id']}",
                        'kind': 'eq.late_approval', 'limit': '1',
                    })
                    # An observed real charge contradicts the attestation. Keep
                    # immutable history but do not advertise verified finality.
                    if not late_approvals:
                        data.update(recovery_action='closed', user_id=str(profile.id), completion=None, closure=closure)
            else:
                try:
                    local = local_recovery(repo, order, str(profile.id))
                except (ValueError, KeyError, TypeError) as exc:
                    raise _error(503, 'LOCAL_RECEIPT_INVALID', '중단한 주문 상태를 확인하지 못했어요') from exc
                if local is not None:
                    data = local
        # A ready status read is intentionally mutation-free. Expiry/release and
        # payable eligibility belong to their existing write/admission paths,
        # not to bounded close/return refresh. Hidden/expired products must not
        # prevent an owner from observing and explicitly stopping this intent.
        return {"ok": True, "data": data, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인 정보가 올바르지 않아요") from exc
        raise _error(502, "SUPABASE_ERROR", "결제 주문 상태를 확인하지 못했어요") from exc


@router.post("/confirm")
def confirm(payload: PaymentConfirmRequest, token: str = Depends(bearer_token)):
    repo, settings = JoinRepository(), get_settings()
    try:
        _, profile = _customer(repo, token, allow_employee=True)
        rows = repo.client.rest_get("payment_orders", {
            "select": ORDER_SELECT, "order_id": f"eq.{payload.order_id}",
            "user_id": f"eq.{profile.id}", "limit": "1",
        })
        if not rows:
            raise _error(404, "ORDER_NOT_FOUND", "결제 주문을 찾을 수 없어요")
        order = rows[0]
        _require_order_tax_classified(order)
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
        completion = present_payment_completion(
            order,
            base_url=settings.kiwoompay_base_url,
            cpid=settings.kiwoompay_cpid,
        )
        return {"ok": True, "data": completion, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "결제 승인 결과를 확인하지 못했어요") from exc


def _checkout_return_page():
    # No query/callback data, opener messages or payment authority. A popup
    # closing is only a UI signal; the parent reads its own authenticated order.
    return HTMLResponse("""<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>구매 화면으로 돌아가기</title><body><h1>결제창에서 돌아왔습니다</h1>
<p>이 화면은 PG 승인·취소·환불 확정이 아닙니다. 구매 화면에서 서버 주문 상태를 확인해 주세요.</p>
<button type="button" onclick="window.close()">결제창 닫고 구매 화면으로 돌아가기</button>
<p>창이 닫히지 않으면 직접 닫은 뒤 기존 구매 화면으로 돌아가 주세요. 이전 결제창은 다시 열지 마세요.</p>
<script>window.close();</script></body></html>""", headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/redirect/success", response_class=HTMLResponse)
def redirect_success():
    return _checkout_return_page()


@short_redirect_router.get("/p", response_class=HTMLResponse)
@short_redirect_router.post("/p", response_class=HTMLResponse)
def short_redirect_success():
    return redirect_success()


@short_redirect_router.get("/f", response_class=HTMLResponse)
def short_redirect_fail():
    return _checkout_return_page()


@short_redirect_router.get("/c", response_class=HTMLResponse)
def short_redirect_close():
    return _checkout_return_page()


@router.get("/redirect/fail", response_class=HTMLResponse)
def redirect_fail():
    return _checkout_return_page()


@router.get("/redirect/close", response_class=HTMLResponse)
def redirect_close():
    return _checkout_return_page()
