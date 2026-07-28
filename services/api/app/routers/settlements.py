from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import bearer_token
from app.config import get_settings
from app.repositories.settlements import SettlementRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.settlement_schemas import ConfirmTaxInvoiceRequest, SettlementDisputeRequest, SettlementPaymentRequest
from app.services.join_flow import JoinFlowError
from app.services.popbill_service import PopbillConfig, PopbillError, PopbillService

company_router = APIRouter(prefix="/company/settlements", tags=["company-settlements"])
company_alias_router = APIRouter(prefix="/admin/settlements", tags=["company-settlements"])
merchant_router = APIRouter(prefix="/admin/merchant/settlements", tags=["merchant-settlements"])


def get_settlement_repository() -> SettlementRepository:
    return SettlementRepository()


def _build_popbill_service() -> PopbillService:
    try:
        return PopbillService(PopbillConfig.from_settings(get_settings()))
    except PopbillError as exc:
        code = "POPBILL_NOT_CONFIGURED" if exc.code == "POPBILL_NOT_CONFIGURED" else "POPBILL_TEMPORARILY_UNAVAILABLE"
        raise HTTPException(
            status_code=503,
            detail={"code": code, "message": "팝빌 설정을 확인해 주세요"},
        ) from exc


def get_popbill_service():
    """Inject a lazy factory so tenant/document checks precede URL provider calls."""
    return _build_popbill_service


def _provider(value):
    return value() if callable(value) else value


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
        ("MIXED_TAX_TYPES_NOT_SUPPORTED", 422, "MIXED_TAX_TYPES_NOT_SUPPORTED", "과세와 면세 거래를 한 정산에 함께 발행할 수 없어요"),
        ("TAX_TYPE_UNCLASSIFIED", 422, "TAX_TYPE_UNCLASSIFIED", "정산 과세 유형을 확인해 주세요"),
        ("POPBILL_DOCUMENT_NOT_FOUND", 404, "POPBILL_DOCUMENT_NOT_FOUND", "세금계산서를 찾을 수 없어요"),
        ("ISSUE_ATTEMPT_TOKEN_MISMATCH", 409, "POPBILL_RECONCILIATION_REQUIRED", "발행 결과를 먼저 확인해 주세요"),
        ("POPBILL_ISSUE_LEASE_ACTIVE", 409, "POPBILL_RECONCILIATION_REQUIRED", "발행 결과를 먼저 확인해 주세요"),
        ("POPBILL_RECONCILIATION_REQUIRED", 409, "POPBILL_RECONCILIATION_REQUIRED", "발행 결과를 먼저 확인해 주세요"),
    )
    for marker, status, code, message in mapping:
        if marker in body:
            return _error(status, code, message)
    if exc.status in (401, 403):
        return _error(401, "UNAUTHENTICATED", "로그인이 필요해요")
    return _error(502, "SUPABASE_ERROR", "정산 처리 중 데이터베이스 오류가 발생했어요")


def _popbill_error(exc: PopbillError) -> HTTPException:
    if exc.code == "POPBILL_NOT_CONFIGURED":
        return _error(503, "POPBILL_NOT_CONFIGURED", "팝빌 설정이 완료되지 않았어요")
    if exc.code == "POPBILL_DOCUMENT_NOT_FOUND":
        return _error(404, "POPBILL_DOCUMENT_NOT_FOUND", "세금계산서를 찾을 수 없어요")
    if exc.code == "POPBILL_RECONCILIATION_REQUIRED":
        return _error(503, "POPBILL_RECONCILIATION_REQUIRED", "발행 결과 확인이 필요해요")
    if exc.code in ("POPBILL_INVALID_INPUT", "POPBILL_ISSUE_REJECTED"):
        return _error(422, "POPBILL_ISSUE_REJECTED", "세금계산서 발행이 거절됐어요")
    return _error(503, "POPBILL_TEMPORARILY_UNAVAILABLE", "팝빌에 잠시 연결할 수 없어요")


