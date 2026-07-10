from __future__ import annotations

import html
import secrets
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.schemas import MerchantCompanyContractUpdateRequest, MerchantCompanyCreateAndLinkRequest, MerchantCompanyLinkRequest, SettlementCreateRequest, SettlementPaymentConfirmRequest
from app.services.join_flow import JoinErrorCode, JoinFlowError

router = APIRouter(prefix="/admin/merchant", tags=["merchant-admin"])
KST = ZoneInfo("Asia/Seoul")


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _token() -> str:
    return secrets.token_urlsafe(32)


def _invite_code() -> str:
    return f"GE-{secrets.token_hex(3).upper()}"


def _ensure_company_invite_code(repo: JoinRepository, company_id: str) -> str:
    rows = repo.client.rest_get(
        "company_invite_codes",
        {"select": "code", "company_id": f"eq.{company_id}", "is_active": "eq.true", "order": "created_at.desc", "limit": "1"},
    )
    if rows:
        return rows[0]["code"]
    for _ in range(5):
        code = _invite_code()
        try:
            repo.client.rest_post("company_invite_codes", {"company_id": company_id, "code": code, "is_active": True})
            return code
        except SupabaseHttpError as exc:
            if "duplicate" not in exc.body.lower() and "unique" not in exc.body.lower():
                raise
    raise _error(502, "INVITE_CODE_CREATE_FAILED", "초대코드를 생성하지 못했어요")


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


def _parse_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError) as exc:
        raise _error(400, "INVALID_DATE", "날짜는 YYYY-MM-DD 형식이어야 해요") from exc


def _month_range(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    start = today.replace(day=1)
    next_month = date(today.year + (1 if today.month == 12 else 0), 1 if today.month == 12 else today.month + 1, 1)
    return start, next_month - timedelta(days=1)


def _iso_bounds(from_: str | None, to: str | None) -> tuple[str, str, date, date]:
    default_from, default_to = _month_range(datetime.now(KST).date())
    from_date = _parse_date(from_, default_from)
    to_date = _parse_date(to, default_to)
    if from_date > to_date:
        raise _error(400, "INVALID_DATE_RANGE", "시작일은 종료일보다 늦을 수 없어요")
    start = datetime.combine(from_date, time.min, tzinfo=KST).astimezone(timezone.utc)
    end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=KST).astimezone(timezone.utc)
    return start.isoformat(), end.isoformat(), from_date, to_date


def _paged_get(repo: JoinRepository, table: str, params: dict[str, str], page_size: int = 1000) -> list[dict]:
    """Read every row rather than silently accepting PostgREST's project row cap."""
    rows: list[dict] = []
    offset = 0
    while True:
        page = repo.client.rest_get(table, {**params, "limit": str(page_size), "offset": str(offset)})
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def _require_company_link(repo: JoinRepository, merchant_id: str, company_id: str) -> dict:
    links = repo.client.rest_get(
        "merchant_companies",
        {"select": "id,merchant_id,company_id,status,settlement_cycle,settlement_day,unit_price,created_at", "merchant_id": f"eq.{merchant_id}", "company_id": f"eq.{company_id}", "limit": "1"},
    )
    if not links:
        raise JoinFlowError(JoinErrorCode.FORBIDDEN, "연결된 장부업체가 아니에요")
    if links[0].get("status") != "active":
        raise JoinFlowError(JoinErrorCode.FORBIDDEN, "일시중지된 장부업체예요")
    return links[0]


def _company_name(repo: JoinRepository, company_id: str) -> str:
    rows = repo.client.rest_get("companies", {"select": "name", "id": f"eq.{company_id}", "limit": "1"})
    return rows[0]["name"] if rows else company_id


def _contract_from_link(link: dict | None) -> dict | None:
    if not link:
        return None
    cycle = link.get("settlement_cycle")
    day = link.get("settlement_day")
    unit_price = link.get("unit_price")
    if not cycle and unit_price is None:
        return None
    return {
        "settlement_cycle": cycle or "month_end",
        "settlement_day": day,
        "unit_price": unit_price,
        "cycle_label": "월말" if (cycle or "month_end") == "month_end" else f"매월 {day}일",
    }


