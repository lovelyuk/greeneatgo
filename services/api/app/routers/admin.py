import base64
import binascii
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.products import FALLBACK_DAILY_MENU, FALLBACK_PRODUCTS, today_kst
from app.schemas import DailyMenuUpsertRequest, EmployeeBulkConfirmRequest, EmployeeLimitUpdateRequest, EmployeePointAdjustRequest, EmployeePointChargeRequest, EmployeeProfileUpdateRequest, ImageDeleteRequest, ImageUploadRequest, JoinDecisionRequest, MealPolicyUpdateRequest, ProductCreateRequest, ProductUpdateRequest
from app.services.employee_bulk import BulkFileError, RawEmployeeRow, build_template, read_employee_file, validate_rows
from app.services.join_flow import JoinFlowError
from app.services.product_images import ProductImageError, managed_image_path, normalize_product_image
from app.services.push_notifications import send_individual_point_push

router = APIRouter(prefix="/admin", tags=["admin"])
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {
    "image/jpeg": ("jpg", (b"\xff\xd8\xff",)),
    "image/png": ("png", (b"\x89PNG\r\n\x1a\n",)),
    "image/webp": ("webp", (b"RIFF",)),
    "image/gif": ("gif", (b"GIF87a", b"GIF89a")),
}
logger = logging.getLogger(__name__)


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


def _paged_rest_get(repo: JoinRepository, table: str, params: dict[str, str]) -> list[dict]:
    rows: list[dict] = []
    page_size = 500
    while True:
        page_params = {**params, "limit": str(page_size), "offset": str(len(rows))}
        page = repo.client.rest_get(table, page_params)
        rows.extend(page)
        if len(page) < page_size:
            return rows


def _bulk_existing(repo: JoinRepository, company_id: str) -> tuple[set[str], set[str]]:
    params = {"select": "phone,employee_no", "company_id": f"eq.{company_id}", "order": "id.asc"}
    users = _paged_rest_get(repo, "app_users", params)
    invites = _paged_rest_get(repo, "employee_bulk_invites", params)
    phones = {str(row["phone"]) for row in users + invites if row.get("phone")}
    employee_nos = {str(row["employee_no"]) for row in users + invites if row.get("employee_no")}
    return phones, employee_nos


