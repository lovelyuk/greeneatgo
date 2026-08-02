from __future__ import annotations

import secrets
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.auth import bearer_token, optional_bearer_token
from app.config import get_settings
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.merchant_admin import _merchant_admin
from app.schemas import LegacyCompatibleVoucherPurchaseRequest, VoucherProductCreateRequest, VoucherProductUpdateRequest, VoucherPurchaseRequest, VoucherQuoteRequest
from app.services.coupon_pricing import build_quote, coupon_is_valid, coupon_snapshot
from app.services.join_flow import JoinFlowError
from app.services.product_images import managed_image_path
from app.services.vouchers import calculate_sale_price, krw_amount, per_voucher_price, resolve_voucher_merchant

router = APIRouter(tags=["voucher-products"])
logger = logging.getLogger(__name__)
_PRODUCT_SELECT = "id,merchant_id,name,voucher_count,bonus_count,unit_price,discount_rate,discount_amount_per_voucher,sale_price,status,display_order,kiwoom_pay_method,image_url,is_event,event_start_at,event_end_at,tax_type,deleted_at,created_at,updated_at"
_LEGACY_PRODUCT_SELECT = "id,merchant_id,name,voucher_count,bonus_count,unit_price,discount_rate,sale_price,status,display_order,image_url,created_at,updated_at"


def _expire_stale_subsidized_orders(repo: JoinRepository, user_id: str) -> None:
    """Recover reservations only after the server-enforced 30-minute window."""
    repo.client.rpc("expire_stale_subsidized_orders", {"p_user_id": user_id})


def _subsidized_context(repo: JoinRepository, token: str):
    auth = repo.auth_user_from_token(token)
    profile = repo.get_profile(auth.id, email=auth.email)
    if profile is None or profile.status != "active" or profile.role != "employee" or not profile.company_id:
        raise _error(403, "LEDGER_EMPLOYEE_ONLY", "장부업체 직원만 이용할 수 있어요")
    merchant = resolve_voucher_merchant(repo, get_settings().pilot_merchant_id)
    if not merchant:
        raise _error(404, "MERCHANT_NOT_FOUND", "식당을 찾을 수 없어요")
    links = repo.client.rest_get("merchant_companies", {"select": "company_id,unit_price,subsidy_enabled,company_subsidy_amount,restaurant_subsidy_amount,status", "merchant_id": f"eq.{merchant['id']}", "company_id": f"eq.{profile.company_id}", "status": "eq.active", "limit": "1"})
    if not links or not links[0].get("subsidy_enabled"):
        raise _error(404, "SUBSIDY_NOT_AVAILABLE", "보조금 계약 대상이 아니에요")
    contract = links[0]
    unit, company, restaurant = int(contract.get("unit_price") or 0), int(contract.get("company_subsidy_amount") or 0), int(contract.get("restaurant_subsidy_amount") or 0)
    if unit <= 0 or company < 0 or restaurant < 0 or company + restaurant >= unit:
        raise _error(409, "INVALID_SUBSIDY_CONTRACT", "보조금 계약 금액이 올바르지 않아요")
    return profile, merchant, contract