def _contract_label(link: dict | None) -> str:
    contract = _contract_from_link(link)
    if not contract:
        return "미설정"
    price = contract.get("unit_price")
    price_text = f" · 단가 {int(price):,}원" if price is not None else ""
    return f"{contract['cycle_label']}{price_text}"


def _next_settlement_date_for_contract(link: dict | None) -> str:
    today = date.today()
    contract = _contract_from_link(link)
    if not contract or contract["settlement_cycle"] == "month_end":
        _, last = _month_range(today)
        return last.isoformat()
    day = min(int(contract.get("settlement_day") or 1), 31)
    last_this_month = _month_range(today)[1].day
    candidate = date(today.year, today.month, min(day, last_this_month))
    if candidate < today:
        next_month = date(today.year + (1 if today.month == 12 else 0), 1 if today.month == 12 else today.month + 1, 1)
        last_next_month = _month_range(next_month)[1].day
        candidate = date(next_month.year, next_month.month, min(day, last_next_month))
    return candidate.isoformat()


def _tx_amount(row: dict) -> int:
    amount = int(row.get("amount") or row.get("product_price") or 0)
    if row.get("kind") in {"spend", "refund", "cancel"}:
        return abs(amount) if row.get("kind") == "spend" else -abs(amount)
    return amount


def _kst_iso(value: object) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(KST).isoformat()
    except (TypeError, ValueError):
        return str(value or "")


def _load_vendor_transactions(repo: JoinRepository, merchant_id: str, company_id: str, from_: str | None, to: str | None, q: str | None = None) -> tuple[list[dict], date, date]:
    from_iso, to_iso, from_date, to_date = _iso_bounds(from_, to)
    rows = _paged_get(
        repo,
        "meal_transactions",
        {
            "select": "id,user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,flags,product_name,product_price,pay_type,created_at",
            "merchant_id": f"eq.{merchant_id}",
            "company_id": f"eq.{company_id}",
            "pay_type": "eq.ledger",
            "and": f"(created_at.gte.{from_iso},created_at.lt.{to_iso})",
            "order": "created_at.desc",
        },
    )
    user_ids = sorted({row["user_id"] for row in rows if row.get("user_id")})
    users = {}
    if user_ids:
        user_rows = repo.client.rest_get("app_users", {"select": "id,display_name,employee_no,group_id", "id": f"in.({','.join(user_ids)})"})
        users = {row["id"]: row for row in user_rows}
    group_ids = sorted({str(row["group_id"]) for row in users.values() if row.get("group_id")})
    groups = {}
    if group_ids:
        group_rows = repo.client.rest_get("employee_groups", {"select": "id,name", "id": f"in.({','.join(group_ids)})"})
        groups = {row["id"]: row.get("name") for row in group_rows}
    query = (q or "").strip().lower()
    items = []
    for row in rows:
        user = users.get(row.get("user_id"), {})
        employee_name = user.get("display_name") or "직원"
        employee_no = user.get("employee_no") or str(row.get("user_id") or "")[:8]
        department = groups.get(user.get("group_id")) or "-"
        if query and query not in f"{department} {employee_name} {employee_no}".lower():
            continue
        amount = _tx_amount(row)
        items.append({
            **row,
            "created_at": _kst_iso(row.get("created_at")),
            "amount": amount,
            "employee_name": employee_name,
            "employee_no": employee_no,
            "department": department,
            "menu": row.get("product_name") or row.get("meal_window") or "식대 사용",
            "pay_type": "식권" if row.get("pay_type") == "voucher" else "장부",
            "status": "refund" if row.get("kind") in {"refund", "cancel"} else "paid",
        })
    return items, from_date, to_date


