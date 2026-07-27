from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import bearer_token
from app.repositories.settlements import SettlementRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.settlement_schemas import ConfirmTaxInvoiceRequest, SettlementDisputeRequest, SettlementPaymentRequest
from app.services.join_flow import JoinFlowError

company_router = APIRouter(prefix="/company/settlements", tags=["company-settlements"])
company_alias_router = APIRouter(prefix="/admin/settlements", tags=["company-settlements"])
merchant_router = APIRouter(prefix="/admin/merchant/settlements", tags=["merchant-settlements"])


def get_settlement_repository() -> SettlementRepository:
    return SettlementRepository()


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _rpc_error(exc: SupabaseHttpError) -> HTTPException:
    body = exc.body
    mapping = (
        ("SETTLEMENT_NOT_FOUND", 404, "SETTLEMENT_NOT_FOUND", "정산을 찾을 수 없어요"),
        ("SETTLEMENT_FORBIDDEN", 403, "FORBIDDEN", "이 정산을 처리할 권한이 없어요"),
        ("IDEMPOTENCY_CONFLICT", 409, "IDEMPOTENCY_CONFLICT", "같은 멱등 키가 다른 요청에 사용됐어요"),
        ("SETTLEMENT_STATE_CONFLICT", 409, "SETTLEMENT_STATE_CONFLICT", "현재 정산 상태에서는 처리할 수 없어요"),
        ("SUPPLIER_PROFILE_INCOMPLETE", 422, "SUPPLIER_PROFILE_INCOMPLETE", "공급자 필수 사업자 정보를 모두 입력해 주세요"),
        ("BUSINESS_PROFILE_INCOMPLETE", 422, "BUSINESS_PROFILE_INCOMPLETE", "필수 사업자 정보를 모두 입력해 주세요"),
        ("SETTLEMENT_AMOUNTS_INVALID", 422, "SETTLEMENT_AMOUNTS_INVALID", "정산 공급가액, 부가세, 합계가 완전하지 않아요"),
        ("SETTLEMENT_INPUT_INVALID", 422, "SETTLEMENT_INPUT_INVALID", "요청 값을 확인해 주세요"),
    )
    for marker, status, code, message in mapping:
        if marker in body:
            return _error(status, code, message)
    if exc.status in (401, 403):
        return _error(401, "UNAUTHENTICATED", "로그인이 필요해요")
    return _error(502, "SUPABASE_ERROR", "정산 처리 중 데이터베이스 오류가 발생했어요")


def _actor(repo: SettlementRepository, token: str, role: str):
    try:
        return repo.actor(token, role)
    except JoinFlowError as exc:
        raise _error(403, "FORBIDDEN", exc.message) from exc
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


