from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.repositories.supabase_http import SupabaseHttpClient, SupabaseHttpError
from app.services.vouchers import resolve_voucher_merchant_client

router = APIRouter(tags=["daily-menu"])
LEGACY_PRIMARY_MENU_QR_TOKEN = "QR-PILOT-KIMCHI"

FALLBACK_DAILY_MENU = {
    "title": "오늘 뷔페 메뉴",
    "menu_text": "",
    "image_url": None,
    "is_active": False,
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
                "select": "id,merchant_id,service_date,title,menu_text,image_url,is_active,updated_at",
                "merchant_id": f"eq.{merchant_id}",
                "service_date": f"eq.{today_kst()}",
                "is_active": "eq.true",
                "limit": "1",
            },
        )
        return (rows[0] if rows else None), False
    except SupabaseHttpError as exc:
        if "image_url" in exc.body or "PGRST204" in exc.body:
            rows = client.rest_get(
                "merchant_daily_menus",
                {"select": "id,merchant_id,service_date,title,menu_text,is_active,updated_at", "merchant_id": f"eq.{merchant_id}", "service_date": f"eq.{today_kst()}", "is_active": "eq.true", "limit": "1"},
            )
            return ({**rows[0], "image_url": None} if rows else None), True
        if "PGRST205" in exc.body:
            return None, True
        raise


@router.get("/daily-menu")
def get_primary_daily_menu():
    client = SupabaseHttpClient()
    try:
        merchant = resolve_voucher_merchant_client(
            client, get_settings().pilot_merchant_id
        )
        if not merchant:
            raise _error(404, "MERCHANT_NOT_FOUND", "식당을 찾을 수 없어요")
        today_menu, migration_required = get_today_menu(client, merchant["id"])
        return {
            "ok": True,
            "data": {
                "today_menu": today_menu,
                "migration_required": migration_required,
            },
            "error": None,
        }
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            return {
                "ok": True,
                "data": {"today_menu": None, "migration_required": True},
                "error": None,
            }
        raise _error(
            502, "SUPABASE_ERROR", "오늘 메뉴를 불러오는 중 오류가 발생했어요"
        ) from exc


@router.get("/merchants/{qr_token}/daily-menu")
def get_public_daily_menu(qr_token: str):
    client = SupabaseHttpClient()
    try:
        merchants = client.rest_get(
            "merchants",
            {"select": "id", "qr_token": f"eq.{qr_token}", "status": "eq.active", "limit": "1"},
        )
        if not merchants and qr_token == LEGACY_PRIMARY_MENU_QR_TOKEN:
            primary = resolve_voucher_merchant_client(
                client, get_settings().pilot_merchant_id
            )
            merchants = [primary] if primary else []
        if not merchants:
            raise _error(404, "MERCHANT_NOT_FOUND", "식당 QR을 찾을 수 없어요")
        today_menu, migration_required = get_today_menu(client, merchants[0]["id"])
        return {
            "ok": True,
            "data": {
                "today_menu": today_menu,
                "migration_required": migration_required,
            },
            "error": None,
        }
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            return {
                "ok": True,
                "data": {"today_menu": None, "migration_required": True},
                "error": None,
            }
        raise _error(502, "SUPABASE_ERROR", "오늘 메뉴를 불러오는 중 오류가 발생했어요") from exc
