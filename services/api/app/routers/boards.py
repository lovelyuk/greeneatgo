from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from PIL import Image, ImageOps
from pydantic import BaseModel, Field, field_validator

from app.auth import bearer_token
from app.config import get_settings
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.merchant_admin import _merchant_admin
from app.routers.push_notifications import _audience
from app.services.push_notifications import send_push_notifications
from app.services.vouchers import resolve_voucher_merchant

router = APIRouter(tags=["boards"])


def error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=5000)
    pinned: bool = False
    send_push: bool = False

    @field_validator("title", "content")
    @classmethod
    def trimmed(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("공백만 입력할 수 없어요")
        return value.strip()


class AnnouncementUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=120)
    content: str | None = Field(None, min_length=1, max_length=5000)
    pinned: bool | None = None
    status: Literal["published", "hidden"] | None = None


class ReviewCreate(BaseModel):
    transaction_id: int
    rating: int = Field(ge=1, le=5)
    content: str | None = Field(default=None, max_length=2000)
    image_urls: list[str] = Field(default_factory=list, max_length=3)


class ReviewUpdate(BaseModel):
    status: Literal["visible", "hidden"] | None = None
    owner_reply: str | None = Field(None, max_length=2000)


def _customer(repo: JoinRepository, token: str):
    auth = repo.auth_user_from_token(token)
    profile = repo.get_profile(auth.id, email=auth.email)
    if profile is None or profile.status != "active" or profile.role not in {"customer", "employee"}:
        raise error(403, "CUSTOMER_ONLY", "활성 사용자만 이용할 수 있어요")
    return profile


def _pilot_merchant(repo: JoinRepository) -> dict:
    merchant = resolve_voucher_merchant(repo, get_settings().pilot_merchant_id)
    if not merchant:
        raise error(404, "MERCHANT_NOT_FOUND", "식당을 찾을 수 없어요")
    return merchant


def _mask(name: str | None) -> str:
    value = (name or "사용자").strip()
    if len(value) == 1:
        return f"{value}*님"
    if len(value) == 2:
        return f"{value[0]}*님"
    return f"{value[0]}{'*' * (len(value)-2)}{value[-1]}님"


def _decorate_reviews(repo: JoinRepository, rows: list[dict]) -> list[dict]:
    ids = sorted({str(row["account_id"]) for row in rows})
    names: dict[str, str] = {}
    if ids:
        users = repo.client.rest_get("app_users", {"select": "id,display_name", "id": f"in.({','.join(ids)})"})
        names = {str(user["id"]): user.get("display_name") or "사용자" for user in users}
    return [{**row, "author_name": _mask(names.get(str(row["account_id"]))), "account_id": None} for row in rows]


@router.get("/admin/announcements")
def admin_announcements(token: str = Depends(bearer_token)):
    repo = JoinRepository(); _, merchant_id = _merchant_admin(repo, token)
    rows = repo.client.rest_get("announcements", {"select": "*", "merchant_id": f"eq.{merchant_id}", "order": "pinned.desc,created_at.desc"})
    return {"ok": True, "data": {"items": rows}, "error": None}


@router.post("/admin/announcements", status_code=201)
def create_announcement(payload: AnnouncementCreate, token: str = Depends(bearer_token)):
    repo = JoinRepository(); actor, merchant_id = _merchant_admin(repo, token)
    row = repo.client.rest_post("announcements", {**payload.model_dump(), "merchant_id": merchant_id, "created_by": actor.id})[0]
    push = None
    if payload.send_push:
        audience = _audience(repo, "all")
        targets = audience["targets"]
        if targets:
            result = send_push_notifications(title=payload.title, body=(payload.content[:50] + ("..." if len(payload.content) > 50 else "")), targets=targets)
            push = {"target_count": result.target_count, "success_count": result.success_count, "failure_device_count": result.failure_device_count}
    return {"ok": True, "data": {"announcement": row, "push": push}, "error": None}


@router.patch("/admin/announcements/{announcement_id}")
def update_announcement(announcement_id: str, payload: AnnouncementUpdate, token: str = Depends(bearer_token)):
    repo = JoinRepository(); _, merchant_id = _merchant_admin(repo, token)
    values = payload.model_dump(exclude_unset=True)
    for key in ("title", "content"):
        if key in values:
            values[key] = values[key].strip()
            if not values[key]: raise error(422, "EMPTY_CONTENT", "공백만 입력할 수 없어요")
    values["updated_at"] = datetime.now(timezone.utc).isoformat()
    rows = repo.client.rest_patch("announcements", {"id": f"eq.{announcement_id}", "merchant_id": f"eq.{merchant_id}"}, values)
    if not rows: raise error(404, "ANNOUNCEMENT_NOT_FOUND", "공지를 찾을 수 없어요")
    return {"ok": True, "data": rows[0], "error": None}


@router.get("/announcements")
def announcements():
    repo = JoinRepository(); merchant = _pilot_merchant(repo)
    rows = repo.client.rest_get("announcements", {"select": "id,title,content,pinned,created_at,updated_at", "merchant_id": f"eq.{merchant['id']}", "status": "eq.published", "order": "pinned.desc,created_at.desc"})
    return {"ok": True, "data": {"items": rows}, "error": None}


