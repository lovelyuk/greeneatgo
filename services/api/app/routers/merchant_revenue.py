"""Restaurant revenue on two bases, side by side.

* paid/issued basis  - what the restaurant reports and is paid: voucher payments
  (approved in the period, minus refunds completed in the period) plus tax
  invoices issued in the period. Only money actually paid counts: company points
  used on an order are billed to the company separately and become revenue when
  that is invoiced, so they are left out here and reported as `point_amount`.
  (결제 내역 shows payment + points; this figure is therefore smaller by the points.)
* usage basis        - meals actually served in the period (the dashboard's
  existing 총 매출 figure), per company and for personal customers.

A paid voucher is revenue when it is paid; using it later is not added again on
the paid basis. The two figures therefore differ by design.
"""
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.merchant_admin import KST, _error, _merchant_admin, _paged_get
from app.services.join_flow import JoinFlowError

router = APIRouter(prefix="/admin/merchant/revenue", tags=["merchant-admin"])

MAX_PERIOD_DAYS = 366
DETAIL_LIMIT = 500
PERSONAL = "personal"
PERSONAL_NAME = "개인 고객"
# A tax invoice counts once it is issued; later NTS transmission keeps it issued.
_ISSUED_SETTLEMENT_STATES = ("issued", "nts_sending", "nts_accepted")
_METHOD_LABELS = {"CARD": "카드", "BANK": "계좌이체", "NAVERPAY": "네이버페이", "KAKAOPAY": "카카오페이"}


def _bounds(period_from: date, period_to: date) -> tuple[str, str]:
    if period_from > period_to:
        raise _error(422, "INVALID_DATE_RANGE", "조회 시작일은 종료일보다 늦을 수 없어요")
    if (period_to - period_from).days + 1 > MAX_PERIOD_DAYS:
        raise _error(422, "INVALID_DATE_RANGE", f"조회 기간은 최대 {MAX_PERIOD_DAYS}일까지 선택할 수 있어요")
    start = datetime.combine(period_from, time.min, tzinfo=KST)
    end = datetime.combine(period_to + timedelta(days=1), time.min, tzinfo=KST)
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()


def _int(value) -> int:
    return int(value or 0)


def _usage_amount(row: dict) -> int:
    """Signed amount of one meal on the usage basis (same rule as the dashboard summary)."""
    if row.get("settlement_total_amount") is not None:
        amount = _int(row.get("settlement_total_amount"))
    elif row.get("pay_type") == "subsidized":
        amount = _int(row.get("company_subsidy_amount"))
    else:
        amount = abs(_int(row.get("amount")))
    return amount if row.get("kind") == "spend" else -amount


def _party_of_meal(row: dict) -> str:
    # Company-billed meals belong to the company; a voucher meal is the diner's own.
    return str(row["company_id"]) if row.get("pay_type") in ("ledger", "subsidized") and row.get("company_id") else PERSONAL


def _party_of_order(row: dict) -> str:
    return str(row["company_id"]) if row.get("company_id") else PERSONAL