def _actor(repo: SettlementRepository, token: str, role: str):
    try:
        return repo.actor(token, role)
    except JoinFlowError as exc:
        raise _error(403, "FORBIDDEN", exc.message) from exc
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


_PRIVATE_RESPONSE_KEYS = {
    "invoicer_mgt_key", "popbill_status_code", "nts_status_code", "issue_attempt_token",
    "issue_attempt_started_at", "issue_lease_expires_at", "reconciliation_required_at",
    "status_refreshed_at", "provider_response", "popbill_status_message", "attempt_token",
    "lease_expires_at", "provider_state_code", "provider_state_memo", "item_key",
}


def _public(value):
    """Fail-closed recursive projection for browser-facing settlement payloads."""
    if isinstance(value, list):
        return [_public(item) for item in value]
    if not isinstance(value, dict):
        return value
    projected = {key: _public(item) for key, item in value.items() if key not in _PRIVATE_RESPONSE_KEYS}
    if "failure_message" in projected:
        projected["failure_message"] = "세금계산서 처리에 실패했어요" if projected["failure_message"] else None
    return projected


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
    return _public(row)


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
        return {"ok": True, "data": _public(result), "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


@company_router.post("/{settlement_id}/dispute")
@company_alias_router.post("/{settlement_id}/dispute")
def dispute(settlement_id: UUID, payload: SettlementDisputeRequest, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "company_admin")
    try:
        result = repo.dispute(actor, settlement_id, payload.reason, payload.idempotency_key)
        return {"ok": True, "data": _public(result), "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


def _invoice_key(repo: SettlementRepository, actor, settlement_id: UUID) -> str:
    key = repo.original_invoice_management_key(actor, settlement_id)
    if not key:
        raise _error(404, "POPBILL_DOCUMENT_NOT_FOUND", "세금계산서를 찾을 수 없어요")
    return key


def _company_provider_document(
    settlement_id: UUID, token: str, repo: SettlementRepository,
    service: PopbillService, kind: str,
):
    actor = _actor(repo, token, "company_admin")
    row = _company_detail(settlement_id, token, repo)
    if row["tax_invoice_status"] not in ("issued", "nts_sending", "nts_accepted"):
        raise _error(409, "POPBILL_DOCUMENT_NOT_FOUND", "발행된 세금계산서가 없어요")
    service = _provider(service)
    try:
        key = _invoice_key(repo, actor, settlement_id)
        result = service.get_view_url(key) if kind == "view" else service.get_pdf_url(key)
    except PopbillError as exc:
        raise _popbill_error(exc) from exc
    return {"ok": True, "data": {"url": result.url, "expires_in": result.expires_in}, "error": None}


@company_router.get("/{settlement_id}/tax-invoice/view-url")
@company_router.get("/{settlement_id}/tax-invoice/view")
@company_alias_router.get("/{settlement_id}/tax-invoice/view-url")
@company_alias_router.get("/{settlement_id}/tax-invoice/view")
def company_invoice_view(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository), service: PopbillService = Depends(get_popbill_service)):
    return _company_provider_document(settlement_id, token, repo, service, "view")


@company_router.get("/{settlement_id}/tax-invoice/pdf-url")
@company_router.get("/{settlement_id}/tax-invoice/pdf")
@company_alias_router.get("/{settlement_id}/tax-invoice/pdf-url")
@company_alias_router.get("/{settlement_id}/tax-invoice/pdf")
def company_invoice_pdf(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository), service: PopbillService = Depends(get_popbill_service)):
    return _company_provider_document(settlement_id, token, repo, service, "pdf")


