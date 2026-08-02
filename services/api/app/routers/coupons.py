from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from app.auth import bearer_token
from app.config import get_settings
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.merchant_admin import _merchant_admin
from app.services.coupon_pricing import coupon_is_valid
from app.services.join_flow import JoinFlowError
from app.services.vouchers import resolve_voucher_merchant

router = APIRouter(tags=["merchant-coupons"])
_COUPON_SELECT = "id,merchant_id,name,discount_type,discount_value,valid_from,valid_until,is_active,created_at,updated_at"


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


class CouponCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    discount_type: Literal["percent", "fixed"]
    discount_value: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    valid_from: date | None = None
    valid_until: date | None = None
    is_active: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_policy(self):
        if self.discount_type == "percent" and self.discount_value >= 100:
            raise ValueError("할인쿠폰은 100% 미만으로 설정해 주세요")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("종료일은 시작일보다 빠를 수 없어요")
        return self

    model_config = {"extra": "forbid"}


class CouponUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    discount_type: Literal["percent", "fixed"] | None = None
    discount_value: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    valid_from: date | None = None
    valid_until: date | None = None
    is_active: bool | None = None

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("name", "discount_type", "discount_value", "is_active", mode="before")
    @classmethod
    def reject_required_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("필드는 null일 수 없어요")
        return value

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("변경할 쿠폰 정보를 입력해 주세요")
        return self

    model_config = {"extra": "forbid"}


def _coupon_payload(model: CouponCreateRequest) -> dict:
    return model.model_dump(mode="json")


def _migration_missing(exc: SupabaseHttpError) -> bool:
    body = exc.body.lower()
    return "merchant_coupons" in body and ("pgrst205" in body or "does not exist" in body or "schema cache" in body)


def _supabase_error(exc: SupabaseHttpError, message: str) -> HTTPException:
    if exc.status in (401, 403):
        return _error(401, "UNAUTHENTICATED", "로그인 정보가 올바르지 않아요")
    if _migration_missing(exc):
        return _error(503, "MIGRATION_REQUIRED", "0055 마이그레이션 적용이 필요해요")
    return _error(502, "SUPABASE_ERROR", message)


@router.get("/coupons")
def customer_coupons(token: str = Depends(bearer_token)):
    """List reusable, currently valid promotions for the pilot merchant."""
    repo = JoinRepository()
    try:
        auth = repo.auth_user_from_token(token)
        profile = repo.get_profile(auth.id, email=auth.email)
        if profile is None or profile.status != "active" or profile.role not in {"customer", "employee"}:
            raise _error(403, "VOUCHER_ACCOUNT_ONLY", "식권 계정만 쿠폰을 조회할 수 있어요")
        merchant = resolve_voucher_merchant(repo, get_settings().pilot_merchant_id)
        if not merchant:
            return {"ok": True, "data": {"merchant": None, "items": []}, "error": None}
        rows = repo.client.rest_get("merchant_coupons", {
            "select": _COUPON_SELECT,
            "merchant_id": f"eq.{merchant['id']}",
            "is_active": "eq.true",
            "order": "created_at.desc",
        })
        return {"ok": True, "data": {
            "merchant": {"id": merchant["id"], "name": merchant["name"]},
            "items": [row for row in rows if coupon_is_valid(row)],
        }, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        raise _supabase_error(exc, "쿠폰을 불러오지 못했어요") from exc


@router.get("/admin/coupons")
def admin_coupons(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        rows = repo.client.rest_get("merchant_coupons", {
            "select": _COUPON_SELECT,
            "merchant_id": f"eq.{merchant_id}",
            "order": "created_at.desc",
        })
        return {"ok": True, "data": {"items": rows, "migration_required": False}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        if _migration_missing(exc):
            return {"ok": True, "data": {"items": [], "migration_required": True}, "error": None}
        raise _supabase_error(exc, "쿠폰을 불러오지 못했어요") from exc


@router.post("/admin/coupons", status_code=201)
def create_coupon(payload: CouponCreateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor, merchant_id = _merchant_admin(repo, token)
        row = repo.client.rest_post("merchant_coupons", {
            **_coupon_payload(payload),
            "merchant_id": merchant_id,
            "created_by": actor.id,
        })[0]
        return {"ok": True, "data": row, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _supabase_error(exc, "쿠폰을 저장하지 못했어요") from exc


@router.patch("/admin/coupons/{coupon_id}")
def update_coupon(coupon_id: str, payload: CouponUpdateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        current = repo.client.rest_get("merchant_coupons", {
            "select": _COUPON_SELECT,
            "id": f"eq.{coupon_id}",
            "merchant_id": f"eq.{merchant_id}",
            "limit": "1",
        })
        if not current:
            raise _error(404, "COUPON_NOT_FOUND", "쿠폰을 찾을 수 없어요")
        values = payload.model_dump(exclude_unset=True, mode="json")
        merged = {**current[0], **values}
        validated = CouponCreateRequest.model_validate({
            key: merged.get(key)
            for key in ("name", "discount_type", "discount_value", "valid_from", "valid_until", "is_active")
        })
        values = {key: value for key, value in _coupon_payload(validated).items() if key in payload.model_fields_set}
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        rows = repo.client.rest_patch("merchant_coupons", {
            "id": f"eq.{coupon_id}",
            "merchant_id": f"eq.{merchant_id}",
        }, values)
        if not rows:
            raise _error(404, "COUPON_NOT_FOUND", "쿠폰을 찾을 수 없어요")
        return {"ok": True, "data": rows[0], "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _supabase_error(exc, "쿠폰을 수정하지 못했어요") from exc


@router.delete("/admin/coupons/{coupon_id}")
def delete_coupon(coupon_id: str, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        rows = repo.client.rest_delete("merchant_coupons", {
            "id": f"eq.{coupon_id}",
            "merchant_id": f"eq.{merchant_id}",
        })
        if not rows:
            raise _error(404, "COUPON_NOT_FOUND", "쿠폰을 찾을 수 없어요")
        return {"ok": True, "data": {"deleted": True, "id": coupon_id}, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _supabase_error(exc, "쿠폰을 삭제하지 못했어요") from exc
