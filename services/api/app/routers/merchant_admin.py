from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.schemas import MerchantCompanyCreateAndLinkRequest, MerchantCompanyLinkRequest
from app.services.join_flow import JoinFlowError

router = APIRouter(prefix="/admin/merchant", tags=["merchant-admin"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _token() -> str:
    return secrets.token_urlsafe(32)


def _merchant_admin(repo: JoinRepository, token: str):
    auth = repo.auth_user_from_token(token)
    actor = repo.get_profile(auth.id, email=auth.email)
    if actor is None or actor.role != "merchant_admin" or actor.status != "active":
        raise JoinFlowError("FORBIDDEN", "식당관리자만 이용할 수 있어요")
    merchant_id = actor.merchant_id
    if not merchant_id:
        legacy = repo.client.rest_get("merchant_admins", {"select": "merchant_id", "user_id": f"eq.{actor.id}", "limit": "1"})
        merchant_id = legacy[0]["merchant_id"] if legacy else None
    if not merchant_id:
        raise JoinFlowError("MERCHANT_NOT_FOUND", "연결된 식당이 없어요")
    return actor, merchant_id


def _company_rows(repo: JoinRepository, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    return repo.client.rest_get("companies", {"select": "id,name,biz_reg_no,status,created_at", "id": f"in.({','.join(ids)})"})


def _upsert_link(repo: JoinRepository, merchant_id: str, company_id: str, actor_id: str) -> dict:
    existing = repo.client.rest_get(
        "merchant_companies",
        {"select": "*", "merchant_id": f"eq.{merchant_id}", "company_id": f"eq.{company_id}", "limit": "1"},
    )
    if existing:
        return repo.client.rest_patch("merchant_companies", {"id": f"eq.{existing[0]['id']}"}, {"status": "active"})[0]
    link = repo.client.rest_post("merchant_companies", {
        "merchant_id": merchant_id,
        "company_id": company_id,
        "status": "active",
        "created_by": actor_id,
    })[0]
    # Maintain the legacy relation for existing settlement/payment code.
    legacy = repo.client.rest_get(
        "company_merchants",
        {"select": "company_id,merchant_id", "company_id": f"eq.{company_id}", "merchant_id": f"eq.{merchant_id}", "limit": "1"},
    )
    if not legacy:
        repo.client.rest_post("company_merchants", {"company_id": company_id, "merchant_id": merchant_id, "is_active": True})
    return link


@router.get("/companies/search")
def search_companies(q: str = Query(min_length=1, max_length=80), token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _merchant_admin(repo, token)
        rows = repo.client.rest_get(
            "companies",
            {"select": "id,name,biz_reg_no,status,created_at", "name": f"ilike.*{q}*", "order": "name.asc", "limit": "20"},
        )
        return {"ok": True, "data": {"items": rows}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "회사 검색 중 오류가 발생했어요") from exc


@router.get("/companies")
def list_companies(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        links = repo.client.rest_get(
            "merchant_companies",
            {"select": "id,merchant_id,company_id,status,created_at", "merchant_id": f"eq.{merchant_id}", "order": "created_at.desc"},
        )
        companies = {row["id"]: row for row in _company_rows(repo, [link["company_id"] for link in links])}
        items = [{**link, "company": companies.get(link["company_id"])} for link in links]
        return {"ok": True, "data": {"items": items}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0008_mealledger_v23.sql 적용 후 장부업체를 관리할 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "장부업체 목록을 불러오는 중 오류가 발생했어요") from exc


@router.post("/companies/link")
def link_company(payload: MerchantCompanyLinkRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor, merchant_id = _merchant_admin(repo, token)
        companies = repo.client.rest_get("companies", {"select": "id,name,status", "id": f"eq.{payload.company_id}", "limit": "1"})
        if not companies:
            raise JoinFlowError("COMPANY_NOT_FOUND", "회사를 찾을 수 없어요")
        link = _upsert_link(repo, merchant_id, payload.company_id, actor.id)
        return {"ok": True, "data": {"link": link, "company": companies[0]}, "error": None}
    except JoinFlowError as exc:
        status = 404 if str(exc.code) == "COMPANY_NOT_FOUND" else 403
        raise _error(status, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0008_mealledger_v23.sql 적용 후 장부업체를 연결할 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "장부업체 연결 중 오류가 발생했어요") from exc


@router.post("/companies/create-and-link")
def create_and_link_company(payload: MerchantCompanyCreateAndLinkRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor, merchant_id = _merchant_admin(repo, token)
        company = repo.client.rest_post("companies", {"name": payload.name, "status": "invited"})[0]
        link = _upsert_link(repo, merchant_id, company["id"], actor.id)
        invite = repo.client.rest_post("invites", {
            "token": _token(),
            "role": "company_admin",
            "company_id": company["id"],
            "phone": payload.owner_phone,
            "invited_by": actor.id,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        })[0]
        return {"ok": True, "data": {"company": company, "link": link, "invite": {**invite, "delivery": "manual"}}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0008_mealledger_v23.sql 적용 후 장부업체를 만들 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "장부업체 생성 중 오류가 발생했어요") from exc


@router.get("/transactions")
def list_transactions(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        rows = repo.client.rest_get(
            "meal_transactions",
            {
                "select": "id,user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,flags,product_name,product_price,created_at",
                "merchant_id": f"eq.{merchant_id}",
                "order": "created_at.desc",
                "limit": "50",
            },
        )
        return {"ok": True, "data": {"items": rows}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "거래내역을 불러오는 중 오류가 발생했어요") from exc
