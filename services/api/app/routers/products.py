from fastapi import APIRouter, HTTPException

from app.repositories.supabase_http import SupabaseHttpClient, SupabaseHttpError

router = APIRouter(tags=["products"])

FALLBACK_PRODUCTS = [
    {"id": "fallback-kimchi", "name": "든든 김치찌개", "price": 9000, "category": "한식", "image_url": None, "is_active": True, "sort_order": 1},
    {"id": "fallback-pork", "name": "제육 도시락", "price": 9500, "category": "도시락", "image_url": None, "is_active": True, "sort_order": 2},
    {"id": "fallback-salad", "name": "닭가슴살 샐러드", "price": 8900, "category": "샐러드", "image_url": None, "is_active": True, "sort_order": 3},
    {"id": "fallback-sandwich", "name": "샌드위치 세트", "price": 7500, "category": "간편식", "image_url": None, "is_active": True, "sort_order": 4},
]


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


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
        return {"ok": True, "data": {"merchant": merchant, "items": products}, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            merchant = {"id": "fallback", "name": "그린잇 식당", "category": "파일럿", "avg_price": 9000, "qr_token": qr_token}
            return {"ok": True, "data": {"merchant": merchant, "items": FALLBACK_PRODUCTS, "migration_required": True}, "error": None}
        raise _error(502, "SUPABASE_ERROR", "상품 목록을 불러오는 중 오류가 발생했어요") from exc
