from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.schemas import MerchantCompanyContractUpdateRequest, MerchantCompanyCreateAndLinkRequest, MerchantCompanyLinkRequest, SettlementPaymentConfirmRequest
from app.services.join_flow import JoinErrorCode, JoinFlowError

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


def _parse_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    return date.fromisoformat(value[:10])


def _month_range(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    start = today.replace(day=1)
    next_month = date(today.year + (1 if today.month == 12 else 0), 1 if today.month == 12 else today.month + 1, 1)
    return start, next_month - timedelta(days=1)


def _iso_bounds(from_: str | None, to: str | None) -> tuple[str, str, date, date]:
    default_from, default_to = _month_range()
    from_date = _parse_date(from_, default_from)
    to_date = _parse_date(to, default_to)
    return f"{from_date.isoformat()}T00:00:00+00:00", f"{to_date.isoformat()}T23:59:59+00:00", from_date, to_date


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


def _load_vendor_transactions(repo: JoinRepository, merchant_id: str, company_id: str, from_: str | None, to: str | None, q: str | None = None) -> tuple[list[dict], date, date]:
    from_iso, to_iso, from_date, to_date = _iso_bounds(from_, to)
    rows = repo.client.rest_get(
        "meal_transactions",
        {
            "select": "id,user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,flags,product_name,product_price,created_at",
            "merchant_id": f"eq.{merchant_id}",
            "company_id": f"eq.{company_id}",
            "and": f"(created_at.gte.{from_iso},created_at.lte.{to_iso})",
            "order": "created_at.desc",
            "limit": "1000",
        },
    )
    user_ids = sorted({row["user_id"] for row in rows if row.get("user_id")})
    users = {}
    if user_ids:
        user_rows = repo.client.rest_get("app_users", {"select": "id,display_name", "id": f"in.({','.join(user_ids)})"})
        users = {row["id"]: row for row in user_rows}
    query = (q or "").strip().lower()
    items = []
    for row in rows:
        user = users.get(row.get("user_id"), {})
        employee_name = user.get("display_name") or "직원"
        employee_no = str(row.get("user_id") or "")[:8]
        if query and query not in f"{employee_name} {employee_no}".lower():
            continue
        amount = _tx_amount(row)
        items.append({
            **row,
            "amount": amount,
            "employee_name": employee_name,
            "employee_no": employee_no,
            "menu": row.get("product_name") or row.get("meal_window") or "식대 사용",
            "pay_type": "식권" if row.get("kind") == "spend" else "장부",
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
    period = row.get("period_ym", "")
    try:
        y, m = [int(part) for part in period.split("-")[:2]]
        due = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 10)
    except Exception:
        due = date.today()
    return "연체" if date.today() > due else "입금대기"


def _ensure_settlements(repo: JoinRepository, merchant_id: str, company_id: str) -> list[dict]:
    tx_rows = repo.client.rest_get(
        "meal_transactions",
        {
            "select": "id,amount,kind,created_at",
            "merchant_id": f"eq.{merchant_id}",
            "company_id": f"eq.{company_id}",
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
        {"select": "id,company_id,merchant_id,period_ym,tx_count,total_amount,status,paid_at", "merchant_id": f"eq.{merchant_id}", "company_id": f"eq.{company_id}", "order": "period_ym.desc"},
    )
    existing_by_period = {row["period_ym"]: row for row in existing}
    for ym, summary in aggregates.items():
        if ym in existing_by_period:
            row = existing_by_period[ym]
            if row.get("status") != "paid" and (row.get("tx_count") != summary["tx_count"] or row.get("total_amount") != summary["total_amount"]):
                repo.client.rest_patch("settlements", {"id": f"eq.{row['id']}"}, {"tx_count": summary["tx_count"], "total_amount": summary["total_amount"]})
        else:
            repo.client.rest_post("settlements", {"company_id": company_id, "merchant_id": merchant_id, "period_ym": ym, "tx_count": summary["tx_count"], "total_amount": summary["total_amount"], "status": "confirmed"})
    return repo.client.rest_get(
        "settlements",
        {"select": "id,company_id,merchant_id,period_ym,tx_count,total_amount,status,paid_at", "merchant_id": f"eq.{merchant_id}", "company_id": f"eq.{company_id}", "order": "period_ym.desc"},
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
    safe_lines = [line.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
    text = "\n".join(f"0 -16 Td ({line}) Tj" for line in safe_lines)
    stream = f"BT /F1 11 Tf 50 780 Td {text} ET".encode("latin-1")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
        b"5 0 obj << /Length " + str(len(stream)).encode() + b" >> stream\n" + stream + b"\nendstream endobj",
    ]
    out = BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(out.tell())
        out.write(obj + b"\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return out.getvalue()


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value).strip("_") or "vendor"


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
        items, from_date, to_date = _load_vendor_transactions(repo, merchant_id, company_id, from_, to)
        settlements = _ensure_settlements(repo, merchant_id, company_id)
        total_amount = sum(int(item.get("amount") or 0) for item in items)
        cancel_count = len([item for item in items if item.get("status") == "refund"])
        unsettled_amount = sum(int(row.get("total_amount") or 0) for row in settlements if row.get("status") != "paid")
        return {"ok": True, "data": {
            "period": {"from": from_date.isoformat(), "to": to_date.isoformat()},
            "total_amount": total_amount,
            "total_count": len(items),
            "cancel_count": cancel_count,
            "unsettled_amount": unsettled_amount,
            "next_settlement_date": _next_settlement_date_for_contract(link),
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
def vendor_settlements(company_id: str, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        _require_company_link(repo, merchant_id, company_id)
        rows = _ensure_settlements(repo, merchant_id, company_id)
        items = []
        for row in rows:
            period_from, period_to = _settlement_period_bounds(row["period_ym"])
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
            ["일자", "시각", "직원", "사번", "메뉴", "결제구분", "금액", "상태"],
        ]
        for item in items:
            created = str(item.get("created_at") or "")
            rows.append([created[:10], created[11:16], item.get("employee_name", ""), item.get("employee_no", ""), item.get("menu", ""), item.get("pay_type", ""), str(item.get("amount", 0)), item.get("status", "")])
        ym = from_date.isoformat()[:7].replace("-", "")
        base = f"{_safe_filename(company_name)}_{'거래내역' if format == 'xlsx' else '청구서'}_{ym}.{format}"
        disposition = f"attachment; filename=\"vendor_{ym}.{format}\"; filename*=UTF-8''{quote(base)}"
        if format == "xlsx":
            return Response(
                _xlsx_bytes(rows),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": disposition},
            )
        pdf_lines = [f"MEALLEDGER Invoice - {company_name}", f"Period: {from_date.isoformat()} ~ {to_date.isoformat()}", f"Total: {total_amount:,} KRW", f"Count: {len(items)}"]
        pdf_lines.extend([f"{row[0]} {row[1]} {row[2]} {row[4]} {row[6]}" for row in rows[3:80]])
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