def _group_days(items: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for item in items:
        key = str(item.get("created_at", ""))[:10]
        grouped.setdefault(key, []).append(item)
    days = []
    for key in sorted(grouped.keys(), reverse=True):
        group_items = grouped[key]
        days.append({
            "date": key,
            "subtotal": sum(int(item.get("amount") or 0) for item in group_items),
            "count": len(group_items),
            "items": group_items,
        })
    return days


def _next_settlement_date() -> str:
    _, last = _month_range()
    return last.isoformat()


def _settlement_status(row: dict) -> str:
    if row.get("status") == "paid":
        return "입금완료"
    if row.get("period_to"):
        try:
            due = date.fromisoformat(str(row["period_to"])[:10]) + timedelta(days=10)
        except ValueError:
            due = datetime.now(KST).date()
    else:
        period = row.get("period_ym", "")
        try:
            y, m = [int(part) for part in period.split("-")[:2]]
            due = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 10)
        except Exception:
            due = datetime.now(KST).date()
    return "연체" if datetime.now(KST).date() > due else "입금대기"


def _ensure_settlements(repo: JoinRepository, merchant_id: str, company_id: str) -> list[dict]:
    tx_rows = repo.client.rest_get(
        "meal_transactions",
        {
            "select": "id,amount,kind,pay_type,created_at",
            "merchant_id": f"eq.{merchant_id}",
            "company_id": f"eq.{company_id}",
            "pay_type": "eq.ledger",
            "kind": "in.(spend,refund)",
            "limit": "2000",
        },
    )
    aggregates: dict[str, dict[str, int]] = {}
    for row in tx_rows:
        ym = str(row.get("created_at", ""))[:7]
        if not ym:
            continue
        bucket = aggregates.setdefault(ym, {"tx_count": 0, "total_amount": 0})
        bucket["tx_count"] += 1
        bucket["total_amount"] += _tx_amount(row)
    existing = repo.client.rest_get(
        "settlements",
        {"select": "id,company_id,merchant_id,period_ym,period_from,period_to,tx_count,total_amount,status,paid_at", "merchant_id": f"eq.{merchant_id}", "company_id": f"eq.{company_id}", "order": "period_from.desc,period_ym.desc"},
    )
    existing_by_period = {row["period_ym"]: row for row in existing}
    for ym, summary in aggregates.items():
        if ym in existing_by_period:
            row = existing_by_period[ym]
            if row.get("status") != "paid" and (row.get("tx_count") != summary["tx_count"] or row.get("total_amount") != summary["total_amount"]):
                repo.client.rest_patch("settlements", {"id": f"eq.{row['id']}"}, {"tx_count": summary["tx_count"], "total_amount": summary["total_amount"]})
        else:
            period_from, period_to = _settlement_period_bounds(ym)
            repo.client.rest_post("settlements", {"company_id": company_id, "merchant_id": merchant_id, "period_ym": ym, "period_from": period_from, "period_to": period_to, "tx_count": summary["tx_count"], "total_amount": summary["total_amount"], "status": "confirmed"})
    return repo.client.rest_get(
        "settlements",
        {"select": "id,company_id,merchant_id,period_ym,period_from,period_to,tx_count,total_amount,status,paid_at", "merchant_id": f"eq.{merchant_id}", "company_id": f"eq.{company_id}", "order": "period_from.desc,period_ym.desc"},
    )


def _settlement_period_bounds(period_ym: str) -> tuple[str, str]:
    y, m = [int(part) for part in period_ym.split("-")[:2]]
    first = date(y, m, 1)
    next_month = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
    last = next_month - timedelta(days=1)
    return first.isoformat(), last.isoformat()


