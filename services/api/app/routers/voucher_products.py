from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.auth import bearer_token
from app.config import get_settings
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.merchant_admin import _merchant_admin
from app.schemas import VoucherProductCreateRequest, VoucherProductUpdateRequest, VoucherPurchaseRequest
from app.services.join_flow import JoinFlowError
from app.services.vouchers import calculate_sale_price, krw_amount, per_voucher_price, resolve_voucher_merchant

router = APIRouter(tags=["voucher-products"])
_PRODUCT_SELECT = "id,merchant_id,name,voucher_count,bonus_count,unit_price,discount_rate,sale_price,status,display_order,image_url,created_at,updated_at"


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _present(row: dict) -> dict:
    return {**row, "total_count": int(row["voucher_count"]) + int(row.get("bonus_count") or 0)}


def _values(payload: VoucherProductCreateRequest | VoucherProductUpdateRequest, *, partial: bool) -> dict:
    values = payload.model_dump(exclude_unset=partial, mode="json")
    if "name" in values:
        values["name"] = values["name"].strip()
    # Validate the same formula used by the generated DB column. sale_price is never accepted.
    if not partial:
        calculate_sale_price(values["unit_price"], values["voucher_count"], values["discount_rate"])
    return values


@router.get("/admin/voucher-products")
def admin_list_products(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        rows = repo.client.rest_get("voucher_products", {
            "select": _PRODUCT_SELECT, "merchant_id": f"eq.{merchant_id}",
            "order": "display_order.asc,created_at.asc",
        })
        return {"ok": True, "data": {"items": [_present(row) for row in rows]}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "식권 상품을 불러오지 못했어요") from exc


@router.post("/admin/voucher-products", status_code=201)
def admin_create_product(payload: VoucherProductCreateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        values = {**_values(payload, partial=False), "merchant_id": merchant_id}
        row = repo.client.rest_post("voucher_products", values)[0]
        return {"ok": True, "data": _present(row), "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "식권 상품을 저장하지 못했어요") from exc


@router.patch("/admin/voucher-products/{product_id}")
def admin_update_product(product_id: str, payload: VoucherProductUpdateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        current = repo.client.rest_get("voucher_products", {
            "select": _PRODUCT_SELECT, "id": f"eq.{product_id}", "merchant_id": f"eq.{merchant_id}", "limit": "1",
        })
        if not current:
            raise _error(404, "VOUCHER_PRODUCT_NOT_FOUND", "식권 상품을 찾을 수 없어요")
        values = _values(payload, partial=True)
        if not values:
            return {"ok": True, "data": _present(current[0]), "error": None}
        merged = {**current[0], **values}
        calculate_sale_price(merged["unit_price"], int(merged["voucher_count"]), merged["discount_rate"])
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        row = repo.client.rest_patch("voucher_products", {
            "id": f"eq.{product_id}", "merchant_id": f"eq.{merchant_id}"
        }, values)[0]
        return {"ok": True, "data": _present(row), "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "식권 상품을 수정하지 못했어요") from exc


@router.get("/vouchers/products")
def active_products():
    repo = JoinRepository()
    try:
        merchant = resolve_voucher_merchant(repo, get_settings().pilot_merchant_id)
        if not merchant:
            return {"ok": True, "data": {"items": []}, "error": None}
        rows = repo.client.rest_get("voucher_products", {
            "select": _PRODUCT_SELECT, "merchant_id": f"eq.{merchant['id']}",
            "status": "eq.active", "order": "display_order.asc,created_at.asc",
        })
        return {"ok": True, "data": {"items": [_present(row) for row in rows]}, "error": None}
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "판매 중인 식권 상품을 불러오지 못했어요") from exc


@router.post("/vouchers/purchase", status_code=201)
def purchase(payload: VoucherPurchaseRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    settings = get_settings()
    try:
        auth = repo.auth_user_from_token(token)
        profile = repo.get_profile(auth.id, email=auth.email)
        if profile is None or profile.status != "active" or profile.role != "customer":
            raise _error(403, "VOUCHER_ACCOUNT_ONLY", "개인 식권 계정만 식권을 구매할 수 있어요")
        merchant = resolve_voucher_merchant(repo, settings.pilot_merchant_id)
        if not merchant:
            raise _error(404, "MERCHANT_NOT_FOUND", "식당을 찾을 수 없어요")
        products = repo.client.rest_get("voucher_products", {
            "select": _PRODUCT_SELECT, "id": f"eq.{payload.product_id}",
            "merchant_id": f"eq.{merchant['id']}", "status": "eq.active", "limit": "1",
        })
        if not products:
            raise _error(404, "VOUCHER_PRODUCT_NOT_FOUND", "판매 중인 식권 상품을 찾을 수 없어요")
        product = products[0]
        total_count = int(product["voucher_count"]) + int(product.get("bonus_count") or 0)
        amount = krw_amount(product["sale_price"])
        if amount <= 0:
            raise _error(400, "INVALID_AMOUNT", "결제 금액이 올바르지 않아요")
        order_id = f"GE-V-{uuid.uuid4().hex}"
        checkout_token = secrets.token_urlsafe(32)
        order = repo.client.rest_post("toss_payment_orders", {
            "order_id": order_id, "checkout_token": checkout_token, "user_id": profile.id,
            "merchant_id": merchant["id"], "product_id": None, "voucher_product_id": product["id"],
            "merchant_name": merchant["name"], "product_name": product["name"], "amount": amount,
            "status": "ready", "pay_type": "voucher", "voucher_count": total_count,
            # Toss charges integer KRW; snapshot from that exact charged amount, not numeric sale_price.
            "voucher_purchase_price": str(per_voucher_price(amount, total_count)),
        })[0]
        return {"ok": True, "data": {
            "order_id": order_id, "amount": int(order["amount"]), "product_id": product["id"],
            "product_name": product["name"], "total_count": total_count,
            "checkout_url": f"{settings.public_api_base_url}/toss/checkout/{checkout_token}",
        }, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "식권 결제 주문을 만들지 못했어요") from exc
