import base64
import binascii
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.products import FALLBACK_DAILY_MENU, FALLBACK_PRODUCTS, today_kst
from app.schemas import DailyMenuUpsertRequest, EmployeeLimitUpdateRequest, EmployeeProfileUpdateRequest, ImageUploadRequest, JoinDecisionRequest, MealPolicyUpdateRequest, ProductCreateRequest, ProductUpdateRequest
from app.services.join_flow import JoinFlowError

router = APIRouter(prefix="/admin", tags=["admin"])
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {
    "image/jpeg": ("jpg", (b"\xff\xd8\xff",)),
    "image/png": ("png", (b"\x89PNG\r\n\x1a\n",)),
    "image/webp": ("webp", (b"RIFF",)),
    "image/gif": ("gif", (b"GIF87a", b"GIF89a")),
}


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


def _company_admin(repo: JoinRepository, token: str):
    actor_auth = repo.auth_user_from_token(token)
    actor = repo.get_profile(actor_auth.id, email=actor_auth.email)
    if actor is None or actor.role != "company_admin" or actor.status != "active" or not actor.company_id:
        raise JoinFlowError("FORBIDDEN", "회사관리자만 조회할 수 있어요")
    return actor


def _month_bounds() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    return start.isoformat(), next_month.isoformat()