def _xlsx_bytes(rows: list[list[str]]) -> bytes:
    def esc(value: object) -> str:
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    sheet_rows = []
    for r_idx, row in enumerate(rows, start=1):
        cells = []
        for c_idx, value in enumerate(row):
            col = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[c_idx]
            cells.append(f'<c r="{col}{r_idx}" t="inlineStr"><is><t>{esc(value)}</t></is></c>')
        sheet_rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    out = BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        zf.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        zf.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="거래내역" sheetId="1" r:id="rId1"/></sheets></workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        zf.writestr("xl/worksheets/sheet1.xml", f'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    return out.getvalue()


def _pdf_bytes(lines: list[str]) -> bytes:
    # WeasyPrint embeds system fonts, preserving Korean headers and values.
    import importlib

    HTML = importlib.import_module("weasyprint").HTML

    body = "".join(f"<div>{html.escape(line)}</div>" for line in lines)
    document = f"""<!doctype html><html lang='ko'><meta charset='utf-8'><style>
      @page {{ size: A4 landscape; margin: 18mm; }}
      body {{ font-family: 'Noto Sans CJK KR', 'NanumGothic', sans-serif; font-size: 10px; color: #14351f; }}
      div {{ padding: 4px 0; border-bottom: 1px solid #d9e8dc; white-space: pre-wrap; }}
      div:nth-child(-n+4) {{ font-size: 13px; font-weight: bold; border: 0; }}
    </style><body>{body}</body></html>"""
    return HTML(string=document).write_pdf()


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value).strip("_") or "vendor"