def _company_list(limit: int, offset: int, token: str, repo: SettlementRepository):
    actor = _actor(repo, token, "company_admin")
    assert actor.company_id is not None
    try:
        items = repo.list_company(actor.company_id, limit, offset)
        return {"ok": True, "data": {"items": items, "limit": limit, "offset": offset}, "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


def _company_detail(settlement_id: UUID, token: str, repo: SettlementRepository):
    actor = _actor(repo, token, "company_admin")
    assert actor.company_id is not None
    try:
        row = repo.company_detail(settlement_id, actor.company_id)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    if row is None:
        raise _error(404, "SETTLEMENT_NOT_FOUND", "정산을 찾을 수 없어요")
    return row


@company_router.get("")
def company_list(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return _company_list(limit, offset, token, repo)


@company_alias_router.get("")
def company_list_alias(ym: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "company_admin")
    assert actor.company_id is not None
    try:
        resolved_ym = ym or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m")
        items = repo.list_company(actor.company_id, limit, offset, resolved_ym)
        summary = repo.company_month_summary(actor.company_id, resolved_ym)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    # Keep the legacy month summary while exposing the canonical paginated item shape.
    return {"ok": True, "data": {"items": items, "limit": limit, "offset": offset,
            "period_ym": resolved_ym, "single_merchant": True, "summary": summary}, "error": None}


@company_router.get("/{settlement_id}")
@company_alias_router.get("/{settlement_id}")
def company_detail(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return {"ok": True, "data": _company_detail(settlement_id, token, repo), "error": None}


@company_router.post("/{settlement_id}/confirm-and-request-tax-invoice")
@company_alias_router.post("/{settlement_id}/confirm-and-request-tax-invoice")
def confirm_and_request(settlement_id: UUID, _: ConfirmTaxInvoiceRequest, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "company_admin")
    try:
        result = repo.confirm(actor, settlement_id)
        return {"ok": True, "data": result, "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


@company_router.post("/{settlement_id}/dispute")
@company_alias_router.post("/{settlement_id}/dispute")
def dispute(settlement_id: UUID, payload: SettlementDisputeRequest, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "company_admin")
    try:
        result = repo.dispute(actor, settlement_id, payload.reason, payload.idempotency_key)
        return {"ok": True, "data": result, "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


def _company_provider_document(settlement_id: UUID, token: str, repo: SettlementRepository):
    row = _company_detail(settlement_id, token, repo)
    if row["tax_invoice_status"] not in ("issued", "nts_sending", "nts_accepted"):
        raise _error(409, "TAX_INVOICE_NOT_ISSUED", "발행된 세금계산서가 없어요")
    raise _error(503, "POPBILL_NOT_CONFIGURED", "세금계산서 제공자가 아직 설정되지 않았어요")


@company_router.get("/{settlement_id}/tax-invoice/view")
@company_alias_router.get("/{settlement_id}/tax-invoice/view")
def company_invoice_view(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return _company_provider_document(settlement_id, token, repo)


@company_router.get("/{settlement_id}/tax-invoice/pdf")
@company_alias_router.get("/{settlement_id}/tax-invoice/pdf")
def company_invoice_pdf(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return _company_provider_document(settlement_id, token, repo)


@merchant_router.get("")
def merchant_list(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    try:
        items = repo.list_merchant(actor.merchant_id, limit, offset)
        return {"ok": True, "data": {"items": items, "limit": limit, "offset": offset}, "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


def _merchant_detail(settlement_id: UUID, token: str, repo: SettlementRepository):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    try:
        row = repo.merchant_detail(settlement_id, actor.merchant_id)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    if row is None:
        raise _error(404, "SETTLEMENT_NOT_FOUND", "정산을 찾을 수 없어요")
    return row


@merchant_router.get("/{settlement_id}")
def merchant_detail(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return {"ok": True, "data": _merchant_detail(settlement_id, token, repo), "error": None}


@merchant_router.post("/{settlement_id}/send")
def merchant_send(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "merchant_admin")
    try:
        return {"ok": True, "data": repo.send(actor, settlement_id), "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


@merchant_router.post("/{settlement_id}/mark-paid")
def merchant_mark_paid(settlement_id: UUID, payload: SettlementPaymentRequest, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "merchant_admin")
    try:
        return {"ok": True, "data": repo.mark_paid(actor, settlement_id, payload), "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


@merchant_router.post("/{settlement_id}/tax-invoice/issue")
def merchant_issue_invoice(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    _merchant_detail(settlement_id, token, repo)
    raise _error(503, "POPBILL_NOT_CONFIGURED", "세금계산서 제공자가 아직 설정되지 않았어요")


@merchant_router.get("/{settlement_id}/tax-invoice/view")
def merchant_invoice_view(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    row = _merchant_detail(settlement_id, token, repo)
    if row["tax_invoice_status"] not in ("issued", "nts_sending", "nts_accepted"):
        raise _error(409, "TAX_INVOICE_NOT_ISSUED", "발행된 세금계산서가 없어요")
    raise _error(503, "POPBILL_NOT_CONFIGURED", "세금계산서 제공자가 아직 설정되지 않았어요")


@merchant_router.get("/{settlement_id}/tax-invoice/pdf")
def merchant_invoice_pdf(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return merchant_invoice_view(settlement_id, token, repo)
