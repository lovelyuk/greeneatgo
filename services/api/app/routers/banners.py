from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import AnyHttpUrl, BaseModel, Field, field_validator, model_validator

from app.auth import bearer_token, optional_bearer_token
from app.config import get_settings
from app.repositories.join_repository import JoinRepository
from app.routers.merchant_admin import _merchant_admin
from app.services.banner_images import BannerImageError, convert_banner_image
from app.services.join_flow import JoinFlowError
from app.services.vouchers import resolve_voucher_merchant

router = APIRouter(tags=["partner-banners"])
Placement = Literal["home_bottom", "event_page"]
_BANNER_SELECT = "id,merchant_id,partner_id,title,image_url,image_alt,link_url,open_mode,placement,sort_order,starts_at,ends_at,is_active,created_by,created_at,updated_at"
_REWARD_SELECT = "id,banner_id,merchant_id,reward_type,point_amount,coupon_id,coupon_valid_days,grant_policy,per_user_limit,total_budget,granted_total,is_active,created_at,updated_at"


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _admin(repo: JoinRepository, token: str):
    try:
        return _merchant_admin(repo, token)
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc


def _https(value):
    if value is not None and not str(value).startswith("https://"):
        raise ValueError("HTTPS URL required")
    return value


class PartnerPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    logo_url: AnyHttpUrl | None = None
    site_url: AnyHttpUrl
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    memo: str | None = None
    status: Literal["active", "paused", "ended"] = "active"
    model_config = {"extra": "forbid"}

    @field_validator("name", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("logo_url", "site_url")
    @classmethod
    def https_urls(cls, value):
        return _https(value)


class PartnerPatchPayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    logo_url: AnyHttpUrl | None = None
    site_url: AnyHttpUrl | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    memo: str | None = None
    status: Literal["active", "paused", "ended"] | None = None
    model_config = {"extra": "forbid"}

    @field_validator("logo_url", "site_url")
    @classmethod
    def https_urls(cls, value):
        return _https(value)


class RewardPayload(BaseModel):
    reward_type: Literal["none", "point", "coupon"] = "none"
    point_amount: int | None = Field(default=None, gt=0)
    coupon_id: uuid.UUID | None = None
    coupon_valid_days: int | None = Field(default=None, ge=1, le=3650)
    grant_policy: Literal["once", "daily", "unlimited"] = "once"
    per_user_limit: int | None = Field(default=None, gt=0)
    total_budget: int | None = Field(default=None, ge=0)
    is_active: bool = True
    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def valid_reward(self):
        if self.reward_type == "point" and (self.point_amount is None or self.coupon_id is not None):
            raise ValueError("point reward requires point_amount")
        if self.reward_type == "coupon" and (self.coupon_id is None or self.point_amount is not None):
            raise ValueError("coupon reward requires coupon_id")
        if self.reward_type == "none" and (self.point_amount is not None or self.coupon_id is not None):
            raise ValueError("none reward cannot contain a value")
        if self.grant_policy != "unlimited" and self.per_user_limit is not None:
            raise ValueError("per_user_limit is only valid for unlimited")
        return self


class BannerPayload(BaseModel):
    partner_id: uuid.UUID
    title: str = Field(min_length=1, max_length=160)
    image_url: AnyHttpUrl
    image_alt: str = Field(default="", max_length=300)
    link_url: AnyHttpUrl
    open_mode: Literal["webview", "external"] = "webview"
    placement: Placement = "home_bottom"
    sort_order: int = Field(default=0, ge=-100000, le=100000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool = True
    reward: RewardPayload = Field(default_factory=RewardPayload)
    model_config = {"extra": "forbid"}

    @field_validator("title", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("image_url", "link_url")
    @classmethod
    def https_urls(cls, value):
        return _https(value)

    @model_validator(mode="after")
    def period_valid(self):
        if (self.starts_at and self.starts_at.tzinfo is None) or (self.ends_at and self.ends_at.tzinfo is None):
            raise ValueError("banner datetimes require timezone")
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class BannerPatchPayload(BaseModel):
    partner_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=160)
    image_url: AnyHttpUrl | None = None
    image_alt: str | None = Field(default=None, max_length=300)
    link_url: AnyHttpUrl | None = None
    open_mode: Literal["webview", "external"] | None = None
    placement: Placement | None = None
    sort_order: int | None = Field(default=None, ge=-100000, le=100000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool | None = None
    reward: RewardPayload | None = None
    model_config = {"extra": "forbid"}

    @field_validator("image_url", "link_url")
    @classmethod
    def https_urls(cls, value):
        return _https(value)


class ReorderItem(BaseModel):
    id: uuid.UUID
    sort_order: int = Field(ge=-100000, le=100000)


class ReorderPayload(BaseModel):
    items: list[ReorderItem] = Field(min_length=1, max_length=200)
    model_config = {"extra": "forbid"}


class ImpressionItem(BaseModel):
    banner_id: uuid.UUID
    placement: Placement
    model_config = {"extra": "forbid"}


class ImpressionPayload(BaseModel):
    items: list[ImpressionItem] = Field(min_length=1, max_length=50)
    model_config = {"extra": "forbid"}


def _state(row: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if not row.get("is_active"):
        return "inactive"
    start = datetime.fromisoformat(str(row["starts_at"]).replace("Z", "+00:00")) if row.get("starts_at") else None
    end = datetime.fromisoformat(str(row["ends_at"]).replace("Z", "+00:00")) if row.get("ends_at") else None
    if start and now < start:
        return "scheduled"
    if end and now >= end:
        return "ended"
    return "live"


@router.get("/admin/partners")
def list_partners(token: str = Depends(bearer_token)):
    repo = JoinRepository(); _, merchant_id = _admin(repo, token)
    items = repo.client.rest_get("partners", {"select": "*", "merchant_id": f"eq.{merchant_id}", "order": "name.asc"})
    return {"ok": True, "data": {"items": items}, "error": None}


@router.post("/admin/partners", status_code=201)
def create_partner(payload: PartnerPayload, token: str = Depends(bearer_token)):
    repo = JoinRepository(); actor, merchant_id = _admin(repo, token)
    row = repo.client.rest_post("partners", {**payload.model_dump(mode="json"), "merchant_id": merchant_id, "created_by": actor.id})[0]
    return {"ok": True, "data": row, "error": None}


@router.patch("/admin/partners/{partner_id}")
def update_partner(partner_id: uuid.UUID, payload: PartnerPatchPayload, token: str = Depends(bearer_token)):
    repo = JoinRepository(); _, merchant_id = _admin(repo, token)
    values = payload.model_dump(mode="json", exclude_unset=True)
    if not values:
        raise _error(400, "EMPTY_PATCH", "변경할 값이 필요해요")
    rows = repo.client.rest_patch("partners", {"id": f"eq.{partner_id}", "merchant_id": f"eq.{merchant_id}"}, values)
    if not rows:
        raise _error(404, "PARTNER_NOT_FOUND", "파트너를 찾을 수 없어요")
    return {"ok": True, "data": rows[0], "error": None}


@router.delete("/admin/partners/{partner_id}")
def delete_partner(partner_id: uuid.UUID, token: str = Depends(bearer_token)):
    repo = JoinRepository(); _, merchant_id = _admin(repo, token)
    rows = repo.client.rest_delete("partners", {"id": f"eq.{partner_id}", "merchant_id": f"eq.{merchant_id}"})
    if not rows:
        raise _error(404, "PARTNER_NOT_FOUND", "파트너를 찾을 수 없어요")
    return {"ok": True, "data": {"deleted": True, "id": str(partner_id)}, "error": None}


def _admin_banner_rows(repo, merchant_id, banner_id: uuid.UUID | None = None, placement=None, partner_id=None, state=None):
    params = {"select": _BANNER_SELECT, "merchant_id": f"eq.{merchant_id}", "order": "sort_order.asc,id.asc"}
    if banner_id: params.update({"id": f"eq.{banner_id}", "limit": "1"})
    if placement: params["placement"] = f"eq.{placement}"
    if partner_id: params["partner_id"] = f"eq.{partner_id}"
    banners = repo.client.rest_get("partner_banners", params)
    ids = [row["id"] for row in banners]
    rewards = repo.client.rest_get("banner_rewards", {"select": _REWARD_SELECT, "banner_id": f"in.({','.join(ids)})"}) if ids else []
    reward_map = {row["banner_id"]: row for row in rewards}
    partner_ids = {row["partner_id"] for row in banners}
    partners = repo.client.rest_get("partners", {"select": "id,name,status", "id": f"in.({','.join(partner_ids)})", "merchant_id": f"eq.{merchant_id}"}) if partner_ids else []
    partner_map = {row["id"]: row for row in partners}
    stats = repo.client.rest_get("v_banner_stats_daily", {
        "select": "banner_id,impressions,clicks,grants,granted_units",
        "merchant_id": f"eq.{merchant_id}", "banner_id": f"in.({','.join(ids)})",
        "day": f"gte.{(datetime.now(ZoneInfo('Asia/Seoul')).date() - timedelta(days=29)).isoformat()}",
    }) if ids else []
    raw_summaries = {bid: {"impressions": 0, "clicks": 0, "grants": 0, "granted_units": 0} for bid in ids}
    for stat in stats:
        for key in raw_summaries[stat["banner_id"]]:
            raw_summaries[stat["banner_id"]][key] += int(stat.get(key) or 0)
    summaries = {
        bid: {
            "impressions": summary["impressions"],
            "clicks": summary["clicks"],
            "ctr": round(summary["clicks"] * 100 / summary["impressions"], 2)
            if summary["impressions"] else 0.0,
            "granted_count": summary["grants"],
            "granted_amount": summary["granted_units"],
        }
        for bid, summary in raw_summaries.items()
    }
    result = [{**row, "state": _state(row), "reward": reward_map.get(row["id"]),
               "partner": partner_map.get(row["partner_id"]),
               "partner_name": (partner_map.get(row["partner_id"]) or {}).get("name", ""),
               "stats": summaries[row["id"]]} for row in banners]
    return [row for row in result if state is None or row["state"] == state]


@router.get("/admin/banners")
def admin_banners(placement: Placement | None = None, partner_id: uuid.UUID | None = None, state: Literal["live", "scheduled", "ended", "inactive"] | None = None, token: str = Depends(bearer_token)):
    repo = JoinRepository(); _, merchant_id = _admin(repo, token)
    return {"ok": True, "data": {"items": _admin_banner_rows(repo, merchant_id, placement=placement, partner_id=partner_id, state=state)}, "error": None}


def _save(repo, actor, merchant_id, payload: BannerPayload, banner_id=None):
    values = payload.model_dump(mode="json", exclude={"reward"})
    return repo.client.rpc("save_partner_banner", {"p_actor_id": actor.id, "p_merchant_id": merchant_id, "p_banner_id": str(banner_id) if banner_id else None, "p_values": values, "p_reward": payload.reward.model_dump(mode="json")})


@router.post("/admin/banners", status_code=201)
def create_banner(payload: BannerPayload, token: str = Depends(bearer_token)):
    repo = JoinRepository(); actor, merchant_id = _admin(repo, token)
    return {"ok": True, "data": _save(repo, actor, merchant_id, payload), "error": None}


@router.patch("/admin/banners/reorder")
def reorder_banners(payload: ReorderPayload, token: str = Depends(bearer_token)):
    repo = JoinRepository(); actor, merchant_id = _admin(repo, token)
    data = repo.client.rpc("reorder_partner_banners", {
        "p_actor_id": actor.id, "p_merchant_id": merchant_id,
        "p_items": payload.model_dump(mode="json")["items"],
    })
    return {"ok": True, "data": data, "error": None}


@router.post("/admin/banners/upload-image", status_code=201)
async def upload_banner_image(partner_id: uuid.UUID = Form(...), placement: Placement = Form(...), image: UploadFile | None = File(None), file: UploadFile | None = File(None), token: str = Depends(bearer_token)):
    upload = image or file
    if upload is None:
        raise _error(400, "IMAGE_REQUIRED", "이미지 파일이 필요해요")
    repo = JoinRepository(); _, merchant_id = _admin(repo, token)
    partners = repo.client.rest_get("partners", {"select": "id", "id": f"eq.{partner_id}", "merchant_id": f"eq.{merchant_id}", "limit": "1"})
    if not partners:
        raise _error(404, "PARTNER_NOT_FOUND", "파트너를 찾을 수 없어요")
    raw = await upload.read(2 * 1024 * 1024 + 1)
    try:
        normalized = convert_banner_image(raw, upload.content_type, placement)
    except BannerImageError as exc:
        raise _error(400, str(exc), "배너 이미지 형식, 크기 또는 비율이 올바르지 않아요") from exc
    path = f"{partner_id}/{uuid.uuid4()}.webp"
    url = repo.client.upload_public_object("partner-banners", path, normalized, "image/webp")
    return {"ok": True, "data": {"url": url, "path": path}, "error": None}


@router.get("/admin/banners/{banner_id}/stats")
def banner_stats(banner_id: uuid.UUID, from_: date | None = Query(None, alias="from"), to: date | None = Query(None), token: str = Depends(bearer_token)):
    repo = JoinRepository(); _, merchant_id = _admin(repo, token)
    if not repo.client.rest_get("partner_banners", {"select": "id", "id": f"eq.{banner_id}", "merchant_id": f"eq.{merchant_id}", "limit": "1"}):
        raise _error(404, "BANNER_NOT_FOUND", "배너를 찾을 수 없어요")
    if from_ and to and to < from_:
        raise _error(422, "INVALID_DATE_RANGE", "종료일은 시작일보다 빠를 수 없어요")
    params = {"select": "day,impressions,clicks,grants,granted_units", "banner_id": f"eq.{banner_id}", "merchant_id": f"eq.{merchant_id}", "order": "day.asc"}
    if from_: params["day"] = f"gte.{from_.isoformat()}"
    if to: params["day"] = f"lte.{to.isoformat()}"
    raw_items = repo.client.rest_get("v_banner_stats_daily", params)
    items = []
    for row in raw_items:
        impressions = int(row.get("impressions") or 0)
        clicks = int(row.get("clicks") or 0)
        items.append({
            "day": row["day"],
            "impressions": impressions,
            "clicks": clicks,
            "ctr": round(clicks * 100 / impressions, 2) if impressions else 0.0,
            "granted_count": int(row.get("grants") or 0),
            "granted_amount": int(row.get("granted_units") or 0),
        })
    totals: dict[str, int | float] = {
        "impressions": sum(row["impressions"] for row in items),
        "clicks": sum(row["clicks"] for row in items),
        "granted_count": sum(row["granted_count"] for row in items),
        "granted_amount": sum(row["granted_amount"] for row in items),
    }
    totals["ctr"] = round(
        totals["clicks"] * 100 / totals["impressions"], 2
    ) if totals["impressions"] else 0.0
    return {"ok": True, "data": {"banner_id": str(banner_id), "items": items, "totals": totals}, "error": None}


@router.get("/admin/banners/{banner_id}")
def admin_banner(banner_id: uuid.UUID, token: str = Depends(bearer_token)):
    repo = JoinRepository(); _, merchant_id = _admin(repo, token)
    rows = _admin_banner_rows(repo, merchant_id, banner_id)
    if not rows:
        raise _error(404, "BANNER_NOT_FOUND", "배너를 찾을 수 없어요")
    return {"ok": True, "data": rows[0], "error": None}


@router.patch("/admin/banners/{banner_id}")
def patch_banner(banner_id: uuid.UUID, payload: BannerPatchPayload, token: str = Depends(bearer_token)):
    repo = JoinRepository(); actor, merchant_id = _admin(repo, token)
    current = _admin_banner_rows(repo, merchant_id, banner_id)
    if not current:
        raise _error(404, "BANNER_NOT_FOUND", "배너를 찾을 수 없어요")
    fields = ("partner_id", "title", "image_url", "image_alt", "link_url", "open_mode", "placement", "sort_order", "starts_at", "ends_at", "is_active")
    base = {key: current[0].get(key) for key in fields}
    changes = payload.model_dump(exclude_unset=True, mode="json")
    reward = changes.pop("reward", None) or current[0].get("reward") or {"reward_type": "none"}
    merged = BannerPayload.model_validate({**base, **changes, "reward": reward})
    return {"ok": True, "data": _save(repo, actor, merchant_id, merged, banner_id), "error": None}


@router.delete("/admin/banners/{banner_id}")
def delete_banner(banner_id: uuid.UUID, force: bool = Query(False), token: str = Depends(bearer_token)):
    repo = JoinRepository(); _, merchant_id = _admin(repo, token)
    if not force and repo.client.rest_get("banner_events", {"select": "id", "banner_id": f"eq.{banner_id}", "merchant_id": f"eq.{merchant_id}", "limit": "1"}):
        raise _error(409, "BANNER_HAS_HISTORY", "이력이 있는 배너는 force=true로만 삭제할 수 있어요")
    rows = repo.client.rest_delete("partner_banners", {"id": f"eq.{banner_id}", "merchant_id": f"eq.{merchant_id}"})
    if not rows:
        raise _error(404, "BANNER_NOT_FOUND", "배너를 찾을 수 없어요")
    return {"ok": True, "data": {"deleted": True, "id": str(banner_id)}, "error": None}


def _public_reward(reward, available):
    if not reward:
        return {"type": "none", "amount": None, "available": False, "label": ""}
    kind = reward["reward_type"]
    amount = int(reward["point_amount"]) if kind == "point" else None
    label = f"{amount:,}P 받기" if kind == "point" else ("쿠폰 받기" if kind == "coupon" else "")
    return {"type": kind, "amount": amount, "available": bool(available), "label": label}


@router.get("/banners")
def banners(response: Response, placement: Placement = Query(...), token: str | None = Depends(optional_bearer_token)):
    repo = JoinRepository(); profile = None
    if token is not None:
        auth = repo.auth_user_from_token(token); profile = repo.get_profile(auth.id, email=auth.email)
        if profile is None or profile.status != "active":
            raise _error(403, "ACCOUNT_INACTIVE", "활성 계정만 이용할 수 있어요")
    merchant = resolve_voucher_merchant(repo, get_settings().pilot_merchant_id)
    response.headers["Cache-Control"] = "private, max-age=60"
    if not merchant:
        return {"ok": True, "data": {"items": []}, "error": None}
    rows = repo.client.rest_get("partner_banners", {"select": _BANNER_SELECT, "merchant_id": f"eq.{merchant['id']}", "placement": f"eq.{placement}", "is_active": "eq.true", "order": "sort_order.asc,id.asc"})
    rows = [row for row in rows if _state(row) == "live"]
    ids = [row["id"] for row in rows]
    rewards = repo.client.rest_get("banner_rewards", {"select": _REWARD_SELECT, "banner_id": f"in.({','.join(ids)})", "is_active": "eq.true"}) if ids else []
    partners = repo.client.rest_get("partners", {"select": "id,name,status", "id": f"in.({','.join({row['partner_id'] for row in rows})})", "merchant_id": f"eq.{merchant['id']}", "status": "eq.active"}) if rows else []
    reward_map = {row["banner_id"]: row for row in rewards}; partner_map = {row["id"]: row["name"] for row in partners}
    rows = [row for row in rows if row["partner_id"] in partner_map]
    grants = []
    if profile and rewards:
        grants = repo.client.rest_get("banner_reward_grants", {"select": "reward_id,policy_key", "user_id": f"eq.{profile.id}", "reward_id": f"in.({','.join(str(row['id']) for row in rewards)})"})
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    items = []
    for row in rows:
        reward = reward_map.get(row["id"]); mine = [g for g in grants if reward and g["reward_id"] == reward["id"]]
        available = bool(profile and reward and reward["reward_type"] != "none")
        if available:
            available &= not (reward["reward_type"] == "point" and not getattr(profile, "company_id", None))
            units = int(reward.get("point_amount") or 1)
            available &= reward.get("total_budget") is None or int(reward.get("granted_total") or 0) + units <= int(reward["total_budget"])
            if reward["grant_policy"] == "once": available &= not mine
            elif reward["grant_policy"] == "daily": available &= not any(g["policy_key"] == today for g in mine)
            elif reward.get("per_user_limit"): available &= len(mine) < int(reward["per_user_limit"])
        # Deliberately withhold link_url until the click endpoint.
        items.append({key: row.get(key) for key in ("id", "title", "image_url", "image_alt", "open_mode", "placement", "sort_order", "starts_at", "ends_at") } | {"partner_name": partner_map.get(row["partner_id"], ""), "reward": _public_reward(reward, available)})
    return {"ok": True, "data": {"items": items}, "error": None}


@router.post("/banners/impressions", status_code=204)
def impressions(payload: ImpressionPayload, token: str | None = Depends(optional_bearer_token)):
    repo = JoinRepository(); user_id = None
    if token:
        auth = repo.auth_user_from_token(token); user_id = auth.id
    ids = [str(item.banner_id) for item in payload.items]
    live = repo.client.rest_get("partner_banners", {"select": "id,merchant_id,partner_id,placement,is_active,starts_at,ends_at", "id": f"in.({','.join(ids)})", "is_active": "eq.true"})
    partner_ids = {row["partner_id"] for row in live}
    active_partners = repo.client.rest_get("partners", {"select": "id", "id": f"in.({','.join(partner_ids)})", "status": "eq.active"}) if partner_ids else []
    active_partner_ids = {row["id"] for row in active_partners}
    row_map = {row["id"]: row for row in live if _state(row) == "live" and row["partner_id"] in active_partner_ids}
    if any(str(item.banner_id) not in row_map for item in payload.items):
        raise _error(410, "BANNER_NOT_AVAILABLE", "이 배너는 더 이상 이용할 수 없어요")
    if any(row_map[str(item.banner_id)]["placement"] != item.placement for item in payload.items):
        raise _error(422, "PLACEMENT_MISMATCH", "배너 노출 위치가 올바르지 않아요")
    events = [{"id": str(uuid.uuid4()), "banner_id": str(item.banner_id), "merchant_id": row_map[str(item.banner_id)]["merchant_id"], "user_id": user_id, "event_type": "impression"} for item in payload.items]
    if events:
        try: repo.client.rest_post("banner_events", events)
        except Exception: pass
    return Response(status_code=204)


@router.post("/banners/{banner_id}/click")
def click_banner(banner_id: uuid.UUID, token: str | None = Depends(optional_bearer_token)):
    repo = JoinRepository()
    rows = repo.client.rest_get("partner_banners", {"select": "id,merchant_id,partner_id,link_url,is_active,starts_at,ends_at", "id": f"eq.{banner_id}", "limit": "1"})
    if not rows or _state(rows[0]) != "live":
        raise _error(410, "BANNER_NOT_AVAILABLE", "이 배너는 더 이상 이용할 수 없어요")
    if not repo.client.rest_get("partners", {"select": "id", "id": f"eq.{rows[0]['partner_id']}", "merchant_id": f"eq.{rows[0]['merchant_id']}", "status": "eq.active", "limit": "1"}):
        raise _error(410, "BANNER_NOT_AVAILABLE", "이 배너는 더 이상 이용할 수 없어요")
    event_id = str(uuid.uuid4()); reward = {"granted": False, "reason": "anonymous"}
    if token is None:
        try: repo.client.rest_post("banner_events", {"id": event_id, "banner_id": str(banner_id), "merchant_id": rows[0]["merchant_id"], "event_type": "click"})
        except Exception: pass
    else:
        auth = repo.auth_user_from_token(token)
        try: reward = repo.client.rpc("grant_banner_reward", {"p_event_id": event_id, "p_banner_id": str(banner_id), "p_user_id": auth.id})
        except Exception: reward = {"granted": False, "reason": "error"}
    data = {"link_url": rows[0]["link_url"], "reward_granted": bool(reward.get("granted")), "reward_type": reward.get("reward_type"), "amount": reward.get("units"), "balance_after": reward.get("balance_after"), "user_coupon_id": reward.get("user_coupon_id"), "reason": reward.get("reason")}
    return {"ok": True, "data": data, "error": None}
