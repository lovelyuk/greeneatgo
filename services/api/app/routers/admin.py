from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.products import FALLBACK_DAILY_MENU, FALLBACK_PRODUCTS, today_kst
from app.schemas import DailyMenuUpsertRequest, JoinDecisionRequest, ProductCreateRequest, ProductUpdateRequest
from app.services.join_flow import JoinFlowError

router = APIRouter(prefix="/admin", tags=["admin"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _handle_join_error(exc: JoinFlowError) -> HTTPException:
    status = 403 if str(exc.code) == "FORBIDDEN" else 400
    return _error(status, str(exc.code), exc.message)


@router.get("/join-requests")
def list_join_requests(token: str = Depends(bearer_token)):
    try:
        rows = JoinRepository().list_pending_join_requests(actor_token=token)
        return {"ok": True, "data": {"items": rows}, "error": None}
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "Supabase 처리 중 오류가 발생했어요") from exc


@router.post("/join-requests/{user_id}/approve")
def approve_join_request(user_id: str, _: JoinDecisionRequest | None = None, token: str = Depends(bearer_token)):
    try:
        row = JoinRepository().approve(actor_token=token, user_id=user_id)
        return {"ok": True, "data": row, "error": None}
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "Supabase 처리 중 오류가 발생했어요") from exc


@router.post("/join-requests/{user_id}/reject")
def reject_join_request(user_id: str, payload: JoinDecisionRequest, token: str = Depends(bearer_token)):
    if not payload.reason:
        raise _error(400, "REASON_REQUIRED", "거절 사유를 입력해 주세요")
    try:
        row = JoinRepository().reject(actor_token=token, user_id=user_id, reason=payload.reason)
        return {"ok": True, "data": row, "error": None}
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "Supabase 처리 중 오류가 발생했어요") from exc


@router.get("/settlements")
def list_settlements(ym: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"), token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor_auth = repo.auth_user_from_token(token)
        actor = repo.get_profile(actor_auth.id, email=actor_auth.email)
        if actor is None or actor.role != "company_admin" or actor.status != "active" or not actor.company_id:
            raise JoinFlowError("FORBIDDEN", "회사관리자만 조회할 수 있어요")

        period_ym = ym or datetime.now().strftime("%Y-%m")
        rows = repo.client.rest_get(
            "settlements",
            {
                "select": "id,company_id,merchant_id,period_ym,tx_count,total_amount,status,paid_at",
                "company_id": f"eq.{actor.company_id}",
                "period_ym": f"eq.{period_ym}",
                "order": "status.asc",
            },
        )
        total_amount = sum(int(row.get("total_amount") or 0) for row in rows)
        tx_count = sum(int(row.get("tx_count") or 0) for row in rows)
        paid_count = sum(1 for row in rows if row.get("status") == "paid")
        return {
            "ok": True,
            "data": {
                "period_ym": period_ym,
                "single_merchant": True,
                "items": rows,
                "summary": {
                    "settlement_count": len(rows),
                    "paid_count": paid_count,
                    "tx_count": tx_count,
                    "total_amount": total_amount,
                },
            },
            "error": None,
        }
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "정산 데이터를 불러오는 중 오류가 발생했어요") from exc


def _active_admin(repo: JoinRepository, token: str):
    actor_auth = repo.auth_user_from_token(token)
    actor = repo.get_profile(actor_auth.id, email=actor_auth.email)
    if actor is None or actor.role != "company_admin" or actor.status != "active" or not actor.company_id:
        raise JoinFlowError("FORBIDDEN", "회사관리자만 이용할 수 있어요")
    return actor


def _admin_merchant(repo: JoinRepository, company_id: str) -> dict:
    links = repo.client.rest_get(
        "company_merchants",
        {"select": "merchant_id", "company_id": f"eq.{company_id}", "is_active": "eq.true", "limit": "1"},
    )
    if not links:
        raise JoinFlowError("MERCHANT_NOT_FOUND", "운영 식당이 아직 연결되지 않았어요")
    merchants = repo.client.rest_get(
        "merchants",
        {"select": "id,name,category,avg_price,qr_token", "id": f"eq.{links[0]['merchant_id']}", "limit": "1"},
    )
    if not merchants:
        raise JoinFlowError("MERCHANT_NOT_FOUND", "운영 식당을 찾을 수 없어요")
    return merchants[0]