@merchant_router.get("")
def merchant_list(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    try:
        items = repo.list_merchant(actor.merchant_id, limit, offset)
        return {"ok": True, "data": {"items": items, "limit": limit, "offset": offset}, "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


@merchant_router.get("/popbill-readiness")
def merchant_popbill_readiness(token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    config = PopbillConfig.from_settings(get_settings())
    try:
        PopbillService(config)
        configured = True
    except PopbillError:
        configured = False
    try:
        supplier = repo.supplier_popbill_readiness(actor.merchant_id, config.corp_num)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    return {"ok": True, "data": {
        "configured": configured,
        "is_test": config.is_test,
        **supplier,
    }, "error": None}


@merchant_router.post("/popbill-test-e2e")
def merchant_popbill_test_e2e(token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    config = PopbillConfig.from_settings(get_settings())
    if config.is_test is not True:
        raise _error(409, "POPBILL_TEST_MODE_REQUIRED", "팝빌 테스트 모드에서만 실행할 수 있어요")
    try:
        service = PopbillService(config)
        readiness = repo.supplier_popbill_readiness(actor.merchant_id, config.corp_num)
        if not readiness["supplier_ready"] or not readiness["corp_matches"]:
            raise _error(422, "POPBILL_TEST_PARTY_NOT_READY", "팝빌 테스트 사업자 정보를 확인해 주세요")
        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        merchant_key = "".join(char for char in str(actor.merchant_id) if char.isalnum())
        management_key = f"GE2E{today:%Y%m%d}{merchant_key}"[:24]
        invoice = repo.popbill_test_invoice_input(actor.merchant_id, management_key, today.isoformat())
        already_in_use = service.management_key_in_use(management_key)
        if not already_in_use:
            service.issue(invoice)
        status = service.get_status(management_key)
        view = service.get_view_url(management_key)
        pdf = service.get_pdf_url(management_key)
    except HTTPException:
        raise
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    except ValueError as exc:
        raise _error(422, "POPBILL_TEST_PARTY_NOT_READY", "팝빌 테스트 사업자 정보를 확인해 주세요") from exc
    except PopbillError as exc:
        raise HTTPException(status_code=422 if exc.code == "POPBILL_ISSUE_REJECTED" else 503, detail={
            "code": exc.code,
            "provider_code": exc.provider_code,
            "message": "팝빌 테스트 호출을 확인해 주세요",
        }) from exc
    return {"ok": True, "data": {
        "management_key": management_key,
        "issued_now": not already_in_use,
        "duplicate_guarded": already_in_use,
        "provider_state_code": status.provider_state_code,
        "nts_accepted": status.nts_accepted,
        "view_url_ready": view.url.startswith("https://") and view.expires_in == 30,
        "pdf_url_ready": pdf.url.startswith("https://") and pdf.expires_in == 30,
    }, "error": None}


def _merchant_detail(settlement_id: UUID, token: str, repo: SettlementRepository):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    try:
        row = repo.merchant_detail(settlement_id, actor.merchant_id)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    if row is None:
        raise _error(404, "SETTLEMENT_NOT_FOUND", "정산을 찾을 수 없어요")
    return _public(row)


@merchant_router.get("/{settlement_id}")
def merchant_detail(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return {"ok": True, "data": _merchant_detail(settlement_id, token, repo), "error": None}


@merchant_router.post("/{settlement_id}/send")
def merchant_send(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "merchant_admin")
    try:
        return {"ok": True, "data": _public(repo.send(actor, settlement_id)), "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


@merchant_router.post("/{settlement_id}/mark-paid")
def merchant_mark_paid(settlement_id: UUID, payload: SettlementPaymentRequest, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "merchant_admin")
    try:
        return {"ok": True, "data": _public(repo.mark_paid(actor, settlement_id, payload)), "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


def _refresh_status(actor, settlement_id: UUID, repo: SettlementRepository, service: PopbillService, key: str):
    try:
        status = service.get_status(key)
        return repo.apply_invoice_status(actor, settlement_id, status)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    except PopbillError as exc:
        raise _popbill_error(exc) from exc


@merchant_router.post("/{settlement_id}/tax-invoice/issue")
def merchant_issue_invoice(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository), service: PopbillService = Depends(get_popbill_service)):
    actor = _actor(repo, token, "merchant_admin")
    # Tenant-scoped existence precedes provider configuration; provider construction
    # still precedes the mutating claim.
    _merchant_detail(settlement_id, token, repo)
    service = _provider(service)
    try:
        claim = repo.claim_invoice_issue(actor, settlement_id)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    action = claim["action"]
    invoice = claim.get("tax_invoice") or {}
    if action == "already_issued":
        return {"ok": True, "data": _public(claim), "error": None}
    if action == "reconcile":
        key = invoice.get("invoicer_mgt_key", "")
        try:
            in_use = service.management_key_in_use(key)
            if not in_use:
                result = repo.reset_stale_invoice_issue(
                    actor, settlement_id, claim["attempt_token"], False
                )
                return {"ok": True, "data": _public({**result, "reconciled": True}), "error": None}
        except SupabaseHttpError as exc:
            raise _rpc_error(exc) from exc
        except PopbillError as exc:
            raise _popbill_error(exc) from exc
        result = _refresh_status(actor, settlement_id, repo, service, key)
        return {"ok": True, "data": _public({**result, "reconciled": True}), "error": None}
    attempt_token = claim["attempt_token"]
    try:
        issued = service.issue(invoice)
    except PopbillError as exc:
        outcome = "rejected" if exc.code in ("POPBILL_INVALID_INPUT", "POPBILL_ISSUE_REJECTED") else "reconciliation_required"
        try:
            repo.finalize_invoice_issue(
                actor, settlement_id, attempt_token, outcome,
                "POPBILL_ISSUE_REJECTED" if outcome == "rejected" else None,
                "Popbill rejected the request" if outcome == "rejected" else None,
            )
        except SupabaseHttpError as db_exc:
            raise _rpc_error(db_exc) from db_exc
        raise _popbill_error(exc) from exc
    try:
        result = repo.finalize_invoice_issue(actor, settlement_id, attempt_token, "success")
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    return {"ok": True, "data": _public({**result, "reconciled": issued.reconciled}), "error": None}


@merchant_router.post("/{settlement_id}/tax-invoice/refresh-status")
def merchant_refresh_invoice_status(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository), service: PopbillService = Depends(get_popbill_service)):
    actor = _actor(repo, token, "merchant_admin")
    row = _merchant_detail(settlement_id, token, repo)
    if row["tax_invoice_status"] not in ("issuing", "issued", "nts_sending", "nts_accepted"):
        raise _error(409, "POPBILL_DOCUMENT_NOT_FOUND", "발행된 세금계산서가 없어요")
    service = _provider(service)
    result = _refresh_status(actor, settlement_id, repo, service, _invoice_key(repo, actor, settlement_id))
    return {"ok": True, "data": _public(result), "error": None}


def _merchant_provider_document(settlement_id: UUID, token: str, repo: SettlementRepository, service: PopbillService, kind: str):
    actor = _actor(repo, token, "merchant_admin")
    row = _merchant_detail(settlement_id, token, repo)
    if row["tax_invoice_status"] not in ("issued", "nts_sending", "nts_accepted"):
        raise _error(409, "POPBILL_DOCUMENT_NOT_FOUND", "발행된 세금계산서가 없어요")
    service = _provider(service)
    try:
        key = _invoice_key(repo, actor, settlement_id)
        result = service.get_view_url(key) if kind == "view" else service.get_pdf_url(key)
    except PopbillError as exc:
        raise _popbill_error(exc) from exc
    return {"ok": True, "data": {"url": result.url, "expires_in": result.expires_in}, "error": None}


@merchant_router.get("/{settlement_id}/tax-invoice/view-url")
@merchant_router.get("/{settlement_id}/tax-invoice/view")
def merchant_invoice_view(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository), service: PopbillService = Depends(get_popbill_service)):
    return _merchant_provider_document(settlement_id, token, repo, service, "view")


@merchant_router.get("/{settlement_id}/tax-invoice/pdf-url")
@merchant_router.get("/{settlement_id}/tax-invoice/pdf")
def merchant_invoice_pdf(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository), service: PopbillService = Depends(get_popbill_service)):
    return _merchant_provider_document(settlement_id, token, repo, service, "pdf")
