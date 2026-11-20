from fastapi import APIRouter, Depends, HTTPException

from app.auth import bearer_token
from app.config import get_settings
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.voucher_products import _is_exposed, _load_products
from app.services.vouchers import krw_amount, resolve_voucher_merchant

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _lowest_voucher_price(repo: JoinRepository, merchant_id: str) -> int | None:
    """Cheapest price of one paid voucher among the products on sale now."""
    rows, _ = _load_products(repo, {
        "merchant_id": f"eq.{merchant_id}", "status": "eq.active", "deleted_at": "is.null",
        "order": "display_order.asc,created_at.asc",
    }, allow_legacy=True)
    prices = []
    for row in rows:
        count = int(row.get("voucher_count") or 0)
        if count > 0 and _is_exposed(row):
            prices.append(krw_amount(row["sale_price"]) // count)
    return min(prices) if prices else None


@router.get("")
def restaurants(token: str = Depends(bearer_token)):
    """Restaurants this buyer can use, with the vouchers they hold at each.

    The app's restaurant picker reads this list. While the service runs with one
    restaurant it has exactly one entry; the picker and every screen that names
    the restaurant already work from the list, so adding restaurants later is a
    server change only.
    """
    repo = JoinRepository()
    try:
        auth = repo.auth_user_from_token(token)
        profile = repo.get_profile(auth.id, email=auth.email)
        if profile is None or profile.status != "active" or profile.role not in {"customer", "employee"}:
            raise _error(403, "VOUCHER_ACCOUNT_ONLY", "식당 목록을 볼 수 있는 계정이 아니에요")
        exposed = resolve_voucher_merchant(repo, get_settings().pilot_merchant_id)
        if not exposed:
            return {"ok": True, "data": {"items": [], "default_merchant_id": None}, "error": None}
        rows = repo.client.rest_get("merchants", {
            "select": "id,name,address,category", "id": f"eq.{exposed['id']}", "status": "eq.active",
        })
        held = repo.client.rest_get("vouchers", {
            "select": "merchant_id", "user_id": f"eq.{profile.id}", "status": "eq.unused", "limit": "1000",
        })
        balances: dict[str, int] = {}
        for voucher in held:
            merchant_id = str(voucher.get("merchant_id"))
            balances[merchant_id] = balances.get(merchant_id, 0) + 1
        items = [{
            "id": row["id"],
            "name": row.get("name") or "",
            "address": row.get("address") or "",
            "category": row.get("category") or "",
            "voucher_balance": balances.get(row["id"], 0),
            "voucher_price": _lowest_voucher_price(repo, row["id"]),
        } for row in rows]
        # Restaurants where the buyer holds vouchers first, then by name.
        items.sort(key=lambda item: (item["voucher_balance"] == 0, item["name"]))
        return {"ok": True, "data": {
            "items": items, "default_merchant_id": exposed["id"] if items else None,
        }, "error": None}
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인 정보가 올바르지 않아요") from exc
        raise _error(502, "SUPABASE_ERROR", "식당 목록을 불러오지 못했어요") from exc