def _ensure_product_belongs(repo: JoinRepository, product_id: str, merchant_id: str) -> dict:
    rows = repo.client.rest_get(
        "merchant_products",
        {"select": "*", "id": f"eq.{product_id}", "merchant_id": f"eq.{merchant_id}", "limit": "1"},
    )
    if not rows:
        raise JoinFlowError("PRODUCT_NOT_FOUND", "상품을 찾을 수 없어요")
    return rows[0]


@router.get("/products")
def list_products(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _active_admin(repo, token)
        merchant = _admin_merchant(repo, actor.company_id)
        try:
            rows = repo.client.rest_get(
                "merchant_products",
                {
                    "select": "id,merchant_id,name,price,category,image_url,is_active,sort_order,created_at,updated_at",
                    "merchant_id": f"eq.{merchant['id']}",
                    "order": "sort_order.asc,created_at.asc",
                },
            )
            migration_required = False
        except SupabaseHttpError as exc:
            if "PGRST205" not in exc.body:
                raise
            rows = [{**item, "merchant_id": merchant["id"]} for item in FALLBACK_PRODUCTS]
            migration_required = True
        return {"ok": True, "data": {"merchant": merchant, "items": rows, "migration_required": migration_required}, "error": None}
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "상품 데이터를 불러오는 중 오류가 발생했어요") from exc


@router.post("/products")
def create_product(payload: ProductCreateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _active_admin(repo, token)
        merchant = _admin_merchant(repo, actor.company_id)
        row = repo.client.rest_post("merchant_products", {
            "merchant_id": merchant["id"],
            "name": payload.name,
            "price": payload.price,
            "category": payload.category,
            "image_url": payload.image_url,
            "is_active": payload.is_active,
            "sort_order": payload.sort_order,
        })[0]
        return {"ok": True, "data": row, "error": None}
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "상품을 저장하는 중 오류가 발생했어요") from exc


@router.patch("/products/{product_id}")
def update_product(product_id: str, payload: ProductUpdateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _active_admin(repo, token)
        merchant = _admin_merchant(repo, actor.company_id)
        _ensure_product_belongs(repo, product_id, merchant["id"])
        values = {key: value for key, value in payload.model_dump().items() if value is not None}
        if not values:
            raise _error(400, "NO_CHANGES", "수정할 값을 입력해 주세요")
        values["updated_at"] = datetime.now().isoformat()
        row = repo.client.rest_patch("merchant_products", {"id": f"eq.{product_id}"}, values)[0]
        return {"ok": True, "data": row, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "상품을 수정하는 중 오류가 발생했어요") from exc


@router.get("/daily-menu")
def get_daily_menu(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _active_admin(repo, token)
        merchant = _admin_merchant(repo, actor.company_id)
        try:
            rows = repo.client.rest_get(
                "merchant_daily_menus",
                {
                    "select": "id,merchant_id,service_date,title,menu_text,is_active,updated_at",
                    "merchant_id": f"eq.{merchant['id']}",
                    "service_date": f"eq.{today_kst()}",
                    "limit": "1",
                },
            )
            menu = rows[0] if rows else None
            migration_required = False
        except SupabaseHttpError as exc:
            if "PGRST205" not in exc.body:
                raise
            menu = FALLBACK_DAILY_MENU
            migration_required = True
        return {"ok": True, "data": {"merchant": merchant, "today_menu": menu, "service_date": today_kst(), "migration_required": migration_required}, "error": None}
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "오늘 메뉴를 불러오는 중 오류가 발생했어요") from exc


@router.put("/daily-menu")
def upsert_daily_menu(payload: DailyMenuUpsertRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _active_admin(repo, token)
        merchant = _admin_merchant(repo, actor.company_id)
        service_date = today_kst()
        existing = repo.client.rest_get(
            "merchant_daily_menus",
            {"select": "id", "merchant_id": f"eq.{merchant['id']}", "service_date": f"eq.{service_date}", "limit": "1"},
        )
        values = {
            "merchant_id": merchant["id"],
            "service_date": service_date,
            "title": payload.title,
            "menu_text": payload.menu_text,
            "is_active": payload.is_active,
            "updated_at": datetime.now().isoformat(),
        }
        if existing:
            row = repo.client.rest_patch("merchant_daily_menus", {"id": f"eq.{existing[0]['id']}"}, values)[0]
        else:
            row = repo.client.rest_post("merchant_daily_menus", values)[0]
        return {"ok": True, "data": row, "error": None}
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0006_merchant_daily_menus.sql 적용 후 오늘 메뉴를 저장할 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "오늘 메뉴를 저장하는 중 오류가 발생했어요") from exc