@router.get("/employees")
def list_employees(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _company_admin(repo, token)
        migration_required = False
        try:
            employees = repo.client.rest_get(
                "app_users",
                {"select": "id,display_name,employee_no,status,monthly_limit,approved_at,created_at", "company_id": f"eq.{actor.company_id}", "role": "eq.employee", "order": "created_at.desc"},
            )
        except SupabaseHttpError as exc:
            if "monthly_limit" not in exc.body and "PGRST204" not in exc.body:
                raise
            migration_required = True
            employees = repo.client.rest_get(
                "app_users",
                {"select": "id,display_name,status,approved_at,created_at", "company_id": f"eq.{actor.company_id}", "role": "eq.employee", "order": "created_at.desc"},
            )
        user_ids = [row["id"] for row in employees]
        start_iso, end_iso = _month_bounds()
        month_start = datetime.fromisoformat(start_iso)
        month_end = datetime.fromisoformat(end_iso)
        tx_rows = []
        if user_ids:
            tx_rows = repo.client.rest_get(
                "meal_transactions",
                {
                    "select": "user_id,amount,kind,created_at",
                    "user_id": f"in.({','.join(user_ids)})",
                    "created_at": f"gte.{start_iso}",
                },
            )
        stats = {user_id: {"used": 0, "recent": None} for user_id in user_ids}
        for tx in tx_rows:
            user_id = tx.get("user_id")
            if user_id not in stats or tx.get("kind") != "spend":
                continue
            created = tx.get("created_at")
            if not created:
                continue
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if not (month_start <= created_dt < month_end):
                continue
            stats[user_id]["used"] += abs(int(tx.get("amount") or 0))
            if stats[user_id]["recent"] is None or created > stats[user_id]["recent"]:
                stats[user_id]["recent"] = created
        items = []
        for employee in employees:
            employee_stats = stats.get(employee["id"], {"used": 0, "recent": None})
            items.append({
                **employee,
                "monthly_limit": employee.get("monthly_limit") if employee.get("monthly_limit") is not None else 200000,
                "month_used": employee_stats["used"],
                "recent_used_at": employee_stats["recent"],
            })
        return {"ok": True, "data": {"items": items, "migration_required": migration_required}, "error": None}
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        if exc.status in (401, 403):
            raise _error(401, "UNAUTHENTICATED", "로그인이 필요해요") from exc
        raise _error(502, "SUPABASE_ERROR", "직원 목록을 불러오는 중 오류가 발생했어요") from exc


@router.patch("/employees/{user_id}/limit")
def update_employee_limit(user_id: str, payload: EmployeeLimitUpdateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _company_admin(repo, token)
        rows = repo.client.rest_get("app_users", {"select": "id,company_id,role", "id": f"eq.{user_id}", "company_id": f"eq.{actor.company_id}", "role": "eq.employee", "limit": "1"})
        if not rows:
            raise _error(404, "EMPLOYEE_NOT_FOUND", "직원을 찾을 수 없어요")
        updated = repo.client.rest_patch("app_users", {"id": f"eq.{user_id}"}, {"monthly_limit": payload.monthly_limit})[0]
        return {"ok": True, "data": {"employee": updated}, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        if "monthly_limit" in exc.body or "PGRST204" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0011_employee_monthly_limit.sql 적용 후 한도를 저장할 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "직원 한도를 저장하는 중 오류가 발생했어요") from exc


@router.patch("/employees/{user_id}")
def update_employee_profile(user_id: str, payload: EmployeeProfileUpdateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _company_admin(repo, token)
        rows = repo.client.rest_get("app_users", {"select": "id,company_id,role", "id": f"eq.{user_id}", "company_id": f"eq.{actor.company_id}", "role": "eq.employee", "limit": "1"})
        if not rows:
            raise _error(404, "EMPLOYEE_NOT_FOUND", "직원을 찾을 수 없어요")
        updated = repo.client.rest_patch("app_users", {"id": f"eq.{user_id}"}, {"employee_no": payload.employee_no})[0]
        return {"ok": True, "data": {"employee": updated}, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        if "employee_no" in exc.body or "PGRST204" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0016 마이그레이션 적용 후 사번을 저장할 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "직원 사번을 저장하는 중 오류가 발생했어요") from exc


def _meal_policy_data(row: dict | None) -> dict:
    windows = row.get("meal_windows") if row else None
    if not windows:
        return {
            "enabled": False,
            "lunch_start": "11:00",
            "lunch_end": "14:00",
            "dinner_start": "17:30",
            "dinner_end": "20:30",
        }
    by_name = {item.get("name"): item for item in windows if isinstance(item, dict)}
    lunch = by_name.get("중식")
    dinner = by_name.get("석식")
    enabled = bool(lunch and dinner)
    return {
        "enabled": enabled,
        "lunch_start": (lunch or {}).get("start", "11:00"),
        "lunch_end": (lunch or {}).get("end", "14:00"),
        "dinner_start": (dinner or {}).get("start", "17:30"),
        "dinner_end": (dinner or {}).get("end", "20:30"),
    }


def _policy_windows(payload: MealPolicyUpdateRequest) -> list[dict]:
    if not payload.enabled:
        return [{"name": "상시", "start": "00:00", "end": "23:59", "per_meal_limit": 10000000}]
    return [
        {"name": "중식", "start": payload.lunch_start, "end": payload.lunch_end, "per_meal_limit": 10000000},
        {"name": "석식", "start": payload.dinner_start, "end": payload.dinner_end, "per_meal_limit": 10000000},
    ]


@router.get("/meal-policy")
def get_meal_policy(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _company_admin(repo, token)
        rows = repo.client.rest_get(
            "meal_policies",
            {"select": "id,meal_windows,daily_limit,weekend_allowed", "company_id": f"eq.{actor.company_id}", "group_id": "is.null", "limit": "1"},
        )
        return {"ok": True, "data": _meal_policy_data(rows[0] if rows else None), "error": None}
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "식대 사용시간 설정을 불러오는 중 오류가 발생했어요") from exc


@router.put("/meal-policy")
def update_meal_policy(payload: MealPolicyUpdateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _company_admin(repo, token)
        rows = repo.client.rest_get("meal_policies", {"select": "id", "company_id": f"eq.{actor.company_id}", "group_id": "is.null", "limit": "1"})
        body = {
            "company_id": actor.company_id,
            "group_id": None,
            "meal_windows": _policy_windows(payload),
            "daily_limit": None,
            "weekend_allowed": True,
        }
        if rows:
            row = repo.client.rest_patch("meal_policies", {"id": f"eq.{rows[0]['id']}"}, body)[0]
        else:
            row = repo.client.rest_post("meal_policies", body)[0]
        return {"ok": True, "data": _meal_policy_data(row), "error": None}
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "식대 사용시간 설정을 저장하는 중 오류가 발생했어요") from exc


@router.get("/employees/{user_id}/transactions")
def employee_transactions(user_id: str, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _company_admin(repo, token)
        rows = repo.client.rest_get("app_users", {"select": "id,display_name,company_id,role", "id": f"eq.{user_id}", "company_id": f"eq.{actor.company_id}", "role": "eq.employee", "limit": "1"})
        if not rows:
            raise _error(404, "EMPLOYEE_NOT_FOUND", "직원을 찾을 수 없어요")
        tx_rows = repo.client.rest_get(
            "meal_transactions",
            {"select": "id,amount,kind,tx_code,meal_window,product_name,product_price,merchant_id,created_at", "user_id": f"eq.{user_id}", "order": "created_at.desc", "limit": "100"},
        )
        merchant_ids = sorted({str(row.get("merchant_id")) for row in tx_rows if row.get("merchant_id")})
        merchants = {}
        if merchant_ids:
            merchant_rows = repo.client.rest_get("merchants", {"select": "id,name", "id": f"in.({','.join(merchant_ids)})"})
            merchants = {row["id"]: row["name"] for row in merchant_rows}
        items = [{**row, "merchant_name": merchants.get(row.get("merchant_id"), "-")} for row in tx_rows]
        return {"ok": True, "data": {"employee": rows[0], "items": items}, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "직원 이용내역을 불러오는 중 오류가 발생했어요") from exc


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
    if actor is None or actor.role not in ("company_admin", "merchant_admin") or actor.status != "active":
        raise JoinFlowError("FORBIDDEN", "관리자만 이용할 수 있어요")
    return actor


def _admin_merchant(repo: JoinRepository, actor) -> dict:
    if actor.role == "merchant_admin":
        merchant_id = actor.merchant_id
        if not merchant_id:
            links = repo.client.rest_get(
                "merchant_admins",
                {"select": "merchant_id", "user_id": f"eq.{actor.id}", "limit": "1"},
            )
            merchant_id = links[0]["merchant_id"] if links else None
    else:
        if not actor.company_id:
            raise JoinFlowError("FORBIDDEN", "회사 정보가 없어요")
        links = repo.client.rest_get(
            "company_merchants",
            {"select": "merchant_id", "company_id": f"eq.{actor.company_id}", "is_active": "eq.true", "limit": "1"},
        )
        merchant_id = links[0]["merchant_id"] if links else None
    if not merchant_id:
        raise JoinFlowError("MERCHANT_NOT_FOUND", "운영 식당이 아직 연결되지 않았어요")
    merchants = repo.client.rest_get(
        "merchants",
        {"select": "id,name,category,avg_price,qr_token", "id": f"eq.{merchant_id}", "limit": "1"},
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


@router.post("/images")
def upload_merchant_image(payload: ImageUploadRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _active_admin(repo, token)
        merchant = _admin_merchant(repo, actor)
        image_type = payload.content_type.lower().split(";", 1)[0].strip()
        if image_type not in IMAGE_TYPES:
            raise _error(400, "INVALID_IMAGE_TYPE", "JPEG, PNG, WEBP, GIF 이미지만 업로드할 수 있어요")
        try:
            content = base64.b64decode(payload.data_base64.split(",", 1)[-1], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise _error(400, "INVALID_IMAGE_DATA", "올바른 base64 이미지가 아니에요") from exc
        if not content or len(content) > MAX_IMAGE_BYTES:
            raise _error(400, "IMAGE_TOO_LARGE", "이미지는 5MB 이하여야 해요")
        extension, signatures = IMAGE_TYPES[image_type]
        valid_signature = any(content.startswith(signature) for signature in signatures)
        if image_type == "image/webp":
            valid_signature = valid_signature and len(content) >= 12 and content[8:12] == b"WEBP"
        if not valid_signature:
            raise _error(400, "INVALID_IMAGE_DATA", "파일 내용과 이미지 형식이 일치하지 않아요")
        object_path = f"{merchant['id']}/{uuid.uuid4().hex}.{extension}"
        image_url = repo.client.upload_public_object("merchant-images", object_path, content, image_type)
        return {"ok": True, "data": {"image_url": image_url, "filename": payload.filename, "content_type": image_type, "size": len(content)}, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "IMAGE_UPLOAD_FAILED", "이미지 저장소 업로드에 실패했어요") from exc


@router.get("/products")
def list_products(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _active_admin(repo, token)
        merchant = _admin_merchant(repo, actor)
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
        merchant = _admin_merchant(repo, actor)
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
        merchant = _admin_merchant(repo, actor)
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
        merchant = _admin_merchant(repo, actor)
        try:
            rows = repo.client.rest_get(
                "merchant_daily_menus",
                {
                    "select": "id,merchant_id,service_date,title,menu_text,image_url,is_active,updated_at",
                    "merchant_id": f"eq.{merchant['id']}",
                    "service_date": f"eq.{today_kst()}",
                    "limit": "1",
                },
            )
            menu = rows[0] if rows else None
            migration_required = False
        except SupabaseHttpError as exc:
            if "image_url" in exc.body or "PGRST204" in exc.body:
                legacy_rows = repo.client.rest_get(
                    "merchant_daily_menus",
                    {"select": "id,merchant_id,service_date,title,menu_text,is_active,updated_at", "merchant_id": f"eq.{merchant['id']}", "service_date": f"eq.{today_kst()}", "limit": "1"},
                )
                menu = {**legacy_rows[0], "image_url": None} if legacy_rows else None
                migration_required = True
            elif "PGRST205" in exc.body:
                menu = FALLBACK_DAILY_MENU
                migration_required = True
            else:
                raise
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
        merchant = _admin_merchant(repo, actor)
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
            "image_url": payload.image_url,
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
        if "PGRST205" in exc.body or "image_url" in exc.body or "PGRST204" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0016_merchant_images_and_settlement_periods.sql 적용 후 오늘 메뉴 이미지를 저장할 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "오늘 메뉴를 저장하는 중 오류가 발생했어요") from exc
