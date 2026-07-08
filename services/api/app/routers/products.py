from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from app.repositories.supabase_http import SupabaseHttpClient, SupabaseHttpError

router = APIRouter(tags=["products"])

FALLBACK_PRODUCTS = [
    {"id": "fallback-kimchi", "name": "든든 김치찌개", "price": 9000, "category": "한식", "image_url": None, "is_active": True, "sort_order": 1},
    {"id": "fallback-pork", "name": "제육 도시락", "price": 9500, "category": "도시락", "image_url": None, "is_active": True, "sort_order": 2},
    {"id": "fallback-salad", "name": "닭가슴살 샐러드", "price": 8900, "category": "샐러드", "image_url": None, "is_active": True, "sort_order": 3},
    {"id": "fallback-sandwich", "name": "샌드위치 세트", "price": 7500, "category": "간편식", "image_url": None, "is_active": True, "sort_order": 4},
]
FALLBACK_DAILY_MENU = {
    "title": "오늘의 부페 메뉴",
    "menu_text": "김치찌개, 제육볶음, 현미밥, 계절 샐러드, 반찬 4종",
    "is_active": True,
}


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def today_kst() -> str:
    return datetime.now(timezone(timedelta(hours=9))).date().isoformat()


def get_today_menu(client: SupabaseHttpClient, merchant_id: str) -> tuple[dict | None, bool]:
    try:
        rows = client.rest_get(
            "merchant_daily_menus",
            {
                "select": "id,merchant_id,service_date,title,menu_text,is_active,updated_at",
                "merchant_id": f"eq.{merchant_id}",
                "service_date": f"eq.{today_kst()}",
                "is_active": "eq.true",
                "limit": "1",
            },
        )
        return (rows[0] if rows else None), False
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            return FALLBACK_DAILY_MENU, True
        raise


@router.get("/merchants/{qr_token}/products")
def list_public_products(qr_token: str):
    client = SupabaseHttpClient()
    try:
        merchants = client.rest_get(
            "merchants",
            {"select": "id,name,category,avg_price,qr_token", "qr_token": f"eq.{qr_token}", "status": "eq.active", "limit": "1"},
        )
        if not merchants:
            raise _error(404, "MERCHANT_NOT_FOUND", "식당 QR을 찾을 수 없어요")
        merchant = merchants[0]
        products = client.rest_get(
            "merchant_products",
            {
                "select": "id,merchant_id,name,price,category,image_url,is_active,sort_order",
                "merchant_id": f"eq.{merchant['id']}",
                "is_active": "eq.true",
                "order": "sort_order.asc,created_at.asc",
            },
        )
        products_migration_required = False
        if not products:
            products = [{**item, "merchant_id": merchant["id"]} for item in FALLBACK_PRODUCTS]
            products_migration_required = True
        today_menu, menu_migration_required = get_today_menu(client, merchant["id"])
        return {"ok": True, "data": {"merchant": merchant, "items": products, "today_menu": today_menu, "migration_required": products_migration_required, "menu_migration_required": menu_migration_required}, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            merchant = {"id": "fallback", "name": "그린잇 식당", "category": "파일럿", "avg_price": 9000, "qr_token": qr_token}
            return {"ok": True, "data": {"merchant": merchant, "items": FALLBACK_PRODUCTS, "today_menu": FALLBACK_DAILY_MENU, "migration_required": True, "menu_migration_required": True}, "error": None}
        raise _error(502, "SUPABASE_ERROR", "상품 목록을 불러오는 중 오류가 발생했어요") from exc