@router.get("/qr")
def merchant_qr(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        rows = repo.client.rest_get(
            "merchants",
            {"select": "id,name,category,avg_price,qr_token,status", "id": f"eq.{merchant_id}", "limit": "1"},
        )
        if not rows:
            raise _error(404, "MERCHANT_NOT_FOUND", "식당 정보를 찾을 수 없어요")
        merchant = rows[0]
        return {"ok": True, "data": {"merchant": merchant, "qr_token": merchant.get("qr_token")}, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "매장 QR 정보를 불러오는 중 오류가 발생했어요") from exc


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
            {"select": "id,merchant_id,company_id,status,settlement_cycle,settlement_day,unit_price,created_at", "merchant_id": f"eq.{merchant_id}", "order": "created_at.desc"},
        )
        company_ids = [link["company_id"] for link in links]
        companies = {row["id"]: row for row in _company_rows(repo, company_ids)}
        invites_by_company = {}
        if company_ids:
            invite_rows = repo.client.rest_get(
                "invites",
                {
                    "select": "token,company_id,phone,status,expires_at,created_at",
                    "company_id": f"in.({','.join(company_ids)})",
                    "role": "eq.company_admin",
                    "status": "eq.pending",
                    "order": "created_at.desc",
                },
            )
            for invite in invite_rows:
                invites_by_company.setdefault(invite["company_id"], invite)
        items = [{**link, "company": companies.get(link["company_id"]), "invite": invites_by_company.get(link["company_id"]), "contract": _contract_from_link(link), "contract_label": _contract_label(link)} for link in links]
        return {"ok": True, "data": {"items": items}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body or "settlement_cycle" in exc.body or "unit_price" in exc.body or "PGRST204" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0008_mealledger_v23.sql, 0010_merchant_company_contract.sql 적용 후 장부업체를 관리할 수 있어요") from exc
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
        invite_code = _ensure_company_invite_code(repo, company["id"])
        link = _upsert_link(repo, merchant_id, company["id"], actor.id)
        invite = repo.client.rest_post("invites", {
            "token": _token(),
            "role": "company_admin",
            "company_id": company["id"],
            "phone": payload.owner_phone,
            "invited_by": actor.id,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        })[0]
        return {"ok": True, "data": {"company": {**company, "invite_code": invite_code}, "link": link, "invite": {**invite, "delivery": "manual"}}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0008_mealledger_v23.sql 적용 후 장부업체를 만들 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "장부업체 생성 중 오류가 발생했어요") from exc


@router.patch("/companies/{company_id}/contract")
def update_company_contract(company_id: str, payload: MerchantCompanyContractUpdateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        link = _require_company_link(repo, merchant_id, company_id)
        values = {
            "settlement_cycle": payload.settlement_cycle,
            "settlement_day": payload.settlement_day if payload.settlement_cycle == "day" else None,
            "unit_price": payload.unit_price,
        }
        updated = repo.client.rest_patch("merchant_companies", {"id": f"eq.{link['id']}"}, values)[0]
        return {"ok": True, "data": {"link": updated, "contract": _contract_from_link(updated), "contract_label": _contract_label(updated)}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        if "settlement_cycle" in exc.body or "unit_price" in exc.body or "PGRST204" in exc.body or "PGRST205" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0010_merchant_company_contract.sql 적용 후 계약 정보를 저장할 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "계약 정보를 저장하는 중 오류가 발생했어요") from exc


@router.get("/companies/{company_id}/summary")
def vendor_summary(company_id: str, from_: str | None = Query(default=None, alias="from"), to: str | None = None, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        link = _require_company_link(repo, merchant_id, company_id)
        _, _, from_date, to_date = _iso_bounds(from_, to)
        summary = repo.client.rpc("merchant_ledger_summary", {
            "p_merchant_id": merchant_id, "p_company_id": company_id,
            "p_period_from": from_date.isoformat(), "p_period_to": to_date.isoformat(),
        })
        settlements = repo.client.rest_get("settlements", {
            "select": "total_amount,status", "merchant_id": f"eq.{merchant_id}", "company_id": f"eq.{company_id}",
        })
        unsettled_amount = sum(int(row.get("total_amount") or 0) for row in settlements if row.get("status") != "paid")
        return {"ok": True, "data": {
            "period": {"from": from_date.isoformat(), "to": to_date.isoformat()},
            "total_amount": int(summary.get("total_amount") or 0),
            "total_count": int(summary.get("total_count") or 0),
            "cancel_count": int(summary.get("cancel_count") or 0),
            "unsettled_amount": unsettled_amount,
            "contract": _contract_from_link(link),
        }, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "업체 요약을 불러오는 중 오류가 발생했어요") from exc


@router.get("/companies/{company_id}/transactions")
def vendor_transactions(company_id: str, from_: str | None = Query(default=None, alias="from"), to: str | None = None, q: str | None = None, cursor: str | None = None, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        _require_company_link(repo, merchant_id, company_id)
        items, _, _ = _load_vendor_transactions(repo, merchant_id, company_id, from_, to, q)
        return {"ok": True, "data": {"days": _group_days(items), "next_cursor": None}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "업체 거래내역을 불러오는 중 오류가 발생했어요") from exc


@router.get("/companies/{company_id}/settlements")
def vendor_settlements(company_id: str, from_: str | None = Query(default=None, alias="from"), to: str | None = None, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        _require_company_link(repo, merchant_id, company_id)
        rows = repo.client.rest_get("settlements", {
            "select": "id,company_id,merchant_id,period_ym,period_from,period_to,tx_count,total_amount,status,paid_at",
            "merchant_id": f"eq.{merchant_id}", "company_id": f"eq.{company_id}",
            "order": "period_from.desc,period_ym.desc",
        })
        filter_from = _parse_date(from_, date.min) if from_ else None
        filter_to = _parse_date(to, date.max) if to else None
        if filter_from and filter_to and filter_from > filter_to:
            raise _error(400, "INVALID_DATE_RANGE", "시작일은 종료일보다 늦을 수 없어요")
        items = []
        for row in rows:
            if row.get("period_from") and row.get("period_to"):
                period_from = str(row["period_from"])[:10]
                period_to = str(row["period_to"])[:10]
            else:
                period_from, period_to = _settlement_period_bounds(row["period_ym"])
            row_from, row_to = date.fromisoformat(period_from), date.fromisoformat(period_to)
            if filter_from and row_to < filter_from:
                continue
            if filter_to and row_from > filter_to:
                continue
            items.append({
                "id": row["id"],
                "period_from": period_from,
                "period_to": period_to,
                "amount": row.get("total_amount") or 0,
                "tx_count": row.get("tx_count") or 0,
                "status": _settlement_status(row),
                "paid_at": row.get("paid_at"),
            })
        return {"ok": True, "data": {"items": items}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "정산이력을 불러오는 중 오류가 발생했어요") from exc


@router.post("/companies/{company_id}/settlements")
def create_vendor_settlement(company_id: str, payload: SettlementCreateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        _require_company_link(repo, merchant_id, company_id)
        _, _, period_from, period_to = _iso_bounds(payload.period_from, payload.period_to)
        row = repo.client.rpc("create_merchant_settlement", {
            "p_merchant_id": merchant_id, "p_company_id": company_id,
            "p_period_from": period_from.isoformat(), "p_period_to": period_to.isoformat(),
        })
        return {"ok": True, "data": {"settlement": row}, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        if "SETTLEMENT_PERIOD_OVERLAP" in exc.body:
            raise _error(409, "SETTLEMENT_PERIOD_OVERLAP", "이미 정산된 기간과 겹쳐요") from exc
        if "INVALID_DATE_RANGE" in exc.body:
            raise _error(400, "INVALID_DATE_RANGE", "시작일은 종료일보다 늦을 수 없어요") from exc
        if "period_from" in exc.body or "period_to" in exc.body or "PGRST204" in exc.body or "create_merchant_settlement" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0016 마이그레이션 적용 후 기간 정산을 생성할 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "기간 정산을 생성하는 중 오류가 발생했어요") from exc


@router.post("/companies/{company_id}/settlements/{settlement_id}/confirm-payment")
def confirm_vendor_settlement_payment(company_id: str, settlement_id: str, payload: SettlementPaymentConfirmRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        _require_company_link(repo, merchant_id, company_id)
        rows = repo.client.rest_get("settlements", {"select": "id,company_id,merchant_id", "id": f"eq.{settlement_id}", "company_id": f"eq.{company_id}", "merchant_id": f"eq.{merchant_id}", "limit": "1"})
        if not rows:
            raise _error(404, "SETTLEMENT_NOT_FOUND", "정산 회차를 찾을 수 없어요")
        paid_at = payload.paid_at if "T" in payload.paid_at else f"{payload.paid_at}T00:00:00+00:00"
        updated = repo.client.rest_patch("settlements", {"id": f"eq.{settlement_id}"}, {"status": "paid", "paid_at": paid_at})[0]
        return {"ok": True, "data": {"settlement": updated}, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "입금확인 처리 중 오류가 발생했어요") from exc


@router.get("/companies/{company_id}/export")
def export_vendor_transactions(company_id: str, format: str = Query(pattern="^(xlsx|pdf)$"), from_: str | None = Query(default=None, alias="from"), to: str | None = None, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        _require_company_link(repo, merchant_id, company_id)
        company_name = _company_name(repo, company_id)
        items, from_date, to_date = _load_vendor_transactions(repo, merchant_id, company_id, from_, to)
        total_amount = sum(int(item.get("amount") or 0) for item in items)
        rows = [
            ["기간", from_date.isoformat(), to_date.isoformat()],
            ["총액", str(total_amount), "건수", str(len(items))],
            ["날짜", "시간", "부서", "이름", "사번", "메뉴/내역", "결제구분", "금액"],
        ]
        for item in items:
            created = str(item.get("created_at") or "")
            rows.append([created[:10], created[11:16], item.get("department", "-"), item.get("employee_name", ""), item.get("employee_no", ""), item.get("menu", ""), item.get("pay_type", ""), str(item.get("amount", 0))])
        ym = from_date.isoformat()[:7].replace("-", "")
        base = f"{_safe_filename(company_name)}_{'거래내역' if format == 'xlsx' else '청구서'}_{ym}.{format}"
        disposition = f"attachment; filename=\"vendor_{ym}.{format}\"; filename*=UTF-8''{quote(base)}"
        if format == "xlsx":
            return Response(
                _xlsx_bytes(rows),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": disposition},
            )
        pdf_lines = [f"MEALLEDGER Invoice - {company_name}", f"Period: {from_date.isoformat()} ~ {to_date.isoformat()}", f"Total: {total_amount:,} KRW", f"Count: {len(items)}", "날짜 | 시간 | 부서 | 이름 | 사번 | 메뉴/내역 | 결제구분 | 금액"]
        pdf_lines.extend([" | ".join(str(value) for value in row) for row in rows[3:]])
        return Response(_pdf_bytes(pdf_lines), media_type="application/pdf", headers={"Content-Disposition": disposition})
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "내보내기 파일을 만드는 중 오류가 발생했어요") from exc


@router.get("/transactions")
def list_transactions(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        rows = repo.client.rest_get(
            "meal_transactions",
            {
                "select": "id,user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,flags,product_name,product_price,pay_type,voucher_id,created_at",
                "merchant_id": f"eq.{merchant_id}",
                "order": "created_at.desc",
                "limit": "50",
            },
        )
        toss_rows = repo.client.rest_get(
            "toss_payment_orders",
            {
                "select": "id,order_id,user_id,merchant_id,amount,status,payment_method,product_name,approved_at,created_at",
                "merchant_id": f"eq.{merchant_id}",
                "status": "eq.done",
                "order": "approved_at.desc",
                "limit": "50",
            },
        )
        rows.extend({
            "id": f"toss-{item['id']}",
            "user_id": item.get("user_id"),
            "company_id": None,
            "merchant_id": item.get("merchant_id"),
            "amount": -abs(int(item.get("amount") or 0)),
            "kind": "toss_payment",
            "tx_code": str(item.get("order_id") or "")[-8:],
            "meal_window": item.get("payment_method") or "토스페이먼츠",
            "flags": {"payment_provider": "toss"},
            "product_name": item.get("product_name"),
            "product_price": int(item.get("amount") or 0),
            "created_at": item.get("approved_at") or item.get("created_at"),
        } for item in toss_rows)
        rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        user_ids = sorted({str(item["user_id"]) for item in rows if item.get("user_id")})
        users = {}
        if user_ids:
            user_rows = repo.client.rest_get("app_users", {"select": "id,display_name,employee_no", "id": f"in.({','.join(user_ids)})"})
            users = {item["id"]: item for item in user_rows}
        for item in rows:
            user = users.get(item.get("user_id"), {})
            item["employee_name"] = user.get("display_name") or "직원"
            item["employee_no"] = user.get("employee_no") or str(item.get("user_id") or "")[:8] or "-"
        total_count = repo.client.rpc("merchant_transaction_count", {"p_merchant_id": merchant_id})
        return {"ok": True, "data": {"items": rows[:50], "total_count": int(total_count or 0)}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "거래내역을 불러오는 중 오류가 발생했어요") from exc


@router.get("/transactions/{transaction_id}")
def transaction_detail(transaction_id: str, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        rows = repo.client.rest_get("meal_transactions", {
            "select": "id,user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,product_name,product_price,pay_type,voucher_id,created_at",
            "id": f"eq.{transaction_id}", "merchant_id": f"eq.{merchant_id}", "limit": "1",
        })
        if not rows:
            raise _error(404, "TRANSACTION_NOT_FOUND", "거래를 찾을 수 없어요")
        item = rows[0]
        users = repo.client.rest_get("app_users", {"select": "id,display_name,employee_no", "id": f"eq.{item['user_id']}", "limit": "1"})
        user = users[0] if users else {}
        item["employee_name"] = user.get("display_name") or "직원"
        item["employee_no"] = user.get("employee_no") or str(item.get("user_id") or "")[:8] or "-"
        item["amount"] = abs(int(item.get("amount") or item.get("product_price") or 0))
        if item.get("pay_type") == "voucher":
            item["remaining"] = int(repo.client.rpc("voucher_balance", {"p_user_id": item["user_id"]}) or 0)
        return {"ok": True, "data": item, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "거래 알림 상세를 불러오지 못했어요") from exc
