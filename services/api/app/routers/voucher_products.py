from __future__ import annotations

import secrets
import logging
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
from app.services.product_images import managed_image_path
from app.services.vouchers import calculate_sale_price, krw_amount, per_voucher_price, resolve_voucher_merchant

router = APIRouter(tags=["voucher-products"])
logger = logging.getLogger(__name__)
_PRODUCT_SELECT = "id,merchant_id,name,voucher_count,bonus_count,unit_price,discount_rate,sale_price,status,display_order,image_url,is_event,event_start_at,event_end_at,created_at,updated_at"
_LEGACY_PRODUCT_SELECT = "id,merchant_id,name,voucher_count,bonus_count,unit_price,discount_rate,sale_price,status,display_order,image_url,created_at,updated_at"


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _as_utc(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _event_status(row: dict, now: datetime | None = None) -> tuple[str, str]:
    if row.get("status") != "active":
        return "hidden", "숨김(수동)"
    if not row.get("is_event"):
        return "active", "판매중"
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = _as_utc(row.get("event_start_at"))
    end = _as_utc(row.get("event_end_at"))
    if start is None or end is None or end <= start:
        return "event_invalid", "기간 오류(이벤트 자동숨김)"
    if current < start:
        return "scheduled", "⏳ 예정(이벤트)"
    if current <= end:
        return "event_active", "🎉 진행중(이벤트)"
    return "event_ended", "종료(이벤트 자동숨김)"


def _is_exposed(row: dict, now: datetime | None = None) -> bool:
    return _event_status(row, now)[0] in {"active", "event_active"}


def _validate_event_window(row: dict) -> None:
    if not row.get("is_event"):
        return
    start = _as_utc(row.get("event_start_at"))
    end = _as_utc(row.get("event_end_at"))
    if start is None or end is None:
        raise _error(422, "EVENT_PERIOD_REQUIRED", "이벤트 시작일시와 종료일시는 모두 필수예요")
    if end <= start:
        raise _error(422, "INVALID_EVENT_PERIOD", "이벤트 종료일시는 시작일시보다 늦어야 해요")


def _present(row: dict) -> dict:
    now = datetime.now(timezone.utc)
    status, label = _event_status(row, now)
    return {
        **row,
        "is_event": bool(row.get("is_event")),
        "total_count": int(row["voucher_count"]) + int(row.get("bonus_count") or 0),
        "exposed": _is_exposed(row, now),
        "exposure_status": status,
        "exposure_label": label,
    }


def _load_products(repo: JoinRepository, params: dict[str, str], *, allow_legacy: bool = False) -> tuple[list[dict], bool]:
    try:
        return repo.client.rest_get("voucher_products", {"select": _PRODUCT_SELECT, **params}), False
    except SupabaseHttpError as exc:
        if not ("is_event" in exc.body or "event_start_at" in exc.body or "PGRST204" in exc.body):
            raise
        if not allow_legacy:
            raise _error(503, "MIGRATION_REQUIRED", "0020_voucher_product_events.sql 적용이 필요해요") from exc
        rows = repo.client.rest_get("voucher_products", {"select": _LEGACY_PRODUCT_SELECT, **params})
        return [{**row, "is_event": False, "event_start_at": None, "event_end_at": None} for row in rows], True


def _delete_replaced_image(repo: JoinRepository, merchant_id: str, old_url: str | None, new_url: str | None) -> None:
    if not old_url or old_url == new_url:
        return
    object_path = managed_image_path(old_url, repo.client.settings.supabase_url, "merchant-images", merchant_id)
    if object_path is None:
        return
    try:
        repo.client.delete_public_objects("merchant-images", [object_path])
    except Exception:  # DB update already committed; never make the client delete the live new image.
        logger.exception("Failed to delete replaced voucher product image: %s", object_path)


def _values(payload: VoucherProductCreateRequest | VoucherProductUpdateRequest, *, partial: bool) -> dict:
    values = payload.model_dump(exclude_unset=partial, mode="json")
    if "name" in values:
        values["name"] = values["name"].strip()
    # Validate the same formula used by the generated DB column. sale_price is never accepted.
    if not partial:
        calculate_sale_price(values["unit_price"], values["voucher_count"], values["discount_rate"])
        _validate_event_window(values)
        if not values.get("is_event"):
            values.pop("is_event", None)
            values.pop("event_start_at", None)
            values.pop("event_end_at", None)
    return values


@router.get("/admin/voucher-products")
def admin_list_products(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        rows, migration_required = _load_products(repo, {
            "merchant_id": f"eq.{merchant_id}",
            "order": "display_order.asc,created_at.asc",
        }, allow_legacy=True)
        return {"ok": True, "data": {"items": [_present(row) for row in rows], "migration_required": migration_required}, "error": None}
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
        current, _ = _load_products(repo, {
            "id": f"eq.{product_id}", "merchant_id": f"eq.{merchant_id}", "limit": "1",
        }, allow_legacy=True)
        if not current:
            raise _error(404, "VOUCHER_PRODUCT_NOT_FOUND", "식권 상품을 찾을 수 없어요")
        values = _values(payload, partial=True)
        if not values:
            return {"ok": True, "data": _present(current[0]), "error": None}
        merged = {**current[0], **values}
        calculate_sale_price(merged["unit_price"], int(merged["voucher_count"]), merged["discount_rate"])
        _validate_event_window(merged)
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        row = repo.client.rest_patch("voucher_products", {
            "id": f"eq.{product_id}", "merchant_id": f"eq.{merchant_id}"
        }, values)[0]
        if "image_url" in values:
            _delete_replaced_image(repo, merchant_id, current[0].get("image_url"), values.get("image_url"))
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
        rows, _ = _load_products(repo, {
            "merchant_id": f"eq.{merchant['id']}",
            "status": "eq.active", "order": "display_order.asc,created_at.asc",
        })
        return {"ok": True, "data": {"items": [_present(row) for row in rows if _is_exposed(row)]}, "error": None}
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
        products, _ = _load_products(repo, {
            "id": f"eq.{payload.product_id}",
            "merchant_id": f"eq.{merchant['id']}", "status": "eq.active", "limit": "1",
        })
        if not products:
            raise _error(404, "VOUCHER_PRODUCT_NOT_FOUND", "판매 중인 식권 상품을 찾을 수 없어요")
        product = products[0]
        if not _is_exposed(product):
            raise _error(404, "VOUCHER_PRODUCT_NOT_EXPOSED", "현재 판매 기간이 아닌 식권 상품이에요")
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