@router.get("/vouchers/reviewable-transactions")
def reviewable_transactions(token: str = Depends(bearer_token)):
    repo = JoinRepository(); profile = _customer(repo, token); merchant = _pilot_merchant(repo)
    txs = repo.client.rest_get("meal_transactions", {"select": "id,merchant_id,amount,kind,created_at", "user_id": f"eq.{profile.id}", "merchant_id": f"eq.{merchant['id']}", "kind": "eq.spend", "order": "created_at.desc"})
    if not txs: return {"ok": True, "data": {"items": []}, "error": None}
    reviews = repo.client.rest_get("reviews", {"select": "transaction_id", "transaction_id": f"in.({','.join(str(t['id']) for t in txs)})"})
    reviewed = {int(row["transaction_id"]) for row in reviews}
    return {"ok": True, "data": {"items": [t for t in txs if int(t["id"]) not in reviewed]}, "error": None}


@router.post("/reviews", status_code=201)
def create_review(payload: ReviewCreate, token: str = Depends(bearer_token)):
    repo = JoinRepository(); profile = _customer(repo, token)
    txs = repo.client.rest_get("meal_transactions", {"select": "id,user_id,merchant_id,kind", "id": f"eq.{payload.transaction_id}", "limit": "1"})
    if not txs or txs[0].get("user_id") != profile.id: raise error(403, "TRANSACTION_NOT_OWNED", "본인의 이용 내역만 리뷰할 수 있어요")
    tx = txs[0]
    if tx.get("kind") != "spend" or not tx.get("merchant_id"): raise error(422, "TRANSACTION_NOT_COMPLETED", "이용 완료된 거래만 리뷰할 수 있어요")
    allowed_prefix = f"{repo.client.settings.supabase_url.rstrip('/')}/storage/v1/object/public/review-images/{tx['merchant_id']}/{profile.id}/"
    if any(not url.startswith(allowed_prefix) for url in payload.image_urls): raise error(422, "INVALID_REVIEW_IMAGE", "본인이 업로드한 리뷰 이미지만 사용할 수 있어요")
    try:
        row = repo.client.rest_post("reviews", {**payload.model_dump(), "merchant_id": tx["merchant_id"], "account_id": profile.id, "status": "visible"})[0]
    except SupabaseHttpError as exc:
        if "23505" in exc.body: raise error(409, "REVIEW_ALREADY_EXISTS", "이미 리뷰를 작성하셨어요") from exc
        raise
    return {"ok": True, "data": _decorate_reviews(repo, [row])[0], "error": None}


@router.post("/reviews/images", status_code=201)
async def upload_review_image(file: UploadFile = File(...), token: str = Depends(bearer_token)):
    repo = JoinRepository(); profile = _customer(repo, token); merchant = _pilot_merchant(repo)
    raw = await file.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024: raise error(400, "IMAGE_TOO_LARGE", "원본 이미지는 10MB 이하여야 해요")
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
        image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        quality = 88
        while True:
            output = io.BytesIO(); image.save(output, "WEBP", quality=quality, method=6)
            if output.tell() <= 500 * 1024 or quality <= 45: break
            quality -= 8
    except Exception as exc: raise error(400, "INVALID_IMAGE", "올바른 이미지 파일을 선택해 주세요") from exc
    if output.tell() > 500 * 1024: raise error(400, "IMAGE_TOO_LARGE", "이미지를 500KB 이하로 변환할 수 없어요")
    path = f"{merchant['id']}/{profile.id}/{uuid.uuid4().hex}.webp"
    url = repo.client.upload_public_object("review-images", path, output.getvalue(), "image/webp")
    return {"ok": True, "data": {"image_url": url}, "error": None}


@router.get("/reviews")
def reviews():
    repo = JoinRepository(); merchant = _pilot_merchant(repo)
    rows = repo.client.rest_get("reviews", {"select": "id,account_id,rating,content,image_urls,owner_reply,owner_reply_at,created_at", "merchant_id": f"eq.{merchant['id']}", "status": "eq.visible", "order": "created_at.desc"})
    items = _decorate_reviews(repo, rows)
    average = round(sum(int(r["rating"]) for r in rows) / len(rows), 1) if rows else 0.0
    return {"ok": True, "data": {"items": items, "average_rating": average, "review_count": len(rows)}, "error": None}


@router.get("/admin/reviews")
def admin_reviews(sort: Literal["latest", "rating_asc"] = "latest", token: str = Depends(bearer_token)):
    repo = JoinRepository(); _, merchant_id = _merchant_admin(repo, token)
    order = "rating.asc,created_at.desc" if sort == "rating_asc" else "created_at.desc"
    rows = repo.client.rest_get("reviews", {"select": "*", "merchant_id": f"eq.{merchant_id}", "order": order})
    visible = [r for r in rows if r["status"] == "visible"]
    average = round(sum(int(r["rating"]) for r in visible) / len(visible), 1) if visible else 0.0
    return {"ok": True, "data": {"items": _decorate_reviews(repo, rows), "average_rating": average, "review_count": len(visible)}, "error": None}


@router.patch("/admin/reviews/{review_id}")
def update_review(review_id: str, payload: ReviewUpdate, token: str = Depends(bearer_token)):
    repo = JoinRepository(); _, merchant_id = _merchant_admin(repo, token); values = payload.model_dump(exclude_unset=True)
    if "owner_reply" in values:
        values["owner_reply"] = values["owner_reply"].strip() or None if values["owner_reply"] is not None else None
        values["owner_reply_at"] = datetime.now(timezone.utc).isoformat() if values["owner_reply"] else None
    values["updated_at"] = datetime.now(timezone.utc).isoformat()
    rows = repo.client.rest_patch("reviews", {"id": f"eq.{review_id}", "merchant_id": f"eq.{merchant_id}"}, values)
    if not rows: raise error(404, "REVIEW_NOT_FOUND", "리뷰를 찾을 수 없어요")
    return {"ok": True, "data": _decorate_reviews(repo, rows)[0], "error": None}
