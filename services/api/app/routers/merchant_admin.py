from __future__ import annotations

import base64
import html
import secrets
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.auth import bearer_token
from app.config import get_settings
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.schemas import MerchantCompanyContractUpdateRequest, MerchantCompanyCreateAndLinkRequest, MerchantCompanyLinkRequest, MerchantRefundRequest, SettlementCreateRequest, SettlementPaymentConfirmRequest
from app.services.join_flow import JoinErrorCode, JoinFlowError
from app.services.company_invites import send_company_invitation
from app.services.refunds import calculate_refund
from app.services.kiwoom_payment import KiwoomPaymentError, cancel_payment

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
    return repo.client.rest_get("companies", {"select": "id,name,biz_reg_no,status,contact_email,contact_phone,created_at", "id": f"in.({','.join(ids)})"})


def _merchant_name(repo: JoinRepository, merchant_id: str) -> str:
    rows = repo.client.rest_get(
        "merchants", {"select": "name", "id": f"eq.{merchant_id}", "limit": "1"}
    )
    return (rows[0].get("name") if rows else None) or "그린잇 식당"


def _deliver_company_invite(
    repo: JoinRepository,
    invite: dict,
    company_name: str,
    *,
    sender_name: str,
    reply_to: str | None,
) -> dict:
    delivery = send_company_invitation(
        email=invite["email"],
        company_name=company_name,
        token=invite["token"],
        sender_name=sender_name,
        reply_to=reply_to,
    )
    values = {"email_send_status": delivery.status, "email_message_id": delivery.message_id,
              "email_error": delivery.error,
              "email_sent_at": datetime.now(timezone.utc).isoformat() if delivery.status == "sent" else None}
    updated = repo.client.rest_patch("invites", {"id": f"eq.{invite['id']}"}, values)
    return updated[0] if updated else {**invite, **values}


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
            "select": "id,user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,flags,product_name,product_price,pay_type,company_subsidy_amount,restaurant_subsidy_amount,employee_paid_amount,created_at",
            "merchant_id": f"eq.{merchant_id}",
            "company_id": f"eq.{company_id}",
            "pay_type": "in.(ledger,subsidized)",
            "and": f"(created_at.gte.{from_iso},created_at.lt.{to_iso})",
            "order": "created_at.desc",
        },
    )
    user_ids = sorted({row["user_id"] for row in rows if row.get("user_id")})
    users = {}
    if user_ids:
        user_rows = repo.client.rest_get("app_users", {"select": "id,display_name,employee_no,department,group_id", "id": f"in.({','.join(user_ids)})"})
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
        department = user.get("department") or groups.get(user.get("group_id")) or "-"
        if query and query not in f"{department} {employee_name} {employee_no}".lower():
            continue
        amount = _tx_amount(row)
        if row.get("pay_type") == "subsidized":
            company_charge = int(row.get("company_subsidy_amount") or 0)
            amount = company_charge if row.get("kind") == "spend" else -company_charge
        items.append({
            **row,
            "created_at": _kst_iso(row.get("created_at")),
            "amount": amount,
            "employee_name": employee_name,
            "employee_no": employee_no,
            "department": department,
            "menu": row.get("product_name") or row.get("meal_window") or "식대 사용",
            "pay_type": "보조금" if row.get("pay_type") == "subsidized" else ("식권" if row.get("pay_type") == "voucher" else "장부"),
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
            "select": "id,amount,kind,pay_type,company_subsidy_amount,created_at",
            "merchant_id": f"eq.{merchant_id}",
            "company_id": f"eq.{company_id}",
            "pay_type": "in.(ledger,subsidized)",
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
        charge = int(row.get("company_subsidy_amount") or 0) if row.get("pay_type") == "subsidized" else _tx_amount(row)
        bucket["total_amount"] += -charge if row.get("kind") in {"refund", "cancel"} else charge
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
    # Bundle the Korean font in the service so Render/containers do not depend
    # on an OS-level CJK font package. WeasyPrint embeds this data-URI font in
    # the generated PDF, preventing Korean glyphs from becoming boxes.
    import importlib

    HTML = importlib.import_module("weasyprint").HTML
    font_path = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "NanumGothic-Regular.ttf"
    font_data = base64.b64encode(font_path.read_bytes()).decode("ascii")

    body = "".join(f"<div>{html.escape(line)}</div>" for line in lines)
    document = f"""<!doctype html><html lang='ko'><meta charset='utf-8'><style>
      @font-face {{ font-family: 'MealLedger Korean'; src: url(data:font/ttf;base64,{font_data}) format('truetype'); }}
      @page {{ size: A4 landscape; margin: 18mm; }}
      body {{ font-family: 'MealLedger Korean', sans-serif; font-size: 10px; color: #14351f; }}
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
                    "select": "id,token,company_id,phone,email,status,email_send_status,email_sent_at,email_error,expires_at,accepted_at,created_at",
                    "company_id": f"in.({','.join(company_ids)})",
                    "role": "eq.company_admin",
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
        company = repo.client.rest_post("companies", {
            "name": payload.name.strip(),
            "status": "invited",
            "contact_email": payload.contact_email.strip().lower(),
            "contact_phone": (payload.contact_phone or payload.owner_phone or "").strip() or None,
        })[0]
        invite_code = _ensure_company_invite_code(repo, company["id"])
        link = _upsert_link(repo, merchant_id, company["id"], actor.id)
        invite = repo.client.rest_post("invites", {
            "token": _token(),
            "role": "company_admin",
            "company_id": company["id"],
            "phone": company.get("contact_phone"),
            "email": company["contact_email"],
            "invited_by": actor.id,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        })[0]
        invite = _deliver_company_invite(
            repo,
            invite,
            company["name"],
            sender_name=_merchant_name(repo, merchant_id),
            reply_to=actor.email or None,
        )
        return {"ok": True, "data": {"company": {**company, "invite_code": invite_code}, "link": link, "invite": invite}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        if "PGRST205" in exc.body:
            raise _error(400, "MIGRATION_REQUIRED", "0008_mealledger_v23.sql 적용 후 장부업체를 만들 수 있어요") from exc
        raise _error(502, "SUPABASE_ERROR", "장부업체 생성 중 오류가 발생했어요") from exc


@router.post("/companies/{company_id}/invite/resend")
def resend_company_invite(company_id: str, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor, merchant_id = _merchant_admin(repo, token)
        _require_company_link(repo, merchant_id, company_id)
        rows = repo.client.rest_get("invites", {"select": "*", "company_id": f"eq.{company_id}",
            "role": "eq.company_admin", "order": "created_at.desc", "limit": "1"})
        if not rows:
            raise _error(404, "INVITE_NOT_FOUND", "재전송할 초대를 찾을 수 없어요")
        invite = rows[0]
        if invite.get("status") != "pending":
            raise _error(409, "INVITE_ALREADY_ACCEPTED", "이미 수락된 초대는 재전송할 수 없어요")
        try:
            expires_at = datetime.fromisoformat(str(invite["expires_at"]).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise _error(409, "INVITE_EXPIRED", "만료된 초대는 재전송할 수 없어요") from exc
        if expires_at <= datetime.now(timezone.utc):
            repo.client.rest_patch("invites", {"id": f"eq.{invite['id']}"}, {"status": "expired"})
            raise _error(409, "INVITE_EXPIRED", "만료된 초대는 재전송할 수 없어요")
        if not invite.get("email"):
            raise _error(409, "INVITE_EMAIL_MISSING", "이메일이 없는 기존 초대는 재전송할 수 없어요")
        delivered = _deliver_company_invite(
            repo,
            invite,
            _company_name(repo, company_id),
            sender_name=_merchant_name(repo, merchant_id),
            reply_to=actor.email or None,
        )
        return {"ok": True, "data": {"invite": delivered}, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "초대 이메일을 재전송하는 중 오류가 발생했어요") from exc


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
            ["날짜", "시간", "부서", "이름", "사번", "메뉴/내역", "금액"],
        ]
        for item in items:
            created = str(item.get("created_at") or "")
            rows.append([created[:10], created[11:16], item.get("department", "-"), item.get("employee_name", ""), item.get("employee_no", ""), item.get("menu", ""), str(item.get("amount", 0))])
        ym = from_date.isoformat()[:7].replace("-", "")
        base = f"{_safe_filename(company_name)}_{'거래내역' if format == 'xlsx' else '청구서'}_{ym}.{format}"
        disposition = f"attachment; filename=\"vendor_{ym}.{format}\"; filename*=UTF-8''{quote(base)}"
        if format == "xlsx":
            return Response(
                _xlsx_bytes(rows),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": disposition},
            )
        pdf_lines = ["Greeneat 청구서 - 돈토식당", f"정산 기간: {from_date.isoformat()} ~ {to_date.isoformat()}", f"총 청구금액: {total_amount:,}원", f"거래 건수: {len(items)}건", "날짜 | 시간 | 부서 | 이름 | 사번 | 메뉴/내역 | 금액"]
        pdf_lines.extend([" | ".join(str(value) for value in row) for row in rows[3:]])
        return Response(_pdf_bytes(pdf_lines), media_type="application/pdf", headers={"Content-Disposition": disposition})
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "내보내기 파일을 만드는 중 오류가 발생했어요") from exc


_REFUND_ORDER_SELECT = "id,order_id,user_id,merchant_id,company_id,product_name,amount,status,pay_type,provider_payment_key,payment_method,refund_account,approved_at,created_at,voucher_count,paid_voucher_count,bonus_voucher_count,point_amount"


def _order_quotes(repo: JoinRepository, orders: list[dict]) -> list[dict]:
    order_ids = [str(order["id"]) for order in orders]
    vouchers = _paged_get(repo, "vouchers", {
        "select": "id,order_id,issue_index,status", "order_id": f"in.({','.join(order_ids)})",
    }) if order_ids else []
    by_order: dict[str, list[dict]] = {}
    for voucher in vouchers:
        by_order.setdefault(str(voucher["order_id"]), []).append(voucher)
    result = []
    for order in orders:
        order_vouchers = by_order.get(str(order["id"]), [])
        quote = calculate_refund(order, order_vouchers)
        if not quote.refundable:
            continue
        used_count = sum(1 for voucher in order_vouchers if voucher.get("status") == "used")
        unused_count = sum(1 for voucher in order_vouchers if voucher.get("status") == "unused")
        result.append({
            "purchase_order_id": order["order_id"], "account_id": order["user_id"],
            "product_name": order.get("product_name"), "pay_type": order.get("pay_type"),
            "purchased_at": order.get("approved_at") or order.get("created_at"),
            "paid_amount": int(order.get("amount") or 0), "point_amount": quote.point_amount,
            "total_count": len(order_vouchers), "used_count": used_count, "remaining_count": unused_count,
            "refundable": quote.refundable, "refund_amount": quote.refund_amount,
            "refundable_voucher_count": quote.refunded_voucher_count,
            "forfeited_bonus_count": quote.forfeited_voucher_count, "reason": quote.reason,
        })
    return result


@router.get("/customers/search")
def search_refund_customers(query: str = Query(min_length=1, max_length=80), token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        orders = _paged_get(repo, "payment_orders", {
            "select": "user_id", "merchant_id": f"eq.{merchant_id}",
            "pay_type": "in.(voucher,subsidized)", "status": "in.(done,refunded)",
        })
        user_ids = sorted({str(row["user_id"]) for row in orders if row.get("user_id")})
        users = repo.client.rest_get("app_users", {
            "select": "id,display_name,phone,role,status", "id": f"in.({','.join(user_ids)})",
        }) if user_ids else []
        needle = query.strip().lower()
        items = [row for row in users if needle in f"{row.get('display_name') or ''} {row.get('phone') or ''}".lower()]
        return {"ok": True, "data": {"items": items[:30]}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "고객을 검색하지 못했어요") from exc


@router.get("/customers/{account_id}/refundable-orders")
def refundable_orders(account_id: str, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        orders = _paged_get(repo, "payment_orders", {
            "select": _REFUND_ORDER_SELECT, "merchant_id": f"eq.{merchant_id}",
            "user_id": f"eq.{account_id}", "pay_type": "in.(voucher,subsidized)",
            "status": "eq.done", "order": "approved_at.desc,created_at.desc",
        })
        return {"ok": True, "data": {"items": _order_quotes(repo, orders)}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "환불 가능 주문을 불러오지 못했어요") from exc


@router.post("/refunds")
def refund_purchase_order(payload: MerchantRefundRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    claim = None
    try:
        actor, merchant_id = _merchant_admin(repo, token)
        # Re-read ownership and current state immediately before the locked claim.
        rows = repo.client.rest_get("payment_orders", {
            "select": _REFUND_ORDER_SELECT, "order_id": f"eq.{payload.order_id}",
            "merchant_id": f"eq.{merchant_id}", "user_id": f"eq.{payload.account_id}", "limit": "1",
        })
        if not rows:
            raise _error(404, "ORDER_NOT_FOUND", "해당 고객의 구매 주문을 찾을 수 없어요")
        if int(rows[0].get("amount") or 0) > 0 and not rows[0].get("provider_payment_key"):
            raise _error(409, "PAYMENT_KEY_MISSING", "결제 거래번호가 없어 자동 환불할 수 없어요")
        payment_method = str(rows[0].get("payment_method") or "").strip().upper()
        if int(rows[0].get("amount") or 0) > 0 and not payment_method:
            raise _error(409, "PAYMENT_METHOD_MISSING", "원 결제수단이 없어 자동 환불할 수 없어요")
        account = payload.refund_account.model_dump() if payload.refund_account else rows[0].get("refund_account")
        claim = repo.client.rpc("claim_purchase_order_refund", {
            "p_order_id": rows[0]["id"], "p_merchant_id": merchant_id,
            "p_user_id": payload.account_id, "p_requested_by": actor.id,
            "p_refund_account": account,
        })
        pg_response = None
        amount = int(claim.get("refund_amount") or 0)
        if amount > 0:
            transaction_id = claim.get("provider_payment_key")
            if not transaction_id:
                raise _error(409, "PAYMENT_KEY_MISSING", "결제 거래번호가 없어 자동 환불할 수 없어요")
            settings = get_settings()
            pg_response = cancel_payment(
                settings.kiwoompay_base_url,
                settings.kiwoompay_authorization_key,
                settings.kiwoompay_cpid,
                transaction_id,
                amount,
                pay_method=payment_method,
                cancel_reason="식권구매환불",
            )
        result = repo.client.rpc("finalize_purchase_order_refund", {
            "p_refund_request_id": claim["refund_request_id"],
            "p_merchant_id": merchant_id, "p_pg_response": pg_response,
        })
        return {"ok": True, "data": result, "error": None}
    except HTTPException:
        raise
    except KiwoomPaymentError as exc:
        if claim:
            try:
                repo.client.rest_patch("refund_requests", {"id": f"eq.{claim['refund_request_id']}", "status": "eq.processing"}, {
                    "status": "failed", "failure_code": exc.code, "failure_message": exc.message,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
            except SupabaseHttpError:
                pass
        raise _error(exc.status if 400 <= exc.status < 500 else 502, exc.code, exc.message) from exc
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        code_map = {
            "ORDER_ALREADY_USED": (409, "ORDER_ALREADY_USED", "이미 사용한 보조금 식권은 환불할 수 없어요"),
            "PAID_VOUCHERS_EXHAUSTED": (409, "PAID_VOUCHERS_EXHAUSTED", "유료 식권을 모두 사용해 환불할 금액이 없어요"),
            "REFUND_ALREADY_REQUESTED": (409, "REFUND_ALREADY_REQUESTED", "이미 처리 중이거나 완료된 환불이에요"),
        }
        for marker, detail in code_map.items():
            if marker in exc.body:
                raise _error(*detail) from exc
        raise _error(502, "REFUND_FAILED", "환불 처리 중 오류가 발생했어요") from exc


def _analytics_bounds(selected: date, granularity: str) -> tuple[datetime, datetime, str]:
    if granularity == "year":
        start = datetime(selected.year, 1, 1, tzinfo=KST)
        end = datetime(selected.year + 1, 1, 1, tzinfo=KST)
        return start, end, "%Y-%m"
    if granularity == "month":
        start = datetime(selected.year, selected.month, 1, tzinfo=KST)
        end_date = date(selected.year + (selected.month == 12), 1 if selected.month == 12 else selected.month + 1, 1)
        return start, datetime.combine(end_date, time.min, tzinfo=KST), "%Y-%m-%d"
    start = datetime.combine(selected, time.min, tzinfo=KST)
    return start, start + timedelta(days=1), "%Y-%m-%dT%H:00"


def _bucket(value: object, pattern: str) -> str:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(KST).strftime(pattern)


def _payment_type_label(value: object) -> str:
    return {"ledger": "장부", "subsidized": "보조금"}.get(str(value or ""), "일반")


def _decorate_transaction_people(repo: JoinRepository, *groups: list[dict]) -> dict[str, dict]:
    rows = [row for group in groups for row in group]
    user_ids = sorted({str(row["user_id"]) for row in rows if row.get("user_id")})
    user_rows = repo.client.rest_get(
        "app_users",
        {"select": "id,display_name,company_id,employee_no,department", "id": f"in.({','.join(user_ids)})"},
    ) if user_ids else []
    users = {row["id"]: row for row in user_rows}
    company_ids = sorted({
        str(company_id)
        for row in rows
        for company_id in (row.get("company_id") or users.get(row.get("user_id"), {}).get("company_id"),)
        if company_id
    })
    company_rows = repo.client.rest_get(
        "companies", {"select": "id,name", "id": f"in.({','.join(company_ids)})"}
    ) if company_ids else []
    companies = {row["id"]: row.get("name") or row["id"] for row in company_rows}
    for row in rows:
        user = users.get(row.get("user_id"), {})
        company_id = row.get("company_id") or user.get("company_id")
        row["employee_name"] = user.get("display_name") or "-"
        row["company_name"] = companies.get(company_id, "일반 고객")
        row["payment_type_label"] = _payment_type_label(row.get("pay_type"))
    return users


@router.get("/payment-history")
def payment_history(date_: str = Query(alias="date"), granularity: str = Query(pattern="^(year|month|day|hour|range)$"), token: str = Depends(bearer_token), end_date: str | None = Query(default=None)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        selected = _parse_date(date_, datetime.now(KST).date())
        if granularity == "range":
            selected_end = _parse_date(end_date, selected)
            if selected_end < selected:
                raise _error(400, "INVALID_DATE_RANGE", "종료일은 시작일보다 빠를 수 없어요")
            start = datetime.combine(selected, time.min, tzinfo=KST)
            end = datetime.combine(selected_end + timedelta(days=1), time.min, tzinfo=KST)
            pattern = "%Y-%m-%d"
        else:
            start, end, pattern = _analytics_bounds(selected, granularity)
        start_iso, end_iso = start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()
        txs = _paged_get(repo, "meal_transactions", {
            "select": "id,user_id,company_id,amount,kind,pay_type,created_at", "merchant_id": f"eq.{merchant_id}",
            "and": f"(created_at.gte.{start_iso},created_at.lt.{end_iso})", "order": "created_at.desc",
        })
        payments = _paged_get(repo, "payment_orders", {
            "select": "id,order_id,user_id,company_id,amount,point_amount,status,pay_type,product_name,payment_method,approved_at,created_at",
            "merchant_id": f"eq.{merchant_id}", "status": "in.(done,refunded)",
            "and": f"(approved_at.gte.{start_iso},approved_at.lt.{end_iso})", "order": "approved_at.desc",
        })
        refunds = _paged_get(repo, "refund_requests", {
            "select": "id,order_id,user_id,refund_amount,point_amount,status,created_at,completed_at",
            "merchant_id": f"eq.{merchant_id}", "status": "eq.completed",
            "and": f"(completed_at.gte.{start_iso},completed_at.lt.{end_iso})", "order": "completed_at.desc",
        })
        refund_order_ids = sorted({str(row["order_id"]) for row in refunds if row.get("order_id")})
        refund_orders = repo.client.rest_get(
            "payment_orders", {"select": "id,pay_type", "id": f"in.({','.join(refund_order_ids)})"}
        ) if refund_order_ids else []
        refund_pay_types = {row["id"]: row.get("pay_type") or "direct" for row in refund_orders}
        for row in refunds:
            row["pay_type"] = refund_pay_types.get(row.get("order_id"), "direct")
        _decorate_transaction_people(repo, txs, payments, refunds)
        series: dict[str, dict[str, int]] = {}
        for row in txs:
            key = _bucket(row["created_at"], pattern)
            item = series.setdefault(key, {"transactions": 0, "transaction_amount": 0, "payments": 0, "payment_amount": 0, "refunds": 0, "refund_amount": 0})
            item["transactions"] += 1; item["transaction_amount"] += _tx_amount(row)
        for row in payments:
            key = _bucket(row.get("approved_at") or row["created_at"], pattern)
            item = series.setdefault(key, {"transactions": 0, "transaction_amount": 0, "payments": 0, "payment_amount": 0, "refunds": 0, "refund_amount": 0})
            item["payments"] += 1; item["payment_amount"] += int(row.get("amount") or 0) + int(row.get("point_amount") or 0)
        for row in refunds:
            key = _bucket(row.get("completed_at") or row["created_at"], pattern)
            item = series.setdefault(key, {"transactions": 0, "transaction_amount": 0, "payments": 0, "payment_amount": 0, "refunds": 0, "refund_amount": 0})
            item["refunds"] += 1; item["refund_amount"] += int(row.get("refund_amount") or 0) + int(row.get("point_amount") or 0)
        points = [{"bucket": key, **series[key]} for key in sorted(series)]
        gross = sum(item["payment_amount"] for item in series.values())
        refunded = sum(item["refund_amount"] for item in series.values())
        tx_series = [{"label": item["bucket"], "value": item["transaction_amount"]} for item in points]
        payment_series = [{"label": item["bucket"], "value": item["payment_amount"] - item["refund_amount"]} for item in points]
        transaction_total = sum(_tx_amount(row) for row in txs)
        is_selected_day = lambda value: datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(KST).date() == selected
        detail_txs = [row for row in txs if is_selected_day(row.get("created_at"))] if granularity in ("day", "hour") else txs
        detail_payments = [row for row in payments if is_selected_day(row.get("approved_at") or row.get("created_at"))] if granularity in ("day", "hour") else payments
        detail_refunds = [row for row in refunds if is_selected_day(row.get("completed_at") or row.get("created_at"))] if granularity in ("day", "hour") else refunds
        payment_items = [*detail_payments, *[{**row, "kind": "refund", "amount": -int(row.get("refund_amount") or 0) - int(row.get("point_amount") or 0), "created_at": row.get("completed_at") or row.get("created_at")} for row in detail_refunds]]
        payment_items.sort(key=lambda row: row.get("created_at") or row.get("approved_at") or "", reverse=True)
        shaped = {
            "transaction": {"total": transaction_total, "count": len(txs), "detail_count": len(detail_txs), "series": tx_series, "items": detail_txs},
            "payment": {"total": gross-refunded, "gross_total": gross, "refund_total": refunded,
                        "count": len(payments), "detail_count": len(payment_items), "series": payment_series, "items": payment_items},
        }
        return {"ok": True, "data": {**shaped, "series": points, "rows": payments, "refunds": refunds, "totals": {
            "transaction_count": len(txs), "transaction_amount": sum(abs(int(row.get("amount") or 0)) for row in txs),
            "payment_count": len(payments), "payment_amount": gross, "refund_count": len(refunds),
            "refund_amount": refunded, "net_payment_amount": gross-refunded,
        }}, "error": None}
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "결제 분석을 불러오지 못했어요") from exc


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
        payment_rows = repo.client.rest_get(
            "payment_orders",
            {
                "select": "id,order_id,user_id,merchant_id,amount,status,pay_type,payment_method,product_name,approved_at,created_at",
                "merchant_id": f"eq.{merchant_id}",
                "status": "eq.done",
                "pay_type": "eq.direct",
                "order": "approved_at.desc",
                "limit": "50",
            },
        )
        rows.extend({
            "id": f"kiwoompay-{item['id']}",
            "user_id": item.get("user_id"),
            "company_id": None,
            "merchant_id": item.get("merchant_id"),
            "amount": -abs(int(item.get("amount") or 0)),
            "kind": "payment",
            "tx_code": str(item.get("order_id") or "")[-8:],
            "meal_window": item.get("payment_method") or "키움페이",
            "flags": {"payment_provider": "kiwoompay"},
            "product_name": item.get("product_name"),
            "product_price": int(item.get("amount") or 0),
            "pay_type": item.get("pay_type") or "direct",
            "created_at": item.get("approved_at") or item.get("created_at"),
        } for item in payment_rows)
        rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        users = _decorate_transaction_people(repo, rows)
        for item in rows:
            user = users.get(str(item.get("user_id") or ""), {})
            item["employee_no"] = user.get("employee_no") or str(item.get("user_id") or "")[:8] or "-"
            item["department"] = user.get("department") or "-"
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
        users = repo.client.rest_get("app_users", {"select": "id,display_name,employee_no,department", "id": f"eq.{item['user_id']}", "limit": "1"})
        user = users[0] if users else {}
        item["employee_name"] = user.get("display_name") or "직원"
        item["employee_no"] = user.get("employee_no") or str(item.get("user_id") or "")[:8] or "-"
        item["department"] = user.get("department") or "-"
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