def _load(repo: JoinRepository, merchant_id: str, start_iso: str, end_iso: str) -> dict:
    """Every row both bases are built from, read once."""
    meals = _paged_get(repo, "meal_transactions", {
        "select": "id,user_id,company_id,amount,kind,pay_type,company_subsidy_amount,settlement_total_amount,meal_window,product_name,created_at",
        "merchant_id": f"eq.{merchant_id}", "kind": "in.(spend,refund,cancel)",
        "and": f"(created_at.gte.{start_iso},created_at.lt.{end_iso})", "order": "created_at.desc,id.desc",
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
    refund_orders = {}
    for index in range(0, len(refund_order_ids), 100):
        chunk = refund_order_ids[index:index + 100]
        for order in repo.client.rest_get("payment_orders", {
            "select": "id,company_id,product_name,payment_method", "id": f"in.({','.join(chunk)})", "merchant_id": f"eq.{merchant_id}",
        }):
            refund_orders[str(order["id"])] = order
    for row in refunds:
        order = refund_orders.get(str(row.get("order_id")), {})
        row["company_id"] = order.get("company_id")
        row["product_name"] = order.get("product_name")
        row["payment_method"] = order.get("payment_method")

    invoices = _paged_get(repo, "tax_invoices", {
        "select": "id,settlement_id,company_id,document_type,write_date,supply_amount,vat_amount,total_amount,nts_confirm_num,issued_at,cancelled_at",
        "merchant_id": f"eq.{merchant_id}", "issued_at": "not.is.null",
        "and": f"(issued_at.gte.{start_iso},issued_at.lt.{end_iso})", "order": "issued_at.desc",
    })
    # Real settlements only: the invoice of a demo settlement is not revenue.
    real_settlements = _paged_get(repo, "normal_settlements", {
        "select": "id,company_id,period_ym,total_amount,settlement_status,tax_invoice_status",
        "merchant_id": f"eq.{merchant_id}", "order": "period_ym.desc,id.asc",
    })
    real_ids = {str(row["id"]) for row in real_settlements}
    invoices = [row for row in invoices if str(row.get("settlement_id")) in real_ids and not row.get("cancelled_at")]
    # Meals already served on the company ledger whose tax invoice is not issued yet (any month).
    unbilled = [row for row in real_settlements
                if row.get("tax_invoice_status") not in _ISSUED_SETTLEMENT_STATES
                and row.get("settlement_status") != "cancelled" and _int(row.get("total_amount")) > 0]
    return {"meals": meals, "payments": payments, "refunds": refunds, "invoices": invoices, "unbilled": unbilled}


def _invoice_amount(row: dict) -> int:
    amount = _int(row.get("total_amount"))
    return -amount if row.get("document_type") == "cancellation" else amount


def _payment_amount(row: dict) -> int:
    """Money paid through the PG. Points are not revenue at payment time."""
    return _int(row.get("amount"))


def _refund_amount(row: dict) -> int:
    return _int(row.get("refund_amount"))


def _company_names(repo: JoinRepository, ids: set[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    ordered = sorted(ids)
    for index in range(0, len(ordered), 100):
        chunk = ordered[index:index + 100]
        for row in repo.client.rest_get("companies", {"select": "id,name", "id": f"in.({','.join(chunk)})"}):
            names[str(row["id"])] = row.get("name") or "거래처"
    return names


def _summarize(repo: JoinRepository, data: dict) -> dict:
    parties: dict[str, dict] = {}

    def party(key: str) -> dict:
        return parties.setdefault(key, {
            "key": key, "payment_amount": 0, "refund_amount": 0, "invoice_amount": 0, "point_amount": 0,
            "usage_amount": 0, "usage_count": 0, "unbilled_amount": 0,
        })

    for row in data["payments"]:
        item = party(_party_of_order(row))
        item["payment_amount"] += _payment_amount(row)
        item["point_amount"] += _int(row.get("point_amount"))
    for row in data["refunds"]:
        item = party(_party_of_order(row))
        item["refund_amount"] += _refund_amount(row)
        item["point_amount"] -= _int(row.get("point_amount"))
    for row in data["invoices"]:
        party(str(row["company_id"]))["invoice_amount"] += _invoice_amount(row)
    for row in data["meals"]:
        item = party(_party_of_meal(row))
        item["usage_amount"] += _usage_amount(row)
        item["usage_count"] += 1 if row.get("kind") == "spend" else -1
    for row in data["unbilled"]:
        party(str(row["company_id"]))["unbilled_amount"] += _int(row.get("total_amount"))

    names = _company_names(repo, {key for key in parties if key != PERSONAL})
    items = []
    for key, item in parties.items():
        item["name"] = PERSONAL_NAME if key == PERSONAL else names.get(key, "거래처")
        item["net_payment_amount"] = item["payment_amount"] - item["refund_amount"]
        item["revenue_amount"] = item["net_payment_amount"] + item["invoice_amount"]
        items.append(item)
    # Companies by paid/issued revenue, personal customers last.
    items.sort(key=lambda item: (item["key"] == PERSONAL, -item["revenue_amount"], -item["usage_amount"], item["name"]))

    total = lambda field: sum(item[field] for item in items)  # noqa: E731
    return {
        "paid_basis": {
            "payment_amount": total("payment_amount"), "payment_count": len(data["payments"]),
            "refund_amount": total("refund_amount"), "refund_count": len(data["refunds"]),
            "net_payment_amount": total("net_payment_amount"),
            "invoice_amount": total("invoice_amount"), "invoice_count": len(data["invoices"]),
            "revenue_amount": total("revenue_amount"),
            # Points used on those orders (net of refunds): excluded from revenue above.
            "point_amount": total("point_amount"),
        },
        "usage_basis": {"amount": total("usage_amount"), "count": total("usage_count")},
        "unbilled": {"amount": total("unbilled_amount"), "count": len(data["unbilled"])},
        "parties": items,
    }


def _people(repo: JoinRepository, ids: set[str]) -> dict[str, dict]:
    people: dict[str, dict] = {}
    ordered = sorted(ids)
    for index in range(0, len(ordered), 100):
        chunk = ordered[index:index + 100]
        for row in repo.client.rest_get("app_users", {"select": "id,display_name,employee_no,department", "id": f"in.({','.join(chunk)})"}):
            people[str(row["id"])] = row
    return people


def _detail(repo: JoinRepository, data: dict, key: str) -> dict:
    payments = [row for row in data["payments"] if _party_of_order(row) == key]
    refunds = [row for row in data["refunds"] if _party_of_order(row) == key]
    invoices = [row for row in data["invoices"] if str(row.get("company_id")) == key]
    meals = [row for row in data["meals"] if _party_of_meal(row) == key]
    unbilled = [row for row in data["unbilled"] if str(row.get("company_id")) == key]
    people = _people(repo, {str(row["user_id"]) for row in [*payments, *refunds, *meals] if row.get("user_id")})

    def person(row: dict) -> dict:
        user = people.get(str(row.get("user_id")), {})
        return {"person_name": user.get("display_name") or "-", "department": user.get("department"),
                "employee_no": user.get("employee_no")}

    entries = [
        *[{"kind": "payment", "at": row.get("approved_at") or row.get("created_at"), "amount": _payment_amount(row),
           "point_amount": _int(row.get("point_amount")),
           "label": row.get("product_name") or "식권 결제",
           "method": _METHOD_LABELS.get(str(row.get("payment_method") or "").upper(), row.get("payment_method") or ""),
           **person(row)} for row in payments],
        *[{"kind": "refund", "at": row.get("completed_at") or row.get("created_at"), "amount": -_refund_amount(row),
           "point_amount": -_int(row.get("point_amount")),
           "label": row.get("product_name") or "환불",
           "method": _METHOD_LABELS.get(str(row.get("payment_method") or "").upper(), row.get("payment_method") or ""),
           **person(row)} for row in refunds],
        *[{"kind": "invoice", "at": row.get("issued_at"), "amount": _invoice_amount(row),
           "label": {"cancellation": "세금계산서 취소", "correction": "수정 세금계산서"}.get(row.get("document_type"), "세금계산서 발행"),
           "method": row.get("nts_confirm_num") or "", "person_name": "-", "department": None, "employee_no": None,
           "supply_amount": _int(row.get("supply_amount")), "vat_amount": _int(row.get("vat_amount")),
           "write_date": row.get("write_date")} for row in invoices],
    ]
    entries.sort(key=lambda row: str(row.get("at") or ""), reverse=True)

    daily: dict[str, dict] = {}
    for row in meals:
        day = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00")).astimezone(KST).date().isoformat()
        item = daily.setdefault(day, {"date": day, "count": 0, "cancel_count": 0, "amount": 0})
        item["amount"] += _usage_amount(row)
        if row.get("kind") == "spend":
            item["count"] += 1
        else:
            item["cancel_count"] += 1
    usage_items = [{
        "id": row.get("id"), "at": row.get("created_at"), "kind": row.get("kind"), "pay_type": row.get("pay_type"),
        "item": row.get("meal_window") or row.get("product_name") or "-", "amount": _usage_amount(row), **person(row),
    } for row in meals[:DETAIL_LIMIT]]

    paid = sum(row["amount"] for row in entries if row["kind"] == "payment")
    refunded = -sum(row["amount"] for row in entries if row["kind"] == "refund")
    invoiced = sum(row["amount"] for row in entries if row["kind"] == "invoice")
    return {
        "paid_basis": {"payment_amount": paid, "refund_amount": refunded, "net_payment_amount": paid - refunded,
                       "invoice_amount": invoiced, "revenue_amount": paid - refunded + invoiced,
                       "entries": entries[:DETAIL_LIMIT], "entry_count": len(entries)},
        "usage_basis": {"amount": sum(_usage_amount(row) for row in meals),
                        "count": sum(1 for row in meals if row.get("kind") == "spend"),
                        "cancel_count": sum(1 for row in meals if row.get("kind") != "spend"),
                        "daily": sorted(daily.values(), key=lambda item: item["date"], reverse=True),
                        "items": usage_items, "item_count": len(meals)},
        "unbilled": {"amount": sum(_int(row.get("total_amount")) for row in unbilled),
                     "settlements": [{"period_ym": row.get("period_ym"), "amount": _int(row.get("total_amount")),
                                      "settlement_status": row.get("settlement_status"),
                                      "tax_invoice_status": row.get("tax_invoice_status")} for row in unbilled]},
        "detail_limit": DETAIL_LIMIT,
    }


@router.get("/summary")
def revenue_summary(period_from: date = Query(alias="from"), period_to: date = Query(alias="to"),
                    token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        start_iso, end_iso = _bounds(period_from, period_to)
        data = _summarize(repo, _load(repo, merchant_id, start_iso, end_iso))
        return {"ok": True, "data": {"from": period_from.isoformat(), "to": period_to.isoformat(), **data}, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "매출 현황을 불러오지 못했어요") from exc


@router.get("/detail")
def revenue_detail(period_from: date = Query(alias="from"), period_to: date = Query(alias="to"),
                   party: str = Query(pattern=r"^(personal|[0-9a-fA-F-]{36})$"), token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        start_iso, end_iso = _bounds(period_from, period_to)
        key = PERSONAL if party == PERSONAL else party.lower()
        name = PERSONAL_NAME
        if key != PERSONAL:
            # Only a company this restaurant has dealt with: a contract or any of its rows.
            names = _company_names(repo, {key})
            linked = repo.client.rest_get("merchant_companies", {
                "select": "company_id", "merchant_id": f"eq.{merchant_id}", "company_id": f"eq.{key}", "limit": "1",
            })
            if key not in names or not linked:
                raise _error(404, "COMPANY_NOT_FOUND", "거래처를 찾을 수 없어요")
            name = names[key]
        data = _detail(repo, _load(repo, merchant_id, start_iso, end_iso), key)
        return {"ok": True, "data": {"from": period_from.isoformat(), "to": period_to.isoformat(),
                                     "party": {"key": key, "name": name}, **data}, "error": None}
    except HTTPException:
        raise
    except JoinFlowError as exc:
        raise _error(403, str(exc.code), exc.message) from exc
    except SupabaseHttpError as exc:
        raise _error(502, "SUPABASE_ERROR", "매출 세부 내역을 불러오지 못했어요") from exc