@router.get("/employees/template")
def employee_bulk_template(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _company_admin(repo, token)
        return Response(
            content=build_template(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=employee_bulk_template.xlsx"},
        )
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc


@router.post("/employees/bulk-upload/parse")
async def parse_employee_bulk(file: UploadFile = File(...), token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _company_admin(repo, token)
        assert actor.company_id is not None
        content = await file.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise BulkFileError("파일은 10MB 이하여야 해요")
        rows = read_employee_file(file.filename or "", content)
        phones, employee_nos = _bulk_existing(repo, actor.company_id)
        result = validate_rows(rows, company_id=actor.company_id, existing_phones=phones, existing_employee_nos=employee_nos)
        return {"ok": True, "data": result, "error": None}
    except BulkFileError as exc:
        raise _error(400, "INVALID_BULK_FILE", str(exc)) from exc
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "직원 중복 정보를 확인하지 못했어요") from exc


@router.post("/employees/bulk-upload/confirm")
def confirm_employee_bulk(payload: EmployeeBulkConfirmRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _company_admin(repo, token)
        assert actor.company_id is not None
        submitted = [RawEmployeeRow(
            row=row.row, department=row.department, name=row.name,
            employee_no=row.employee_no, phone=row.phone, auto_generated=row.auto_generated,
        ) for row in payload.valid_rows]
        phones, employee_nos = _bulk_existing(repo, actor.company_id)
        checked = validate_rows(submitted, company_id=actor.company_id, existing_phones=phones, existing_employee_nos=employee_nos)
        if checked["errors"] or len(checked["valid"]) != len(submitted):
            raise HTTPException(status_code=422, detail={
                "code": "BULK_ROWS_INVALID",
                "message": "미리보기 이후 데이터가 변경되었어요. 파일을 다시 확인해 주세요",
                "errors": checked["errors"],
            })
        rpc_rows = [{
            "department": row["department"], "display_name": row["name"],
            "employee_no": row["employee_no"], "phone": row["phone"],
        } for row in checked["valid"]]
        created_count = repo.client.rpc("confirm_employee_bulk_invites", {
            "p_company_id": actor.company_id, "p_rows": rpc_rows,
        })
        return {"ok": True, "data": {"created_count": int(created_count)}, "error": None}
    except HTTPException:
        raise
    except BulkFileError as exc:
        raise _error(422, "BULK_ROWS_INVALID", str(exc)) from exc
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        if any(code in exc.body for code in ("DUPLICATE_", "INVALID_BULK")) or exc.status == 409:
            raise _error(422, "BULK_ROWS_CHANGED", "다른 등록과 중복됐어요. 파일을 다시 업로드해 주세요") from exc
        raise _error(502, "SUPABASE_ERROR", "직원 초대를 저장하지 못했어요") from exc


@router.get("/employees")
def list_employees(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _company_admin(repo, token)
        migration_required = False
        try:
            employees = _paged_rest_get(repo,
                "app_users",
                {"select": "id,display_name,employee_no,phone,department,status,monthly_limit,point_balance,approved_at,created_at", "company_id": f"eq.{actor.company_id}", "role": "eq.employee", "order": "created_at.desc"},
            )
        except SupabaseHttpError as exc:
            if "monthly_limit" not in exc.body and "PGRST204" not in exc.body:
                raise
            migration_required = True
            employees = _paged_rest_get(repo,
                "app_users",
                {"select": "id,display_name,status,approved_at,created_at", "company_id": f"eq.{actor.company_id}", "role": "eq.employee", "order": "created_at.desc"},
            )
        bulk_migration_required = migration_required
        staged_invites = []
        if not migration_required:
            try:
                staged_invites = _paged_rest_get(repo,
                    "employee_bulk_invites",
                    {"select": "id,display_name,employee_no,phone,department,status,created_at", "company_id": f"eq.{actor.company_id}", "status": "eq.invited", "order": "created_at.desc"},
                )
            except SupabaseHttpError as exc:
                if "employee_bulk_invites" not in exc.body and "PGRST205" not in exc.body:
                    raise
                bulk_migration_required = True
        user_ids = [row["id"] for row in employees]
        start_iso, end_iso = _month_bounds()
        month_start = datetime.fromisoformat(start_iso)
        month_end = datetime.fromisoformat(end_iso)
        tx_rows = []
        if user_ids:
            tx_rows = _paged_rest_get(repo,
                "meal_transactions",
                {
                    "select": "user_id,amount,kind,created_at",
                    "company_id": f"eq.{actor.company_id}",
                    "created_at": f"gte.{start_iso}",
                    "order": "id.asc",
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
        point_rows = _paged_rest_get(repo, "point_transactions", {"select": "user_id,amount,created_at", "company_id": f"eq.{actor.company_id}", "type": "eq.charge", "order": "created_at.desc"}) if user_ids and not migration_required else []
        recent_charge = {}
        for point in point_rows:
            recent_charge.setdefault(point["user_id"], point)
        for employee in employees:
            employee_stats = stats.get(employee["id"], {"used": 0, "recent": None})
            items.append({
                **employee,
                "monthly_limit": employee.get("monthly_limit") if employee.get("monthly_limit") is not None else 200000,
                "month_used": employee_stats["used"],
                "recent_used_at": employee_stats["recent"],
                "point_balance": int(employee.get("point_balance") or 0),
                "recent_point_charge": recent_charge.get(employee["id"]),
            })
        items.extend({
            **invite,
            "id": f"bulk:{invite['id']}",
            "is_staged": True,
            "monthly_limit": 200000,
            "month_used": 0,
            "recent_used_at": None,
        } for invite in staged_invites)
        return {"ok": True, "data": {
            "items": items,
            "migration_required": migration_required,
            "bulk_migration_required": bulk_migration_required,
        }, "error": None}
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
        updated = repo.client.rpc("update_company_employee_no", {
            "p_company_id": actor.company_id,
            "p_user_id": user_id,
            "p_employee_no": payload.employee_no,
        })
        return {"ok": True, "data": {"employee": updated}, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        if "DUPLICATE_EMPLOYEE_NO" in exc.body:
            raise _error(409, "DUPLICATE_EMPLOYEE_NO", "이미 사용 중이거나 초대 대기 중인 사번이에요") from exc
        if "update_company_employee_no" in exc.body or "PGRST202" in exc.body or "PGRST204" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0017 마이그레이션 적용 후 사번을 저장할 수 있어요") from exc
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


def _change_employee_points(user_id: str, mode: str, value: int, reason: str, confirmed: bool, token: str):
    repo = JoinRepository()
    try:
        actor = _company_admin(repo, token)
        result = repo.client.rpc("company_admin_change_points", {"p_admin_id": actor.id, "p_employee_id": user_id, "p_mode": mode, "p_value": value, "p_reason": reason, "p_confirmed": confirmed})
        if mode == "charge":
            try:
                rows = repo.client.rest_get("device_tokens", {"select": "fcm_token", "account_id": f"eq.{user_id}", "is_active": "eq.true"})
                send_individual_point_push(tokens=[row["fcm_token"] for row in rows], amount=value, balance=int(result["point_balance"]))
            except Exception:
                logger.exception("Point charge committed but push failed for %s", user_id)
        return {"ok": True, "data": result, "error": None}
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        for code, status in {"EMPLOYEE_NOT_FOUND": 404, "REASON_REQUIRED": 422, "WELFARE_DEDUCTION_CONFIRMATION_REQUIRED": 422, "INVALID_TARGET_BALANCE": 409, "NO_CHANGE": 409}.items():
            if code in exc.body:
                raise _error(status, code, code) from exc
        raise _error(502, "POINT_CHANGE_FAILED", "포인트 변경을 저장하지 못했어요") from exc


@router.post("/employees/{user_id}/points/charge")
def charge_employee_points(user_id: str, payload: EmployeePointChargeRequest, token: str = Depends(bearer_token)):
    if not payload.welfare_deduction_confirmed:
        raise _error(422, "WELFARE_DEDUCTION_CONFIRMATION_REQUIRED", "외부 복지 차감 확인이 필요해요")
    return _change_employee_points(user_id, "charge", payload.amount, payload.reason, True, token)


@router.post("/employees/{user_id}/points/adjust")
def adjust_employee_points(user_id: str, payload: EmployeePointAdjustRequest, token: str = Depends(bearer_token)):
    return _change_employee_points(user_id, "adjust", payload.target_balance, payload.reason, False, token)


@router.get("/employees/{user_id}/points")
def employee_points(user_id: str, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _company_admin(repo, token)
        employees = repo.client.rest_get("app_users", {"select": "id,display_name,point_balance", "id": f"eq.{user_id}", "company_id": f"eq.{actor.company_id}", "role": "eq.employee", "limit": "1"})
        if not employees:
            raise _error(404, "EMPLOYEE_NOT_FOUND", "직원을 찾을 수 없어요")
        items = repo.client.rest_get("point_transactions", {"select": "id,type,amount,balance_after,reason,processed_by,related_voucher_id,related_order_id,created_at", "user_id": f"eq.{user_id}", "order": "created_at.desc", "limit": "100"})
        return {"ok": True, "data": {"employee": employees[0], "items": items}, "error": None}
    except HTTPException: raise
    except JoinFlowError as exc: raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc: raise _error(502, "POINT_HISTORY_FAILED", "포인트 내역을 불러오지 못했어요") from exc


@router.get("/employees/{user_id}/transactions")
def employee_transactions(user_id: str, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _company_admin(repo, token)
        rows = repo.client.rest_get("app_users", {"select": "id,display_name,employee_no,phone,department,company_id,role", "id": f"eq.{user_id}", "company_id": f"eq.{actor.company_id}", "role": "eq.employee", "limit": "1"})
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


@router.post("/product-images")
def upload_product_image(payload: ImageUploadRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _active_admin(repo, token)
        merchant = _admin_merchant(repo, actor)
        image_type = payload.content_type.lower().split(";", 1)[0].strip()
        if image_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise _error(400, "INVALID_IMAGE_TYPE", "JPG, PNG, WEBP 이미지만 업로드할 수 있어요")
        try:
            content = base64.b64decode(payload.data_base64.split(",", 1)[-1], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise _error(400, "INVALID_IMAGE_DATA", "올바른 base64 이미지가 아니에요") from exc
        if not content or len(content) > MAX_IMAGE_BYTES:
            raise _error(400, "IMAGE_TOO_LARGE", "크롭된 이미지는 5MB 이하여야 해요")
        try:
            encoded = normalize_product_image(content)
        except ProductImageError as exc:
            raise _error(400, "INVALID_PRODUCT_IMAGE", str(exc)) from exc
        object_path = f"{merchant['id']}/products/{uuid.uuid4().hex}.webp"
        image_url = repo.client.upload_public_object("merchant-images", object_path, encoded, "image/webp")
        return {"ok": True, "data": {"image_url": image_url, "filename": payload.filename, "content_type": "image/webp", "size": len(encoded), "width": 800, "height": 800}, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "IMAGE_UPLOAD_FAILED", "상품 이미지 저장소 업로드에 실패했어요") from exc


@router.delete("/product-images")
def delete_product_image(payload: ImageDeleteRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor = _active_admin(repo, token)
        merchant = _admin_merchant(repo, actor)
        object_path = managed_image_path(
            payload.image_url,
            repo.client.settings.supabase_url,
            "merchant-images",
            merchant["id"],
        )
        if object_path is None:
            raise _error(400, "INVALID_IMAGE_URL", "이 식당이 업로드한 이미지가 아니에요")
        reference_filters = {
            "select": "id",
            "merchant_id": f"eq.{merchant['id']}",
            "image_url": f"eq.{payload.image_url}",
            "limit": "1",
        }
        if repo.client.rest_get("merchant_products", reference_filters) or repo.client.rest_get("voucher_products", reference_filters):
            raise _error(409, "IMAGE_STILL_IN_USE", "현재 상품에서 사용 중인 이미지는 삭제할 수 없어요")
        repo.client.delete_public_objects("merchant-images", [object_path])
        return {"ok": True, "data": {"deleted": True}, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _handle_join_error(exc) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "IMAGE_DELETE_FAILED", "상품 이미지 삭제에 실패했어요") from exc


def _delete_replaced_product_image(repo: JoinRepository, merchant_id: str, old_url: str | None, new_url: str | None) -> None:
    if not old_url or old_url == new_url:
        return
    object_path = managed_image_path(old_url, repo.client.settings.supabase_url, "merchant-images", merchant_id)
    if object_path is None:
        return
    try:
        repo.client.delete_public_objects("merchant-images", [object_path])
    except Exception:  # DB update already committed; never make the client delete the live new image.
        logger.exception("Failed to delete replaced merchant product image: %s", object_path)


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
        current = _ensure_product_belongs(repo, product_id, merchant["id"])
        values = {key: value for key, value in payload.model_dump().items() if value is not None}
        if not values:
            raise _error(400, "NO_CHANGES", "수정할 값을 입력해 주세요")
        values["updated_at"] = datetime.now().isoformat()
        row = repo.client.rest_patch("merchant_products", {"id": f"eq.{product_id}"}, values)[0]
        if "image_url" in values:
            _delete_replaced_product_image(repo, merchant["id"], current.get("image_url"), values.get("image_url"))
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
            repo.client.rest_delete(
                "merchant_daily_menus",
                {"merchant_id": f"eq.{merchant['id']}", "service_date": f"lt.{today_kst()}"},
            )
            rows = repo.client.rest_get(
                "merchant_daily_menus",
                {
                    "select": "id,merchant_id,service_date,title,menu_text,image_url,is_active,updated_at",
                    "merchant_id": f"eq.{merchant['id']}",
                    "service_date": f"gte.{today_kst()}",
                    "order": "service_date.asc",
                },
            )
            menus = rows
            menu = next((item for item in menus if item["service_date"] == today_kst()), None)
            migration_required = False
        except SupabaseHttpError as exc:
            if "image_url" in exc.body or "PGRST204" in exc.body:
                legacy_rows = repo.client.rest_get(
                    "merchant_daily_menus",
                    {"select": "id,merchant_id,service_date,title,menu_text,is_active,updated_at", "merchant_id": f"eq.{merchant['id']}", "service_date": f"gte.{today_kst()}", "order": "service_date.asc"},
                )
                menus = [{**item, "image_url": None} for item in legacy_rows]
                menu = next((item for item in menus if item["service_date"] == today_kst()), None)
                migration_required = True
            elif "PGRST205" in exc.body:
                menu = FALLBACK_DAILY_MENU
                menus = []
                migration_required = True
            else:
                raise
        return {"ok": True, "data": {"merchant": merchant, "today_menu": menu, "menus": menus, "service_date": today_kst(), "migration_required": migration_required}, "error": None}
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
        service_date = payload.service_date.isoformat()
        if service_date < today_kst():
            raise _error(400, "PAST_DATE", "지난 날짜의 메뉴는 저장할 수 없어요")
        repo.client.rest_delete(
            "merchant_daily_menus",
            {"merchant_id": f"eq.{merchant['id']}", "service_date": f"lt.{today_kst()}"},
        )
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
