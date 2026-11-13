"""Company-admin managed restaurant partnerships (D-17).

The company pays for its employees' meals, so the company admin decides which
restaurants its employees may use: it searches active restaurants (public
fields only), adds one, and can pause it again. Restaurants can no longer attach
themselves to an existing company (0073 removed /companies/link); a restaurant
only links companies it created and invited itself.
"""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.admin import _company_admin
from app.services.join_flow import JoinFlowError

router = APIRouter(prefix="/admin/company/merchants", tags=["company-merchants"])

# Never expose account, business number, phone, qr_token or view_token here.
PUBLIC_MERCHANT_FIELDS = "id,name,category,address,status"
_SEARCH_UNSAFE = re.compile(r"[,()*%\\]")


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _actor(repo: JoinRepository, token: str):
    try:
        return _company_admin(repo, token)
    except JoinFlowError as exc:
        raise _error(403, "FORBIDDEN", "회사관리자만 이용할 수 있어요") from exc


def _active_merchant(repo: JoinRepository, merchant_id: UUID) -> dict:
    rows = repo.client.rest_get("merchants", {
        "select": PUBLIC_MERCHANT_FIELDS, "id": f"eq.{merchant_id}", "status": "eq.active", "limit": "1",
    })
    if not rows:
        raise _error(404, "MERCHANT_NOT_FOUND", "식당을 찾을 수 없어요")
    return rows[0]


def _set_legacy(repo: JoinRepository, company_id: str, merchant_id: str, active: bool) -> None:
    # Legacy relation still read by older settlement/payment code.
    legacy = repo.client.rest_get("company_merchants", {
        "select": "company_id", "company_id": f"eq.{company_id}", "merchant_id": f"eq.{merchant_id}", "limit": "1",
    })
    if legacy:
        repo.client.rest_patch("company_merchants", {
            "company_id": f"eq.{company_id}", "merchant_id": f"eq.{merchant_id}",
        }, {"is_active": active})
    elif active:
        repo.client.rest_post("company_merchants", {"company_id": company_id, "merchant_id": merchant_id, "is_active": True})


@router.get("")
def list_company_merchants(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    actor = _actor(repo, token)
    try:
        links = repo.client.rest_get("merchant_companies", {
            "select": "merchant_id,status,unit_price,created_at",
            "company_id": f"eq.{actor.company_id}", "order": "created_at.asc",
        })
        ids = [str(link["merchant_id"]) for link in links]
        merchants = {str(row["id"]): row for row in repo.client.rest_get("merchants", {
            "select": PUBLIC_MERCHANT_FIELDS, "id": f"in.({','.join(ids)})",
        })} if ids else {}
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "이용 식당을 불러오지 못했어요") from exc
    items = []
    for link in links:
        merchant = merchants.get(str(link["merchant_id"]))
        if merchant is None:
            continue
        items.append({
            **merchant, "link_status": link["status"],
            "price_configured": bool(link.get("unit_price")), "linked_at": link.get("created_at"),
        })
    return {"ok": True, "data": {"items": items}, "error": None}


@router.get("/search")
def search_merchants(q: str = Query(min_length=1, max_length=40), token: str = Depends(bearer_token)):
    repo = JoinRepository()
    actor = _actor(repo, token)
    term = _SEARCH_UNSAFE.sub(" ", q).strip()
    if not term:
        return {"ok": True, "data": {"items": []}, "error": None}
    try:
        rows = repo.client.rest_get("merchants", {
            "select": PUBLIC_MERCHANT_FIELDS, "status": "eq.active",
            "name": f"ilike.*{term}*", "order": "name.asc", "limit": "20",
        })
        linked = {str(row["merchant_id"]): row["status"] for row in repo.client.rest_get("merchant_companies", {
            "select": "merchant_id,status", "company_id": f"eq.{actor.company_id}",
        })}
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "식당을 검색하지 못했어요") from exc
    return {"ok": True, "data": {"items": [
        {**row, "link_status": linked.get(str(row["id"]))} for row in rows
    ]}, "error": None}


@router.post("/{merchant_id}/link")
def link_merchant(merchant_id: UUID, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    actor = _actor(repo, token)
    try:
        merchant = _active_merchant(repo, merchant_id)
        existing = repo.client.rest_get("merchant_companies", {
            "select": "id,status", "merchant_id": f"eq.{merchant_id}", "company_id": f"eq.{actor.company_id}", "limit": "1",
        })
        if existing:
            if existing[0]["status"] != "active":
                repo.client.rest_patch("merchant_companies", {"id": f"eq.{existing[0]['id']}"}, {"status": "active"})
        else:
            repo.client.rest_post("merchant_companies", {
                "merchant_id": str(merchant_id), "company_id": actor.company_id,
                "status": "active", "created_by": actor.id,
            })
        _set_legacy(repo, str(actor.company_id), str(merchant_id), True)
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "식당을 추가하지 못했어요") from exc
    return {"ok": True, "data": {**merchant, "link_status": "active"}, "error": None}


@router.post("/{merchant_id}/pause")
def pause_merchant(merchant_id: UUID, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    actor = _actor(repo, token)
    try:
        updated = repo.client.rest_patch("merchant_companies", {
            "merchant_id": f"eq.{merchant_id}", "company_id": f"eq.{actor.company_id}",
        }, {"status": "paused"})
        if not updated:
            raise _error(404, "MERCHANT_LINK_NOT_FOUND", "이용 중인 식당이 아니에요")
        _set_legacy(repo, str(actor.company_id), str(merchant_id), False)
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "식당 이용을 중지하지 못했어요") from exc
    return {"ok": True, "data": {"merchant_id": str(merchant_id), "link_status": "paused"}, "error": None}