@router.get("/vouchers/subsidized-price")
def subsidized_price(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant, contract = _subsidized_context(repo, token)
        unit, company, restaurant = int(contract["unit_price"]), int(contract["company_subsidy_amount"]), int(contract["restaurant_subsidy_amount"])
        return {"ok": True, "data": {"merchant_id": merchant["id"], "merchant_name": merchant["name"], "unit_price": unit, "employee_pay_amount": unit-company-restaurant, "company_subsidy_amount": company, "restaurant_subsidy_amount": restaurant}, "error": None}
    except HTTPException: raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인 정보가 올바르지 않아요") from exc
        raise _error(502, "SUPABASE_ERROR", "보조금 가격을 불러오지 못했어요") from exc


@router.post("/vouchers/subsidized-orders/{order_id}/cancel")
def cancel_subsidized_order(order_id: str, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        auth = repo.auth_user_from_token(token)
        rows = repo.client.rest_get("payment_orders", {"select": "id,user_id,pay_type", "order_id": f"eq.{order_id}", "user_id": f"eq.{auth.id}", "pay_type": "eq.subsidized", "limit": "1"})
        if not rows:
            raise _error(404, "ORDER_NOT_FOUND", "취소할 주문을 찾을 수 없어요")
        result = repo.client.rpc("release_subsidized_order_points", {"p_order_id": rows[0]["id"], "p_user_id": auth.id})
        return {"ok": True, "data": result, "error": None}
    except HTTPException: raise
    except SupabaseHttpError as exc:
        if "CHECKOUT_ALREADY_STARTED" in exc.body:
            raise _error(409, "CHECKOUT_ALREADY_STARTED", "결제가 시작된 주문은 자동 취소할 수 없어요. 결제 상태를 다시 확인해 주세요") from exc
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인 정보가 올바르지 않아요") from exc
        raise _error(502, "ORDER_CANCEL_FAILED", "포인트 예약을 해제하지 못했어요") from exc


@router.post("/vouchers/purchase-subsidized", status_code=201)
def purchase_subsidized(payload: LegacyCompatibleVoucherPurchaseRequest | None = None, token: str = Depends(bearer_token)):
    repo, settings = JoinRepository(), get_settings()
    try:
        profile, merchant, contract = _subsidized_context(repo, token)
        _expire_stale_subsidized_orders(repo, profile.id)
        company, restaurant = int(contract["company_subsidy_amount"]), int(contract["restaurant_subsidy_amount"])
        if payload is not None and payload.product_id:
            products, _ = _load_products(repo, {"id": f"eq.{payload.product_id}", "merchant_id": f"eq.{merchant['id']}", "status": "eq.active", "deleted_at": "is.null", "limit": "1"}, allow_legacy=True)
        else:
            # Temporary compatibility for deployed clients which POSTed no body.
            candidates, _ = _load_products(repo, {
                "merchant_id": f"eq.{merchant['id']}", "status": "eq.active", "deleted_at": "is.null",
                "order": "display_order.asc,created_at.asc",
            }, allow_legacy=True)
            unit_price = int(contract["unit_price"])
            products = [
                product for product in candidates
                if _is_exposed(product)
                and int(product.get("voucher_count") or 0) == 1
                and int(product.get("bonus_count") or 0) == 0
                and krw_amount(str(product.get("sale_price") or 0)) == unit_price
            ]
            # Prefer the historical TOTAL flow, but never guess among matches.
            total_products = [product for product in products if str(product.get("kiwoom_pay_method") or "TOTAL") == "TOTAL"]
            if len(total_products) == 1:
                products = total_products
            if len(products) != 1:
                raise _error(409, "UPGRADE_REQUIRED", "상품을 안전하게 선택할 수 없어 앱 업데이트가 필요해요")
        if not products:
            raise _error(404, "VOUCHER_PRODUCT_NOT_FOUND", "판매 중인 식권 상품을 찾을 수 없어요")
        product = products[0]
        if not _is_exposed(product):
            raise _error(404, "VOUCHER_PRODUCT_NOT_EXPOSED", "현재 판매 기간이 아닌 식권 상품이에요")
        _require_classified_product(product)
        paid, bonus = int(product["voucher_count"]), int(product.get("bonus_count") or 0)
        gross_amount = krw_amount(product["sale_price"]) - (company + restaurant) * paid
        if gross_amount <= 0:
            raise _error(409, "INVALID_SUBSIDIZED_PRICE", "직원 결제 금액이 올바르지 않아요")
        coupon = _selected_coupon(
            repo, merchant["id"], payload.coupon_id if payload else None,
            payload.user_coupon_id if payload else None, profile.id,
        )
        requested_points = payload.requested_point_amount if payload else None
        quote = build_quote(
            gross_amount=gross_amount, coupon=coupon, requested_point_amount=requested_points,
            available_point_amount=0, points_allowed=True,
        )
        # Point reservation is performed under database wallet/order locks. Only
        # the coupon-adjusted burden is calculated here; the RPC computes points.
        employee_due = int(quote["amount_after_coupon"])
        order_id, checkout_token = f"GE-S-{uuid.uuid4().hex}", secrets.token_urlsafe(32)
        order = repo.client.rest_post("payment_orders", {
            "order_id": order_id, "checkout_token": checkout_token, "user_id": profile.id,
            "merchant_id": merchant["id"], "company_id": profile.company_id, "product_id": None,
            "voucher_product_id": product["id"], "merchant_name": merchant["name"], "product_name": product["name"],
            "amount": employee_due, "gross_amount": gross_amount,
            "coupon_id": coupon["id"] if coupon else None,
            "user_coupon_id": coupon.get("_user_coupon_id") if coupon else None,
            "coupon_discount_amount": int(quote["coupon_discount_amount"]),
            "coupon_snapshot": coupon_snapshot(coupon) if coupon else None,
            "requested_point_amount": requested_points,
            "total_employee_burden": employee_due, "status": "ready", "pay_type": "subsidized",
            "requested_payment_method": product.get("kiwoom_pay_method") or "TOTAL",
            "voucher_count": paid + bonus, "paid_voucher_count": paid, "bonus_voucher_count": bonus,
            "voucher_purchase_price": str(per_voucher_price(employee_due, paid)),
            "company_subsidy_amount": company, "restaurant_subsidy_amount": restaurant,
        })[0]
        _reserve_issued_coupon(repo, order, coupon, profile.id, merchant["id"])
        try:
            split = repo.client.rpc("reserve_subsidized_order_points", {"p_order_id": order["id"]})
            point_amount, card_amount = int(split["point_amount"]), int(split["card_amount"])
            fulfilled = None
            if card_amount == 0:
                fulfilled = repo.client.rpc("fulfill_subsidized_order", {"p_order_id": order["id"], "p_provider_payment_key": None, "p_payment_method": "POINT", "p_provider_response": None, "p_approved_at": datetime.now(timezone.utc).isoformat()})
        except Exception:
            _cancel_ready_order(repo, order["id"])
            raise
        return {"ok": True, "data": {
            "order_id": order_id, "amount": card_amount, "gross_amount": gross_amount,
            "employee_pay_amount": employee_due, "coupon_id": coupon["id"] if coupon else None,
            "user_coupon_id": coupon.get("_user_coupon_id") if coupon else None,
            "coupon_discount_amount": int(quote["coupon_discount_amount"]),
            "requested_point_amount": requested_points, "point_amount": point_amount,
            "card_amount": card_amount, "point_only": card_amount == 0,
            "product_id": product["id"], "product_name": product["name"], "total_count": paid + bonus,
            "paid_voucher_count": paid, "bonus_voucher_count": bonus,
            "payment_method": product.get("kiwoom_pay_method") or "TOTAL",
            "checkout_url": None if card_amount == 0 else f"{settings.public_api_base_url}/payments/checkout/{checkout_token}",
            "fulfillment": fulfilled,
        }, "error": None}
    except HTTPException: raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인 정보가 올바르지 않아요") from exc
        raise _error(502, "SUPABASE_ERROR", "보조금 식권 주문을 만들지 못했어요") from exc


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _selected_coupon(repo: JoinRepository, merchant_id: str, coupon_id: str | None,
                     user_coupon_id: str | None = None, user_id: str | None = None) -> dict | None:
    # Issued instances take priority over the public catalog selection.
    if user_coupon_id is not None:
        rows = repo.client.rest_get("user_coupons", {
            "select": "id,user_id,merchant_id,coupon_id,coupon_snapshot,valid_from,valid_until,status",
            "id": f"eq.{user_coupon_id}", "user_id": f"eq.{user_id}",
            "merchant_id": f"eq.{merchant_id}", "limit": "1",
        })
        if not rows:
            raise _error(400, "COUPON_NOT_USABLE", "사용할 수 없는 쿠폰이에요")
        issued = rows[0]
        now = datetime.now(timezone.utc)
        valid_from = _as_utc(issued.get("valid_from"))
        valid_until = _as_utc(issued.get("valid_until"))
        if issued.get("status") != "available" or (valid_from and valid_from > now) or (valid_until and valid_until <= now):
            raise _error(400, "COUPON_NOT_USABLE", "이미 사용했거나 만료된 쿠폰이에요")
        snapshot = dict(issued.get("coupon_snapshot") or {})
        if snapshot.get("id") != issued.get("coupon_id") or snapshot.get("merchant_id") != merchant_id:
            raise _error(400, "COUPON_NOT_USABLE", "사용할 수 없는 쿠폰이에요")
        snapshot.update({"is_active": True, "valid_from": None, "valid_until": None,
                         "_user_coupon_id": user_coupon_id})
        return snapshot
    if coupon_id is None:
        return None
    rows = repo.client.rest_get("merchant_coupons", {
        "select": "id,merchant_id,name,discount_type,discount_value,valid_from,valid_until,is_active",
        "id": f"eq.{coupon_id}", "merchant_id": f"eq.{merchant_id}", "limit": "1",
    })
    if not rows:
        raise _error(404, "COUPON_NOT_FOUND", "쿠폰을 찾을 수 없어요")
    if not coupon_is_valid(rows[0]):
        raise _error(409, "COUPON_NOT_AVAILABLE", "현재 사용할 수 없는 쿠폰이에요")
    return rows[0]


def _reserve_issued_coupon(repo: JoinRepository, order: dict, coupon: dict | None,
                           user_id: str, merchant_id: str) -> None:
    user_coupon_id = coupon.get("_user_coupon_id") if coupon else None
    if not user_coupon_id:
        return
    try:
        repo.client.rpc("reserve_user_coupon", {
            "p_order_id": order["id"], "p_user_coupon_id": user_coupon_id,
            "p_user_id": user_id, "p_merchant_id": merchant_id,
        })
    except SupabaseHttpError as exc:
        # A losing concurrent order is made authoritatively non-payable.
        _cancel_ready_order(repo, order["id"])
        raise _error(
            400,
            "COUPON_NOT_USABLE",
            "이미 다른 결제에서 사용 중이거나 사용할 수 없는 쿠폰이에요",
        ) from exc


def _cancel_ready_order(repo: JoinRepository, order_id: str) -> None:
    """Best-effort setup rollback; the DB trigger releases any issued coupon."""
    try:
        repo.client.rest_patch("payment_orders", {
            "id": f"eq.{order_id}", "status": "eq.ready", "provider_payment_key": "is.null",
        }, {"status": "canceled"})
    except Exception:
        logger.exception("Failed to cancel ready order after checkout setup error: %s", order_id)


def _available_points(repo: JoinRepository, user_id: str) -> int:
    rows = repo.client.rest_get("app_users", {
        "select": "point_balance,point_reserved", "id": f"eq.{user_id}", "limit": "1",
    })
    if not rows:
        return 0
    return max(int(rows[0].get("point_balance") or 0) - int(rows[0].get("point_reserved") or 0), 0)


def _quote_payload(*, product: dict, merchant: dict, gross: int, coupon: dict | None,
                   requested_points: int | None, available_points: int, points_allowed: bool) -> dict:
    quote = build_quote(
        gross_amount=gross, coupon=coupon, requested_point_amount=requested_points,
        available_point_amount=available_points, points_allowed=points_allowed,
    )
    return {
        **quote, "amount": quote["payment_amount"],
        "merchant_id": merchant["id"], "merchant_name": merchant["name"],
        "product_id": product["id"], "product_name": product["name"],
        "coupon": coupon_snapshot(coupon) if coupon else None,
        "user_coupon_id": coupon.get("_user_coupon_id") if coupon else None,
    }


def _product_migration_missing(exc: SupabaseHttpError) -> bool:
    body = exc.body.lower()
    return any(column in body for column in ("is_event", "event_start_at", "discount_amount_per_voucher", "deleted_at", "pgrst204"))


def _product_supabase_error(exc: SupabaseHttpError, message: str) -> HTTPException:
    if exc.status in (401, 403):
        return _error(401, "UNAUTHENTICATED", "로그인 정보가 올바르지 않아요")
    if _product_migration_missing(exc):
        return _error(503, "MIGRATION_REQUIRED", "0020·0030·0055 마이그레이션 적용이 필요해요")
    return _error(502, "SUPABASE_ERROR", message)


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
    if row.get("status") in {"sold_out", "inactive"}:
        return "sold_out", "일시품절"
    if row.get("status") != "active":
        return "sold_out", "일시품절"
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


def _require_classified_product(row: dict) -> None:
    if row.get("tax_type") == "unclassified":
        raise _error(409, "TAX_TYPE_UNCLASSIFIED", "과세 유형이 설정되지 않은 상품은 결제할 수 없어요")


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
        if not _product_migration_missing(exc):
            raise
        if not allow_legacy:
            raise _error(503, "MIGRATION_REQUIRED", "0020·0030·0055 마이그레이션 적용이 필요해요") from exc
        legacy_params = {key: value for key, value in params.items() if key != "deleted_at"}
        rows = repo.client.rest_get("voucher_products", {"select": _LEGACY_PRODUCT_SELECT, **legacy_params})
        return [{
            **row,
            "status": "sold_out" if row.get("status") == "inactive" else row.get("status"),
            "discount_amount_per_voucher": 0,
            "deleted_at": None,
            "kiwoom_pay_method": "TOTAL",
            "is_event": False,
            "event_start_at": None,
            "event_end_at": None,
            "tax_type": "unclassified",
        } for row in rows], True


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
    # GreenEat vouchers are always taxable. Keep this authoritative on the
    # server so stale or non-web clients cannot save another classification.
    values["tax_type"] = "taxable"
    if "name" in values:
        values["name"] = values["name"].strip()
    # Validate the same formula used by the generated DB column. sale_price is never accepted.
    if not partial:
        calculate_sale_price(
            values["unit_price"], values["voucher_count"], values["discount_rate"],
            values["discount_amount_per_voucher"],
        )
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
            "deleted_at": "is.null",
            "order": "display_order.asc,created_at.asc",
        }, allow_legacy=True)
        return {"ok": True, "data": {"items": [_present(row) for row in rows], "migration_required": migration_required}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _product_supabase_error(exc, "식권 상품을 불러오지 못했어요") from exc


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
        raise _product_supabase_error(exc, "식권 상품을 저장하지 못했어요") from exc


@router.patch("/admin/voucher-products/{product_id}")
def admin_update_product(product_id: str, payload: VoucherProductUpdateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        current, _ = _load_products(repo, {
            "id": f"eq.{product_id}", "merchant_id": f"eq.{merchant_id}", "deleted_at": "is.null", "limit": "1",
        }, allow_legacy=True)
        if not current:
            raise _error(404, "VOUCHER_PRODUCT_NOT_FOUND", "식권 상품을 찾을 수 없어요")
        values = _values(payload, partial=True)
        if not values:
            return {"ok": True, "data": _present(current[0]), "error": None}
        merged = {**current[0], **values}
        calculate_sale_price(
            merged["unit_price"], int(merged["voucher_count"]), merged["discount_rate"],
            merged.get("discount_amount_per_voucher") or 0,
        )
        _validate_event_window(merged)
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        rows = repo.client.rest_patch("voucher_products", {
            "id": f"eq.{product_id}", "merchant_id": f"eq.{merchant_id}", "deleted_at": "is.null",
        }, values)
        if not rows:
            raise _error(404, "VOUCHER_PRODUCT_NOT_FOUND", "식권 상품을 찾을 수 없어요")
        row = rows[0]
        if "image_url" in values:
            _delete_replaced_image(repo, merchant_id, current[0].get("image_url"), values.get("image_url"))
        return {"ok": True, "data": _present(row), "error": None}
    except HTTPException:
        raise
    except ValueError as exc:
        raise _error(422, "INVALID_VOUCHER_PRICE", "할인 후 판매가가 허용 범위를 벗어났어요") from exc
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _product_supabase_error(exc, "식권 상품을 수정하지 못했어요") from exc


@router.delete("/admin/voucher-products/{product_id}")
def admin_delete_product(product_id: str, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        rows = repo.client.rest_patch("voucher_products", {
            "id": f"eq.{product_id}",
            "merchant_id": f"eq.{merchant_id}",
            "deleted_at": "is.null",
        }, {
            "status": "sold_out",
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        if not rows:
            raise _error(404, "VOUCHER_PRODUCT_NOT_FOUND", "식권 상품을 찾을 수 없어요")
        return {"ok": True, "data": {"deleted": True, "id": product_id}, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _product_supabase_error(exc, "식권 상품을 삭제하지 못했어요") from exc


@router.get("/vouchers/products")
def active_products(token: str | None = Depends(optional_bearer_token)):
    repo = JoinRepository()
    try:
        profile = None
        if token is not None:
            # Invalid presented credentials propagate; only an absent header gets
            # the temporary public legacy catalog.
            auth = repo.auth_user_from_token(token)
            profile = repo.get_profile(auth.id, email=auth.email)
            if profile is None or profile.status != "active" or profile.role not in {"customer", "employee"}:
                raise _error(403, "VOUCHER_ACCOUNT_ONLY", "식권 계정만 상품을 조회할 수 있어요")
        if profile is not None and profile.role == "employee":
            _expire_stale_subsidized_orders(repo, profile.id)
        merchant = resolve_voucher_merchant(repo, get_settings().pilot_merchant_id)
        if not merchant:
            return {"ok": True, "data": {"purchase_mode": "none", "items": []}, "error": None}
        contract = None
        if profile is not None and profile.role == "employee":
            links = repo.client.rest_get("merchant_companies", {"select": "company_id,unit_price,subsidy_enabled,company_subsidy_amount,restaurant_subsidy_amount,status", "merchant_id": f"eq.{merchant['id']}", "company_id": f"eq.{profile.company_id}", "status": "eq.active", "limit": "1"})
            if not links or not links[0].get("subsidy_enabled"):
                return {"ok": True, "data": {"purchase_mode": "none", "items": []}, "error": None}
            contract = links[0]
        rows, _ = _load_products(repo, {
            "merchant_id": f"eq.{merchant['id']}",
            "status": "eq.active", "deleted_at": "is.null", "order": "display_order.asc,created_at.asc",
        }, allow_legacy=True)
        items = [_present(row) for row in rows if _is_exposed(row)]
        mode = "voucher"
        if contract is not None:
            mode = "subsidized"
            company, restaurant = int(contract.get("company_subsidy_amount") or 0), int(contract.get("restaurant_subsidy_amount") or 0)
            priced = []
            for item in items:
                paid_count = int(item["voucher_count"])
                employee_due = krw_amount(item["sale_price"]) - (company + restaurant) * paid_count
                if employee_due > 0:
                    priced.append({
                        **item,
                        "employee_pay_amount": employee_due,
                        # Explicit per-voucher names prevent clients from confusing
                        # contract snapshots with package totals. Keep the original
                        # names during the API transition for older app versions.
                        "per_voucher_company_subsidy_amount": company,
                        "per_voucher_restaurant_subsidy_amount": restaurant,
                        "company_subsidy_amount": company,
                        "restaurant_subsidy_amount": restaurant,
                        # Subsidies apply only to paid vouchers; bonuses are free.
                        "total_company_subsidy_amount": company * paid_count,
                        "total_restaurant_subsidy_amount": restaurant * paid_count,
                    })
            items = priced
        return {"ok": True, "data": {"purchase_mode": mode, "items": items}, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인 정보가 올바르지 않아요") from exc
        raise _error(502, "SUPABASE_ERROR", "판매 중인 식권 상품을 불러오지 못했어요") from exc


@router.post("/vouchers/quote")
def quote_purchase(payload: VoucherQuoteRequest, token: str = Depends(bearer_token)):
    """Return a display quote; purchase endpoints independently recalculate it."""
    repo, settings = JoinRepository(), get_settings()
    try:
        auth = repo.auth_user_from_token(token)
        profile = repo.get_profile(auth.id, email=auth.email)
        if profile is None or profile.status != "active" or profile.role not in {"customer", "employee"}:
            raise _error(403, "VOUCHER_ACCOUNT_ONLY", "식권 계정만 견적을 조회할 수 있어요")
        merchant = resolve_voucher_merchant(repo, settings.pilot_merchant_id)
        if not merchant:
            raise _error(404, "MERCHANT_NOT_FOUND", "식당을 찾을 수 없어요")
        products, _ = _load_products(repo, {
            "id": f"eq.{payload.product_id}", "merchant_id": f"eq.{merchant['id']}",
            "status": "eq.active", "deleted_at": "is.null", "limit": "1",
        }, allow_legacy=True)
        if not products or not _is_exposed(products[0]):
            raise _error(404, "VOUCHER_PRODUCT_NOT_FOUND", "판매 중인 식권 상품을 찾을 수 없어요")
        product = products[0]
        _require_classified_product(product)
        coupon = _selected_coupon(repo, merchant["id"], payload.coupon_id, payload.user_coupon_id, profile.id)
        if profile.role == "customer":
            if payload.requested_point_amount not in (None, 0):
                raise _error(422, "POINTS_NOT_AVAILABLE", "개인 식권 계정에는 포인트를 사용할 수 없어요")
            gross, available, points_allowed = krw_amount(product["sale_price"]), 0, False
            purchase_mode = "voucher"
        else:
            if not profile.company_id:
                raise _error(404, "SUBSIDY_NOT_AVAILABLE", "보조금 계약 대상이 아니에요")
            links = repo.client.rest_get("merchant_companies", {
                "select": "unit_price,subsidy_enabled,company_subsidy_amount,restaurant_subsidy_amount,status",
                "merchant_id": f"eq.{merchant['id']}", "company_id": f"eq.{profile.company_id}",
                "status": "eq.active", "limit": "1",
            })
            if not links or not links[0].get("subsidy_enabled"):
                raise _error(404, "SUBSIDY_NOT_AVAILABLE", "보조금 계약 대상이 아니에요")
            contract = links[0]
            paid = int(product["voucher_count"])
            gross = krw_amount(product["sale_price"]) - (
                int(contract.get("company_subsidy_amount") or 0)
                + int(contract.get("restaurant_subsidy_amount") or 0)
            ) * paid
            if gross <= 0:
                raise _error(409, "INVALID_SUBSIDIZED_PRICE", "직원 결제 금액이 올바르지 않아요")
            available, points_allowed, purchase_mode = _available_points(repo, profile.id), True, "subsidized"
        result = _quote_payload(
            product=product, merchant=merchant, gross=gross, coupon=coupon,
            requested_points=payload.requested_point_amount, available_points=available,
            points_allowed=points_allowed,
        )
        return {"ok": True, "data": {**result, "purchase_mode": purchase_mode}, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인 정보가 올바르지 않아요") from exc
        raise _error(502, "SUPABASE_ERROR", "식권 견적을 계산하지 못했어요") from exc


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
            "merchant_id": f"eq.{merchant['id']}", "status": "eq.active", "deleted_at": "is.null", "limit": "1",
        }, allow_legacy=True)
        if not products:
            raise _error(404, "VOUCHER_PRODUCT_NOT_FOUND", "판매 중인 식권 상품을 찾을 수 없어요")
        product = products[0]
        if not _is_exposed(product):
            raise _error(404, "VOUCHER_PRODUCT_NOT_EXPOSED", "현재 판매 기간이 아닌 식권 상품이에요")
        _require_classified_product(product)
        total_count = int(product["voucher_count"]) + int(product.get("bonus_count") or 0)
        gross_amount = krw_amount(product["sale_price"])
        if payload.requested_point_amount not in (None, 0):
            raise _error(422, "POINTS_NOT_AVAILABLE", "개인 식권 계정에는 포인트를 사용할 수 없어요")
        coupon = _selected_coupon(repo, merchant["id"], payload.coupon_id, payload.user_coupon_id, profile.id)
        quote = build_quote(
            gross_amount=gross_amount, coupon=coupon, requested_point_amount=0,
            available_point_amount=0, points_allowed=False,
        )
        amount = int(quote["payment_amount"])
        if amount <= 0:
            raise _error(400, "INVALID_AMOUNT", "결제 금액이 올바르지 않아요")
        order_id = f"GE-V-{uuid.uuid4().hex}"
        checkout_token = secrets.token_urlsafe(32)
        order = repo.client.rest_post("payment_orders", {
            "order_id": order_id, "checkout_token": checkout_token, "user_id": profile.id,
            "merchant_id": merchant["id"], "product_id": None, "voucher_product_id": product["id"],
            "merchant_name": merchant["name"], "product_name": product["name"], "amount": amount,
            "gross_amount": gross_amount, "coupon_id": coupon["id"] if coupon else None,
            "user_coupon_id": coupon.get("_user_coupon_id") if coupon else None,
            "coupon_discount_amount": int(quote["coupon_discount_amount"]),
            "coupon_snapshot": coupon_snapshot(coupon) if coupon else None,
            "requested_point_amount": 0,
            "status": "ready", "pay_type": "voucher", "voucher_count": total_count,
            "requested_payment_method": product.get("kiwoom_pay_method") or "TOTAL",
            "paid_voucher_count": int(product["voucher_count"]),
            "bonus_voucher_count": int(product.get("bonus_count") or 0),
            # Paid vouchers conserve the exact charged KRW; bonus vouchers carry zero purchase cost.
            "voucher_purchase_price": str(per_voucher_price(amount, int(product["voucher_count"]))),
        })[0]
        _reserve_issued_coupon(repo, order, coupon, profile.id, merchant["id"])
        return {"ok": True, "data": {
            "order_id": order_id, "amount": int(order["amount"]), "gross_amount": gross_amount,
            "coupon_id": coupon["id"] if coupon else None,
            "user_coupon_id": coupon.get("_user_coupon_id") if coupon else None,
            "coupon_discount_amount": int(quote["coupon_discount_amount"]),
            "point_amount": 0, "product_id": product["id"],
            "product_name": product["name"], "total_count": total_count,
            "checkout_url": f"{settings.public_api_base_url}/payments/checkout/{checkout_token}",
        }, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "식권 결제 주문을 만들지 못했어요") from exc
