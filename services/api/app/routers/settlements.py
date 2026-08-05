import logging
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import bearer_token
from app.config import get_settings
from app.repositories.settlements import SettlementRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.settlement_schemas import (
    ConfirmTaxInvoiceRequest, SettlementDisputeRequest, SettlementPaymentRequest,
    SettlementPeriodUpdateRequest,
)
from app.services.join_flow import JoinFlowError
from app.services.popbill_service import PopbillConfig, PopbillError, PopbillService

company_router = APIRouter(prefix="/company/settlements", tags=["company-settlements"])
company_alias_router = APIRouter(prefix="/admin/settlements", tags=["company-settlements"])
merchant_router = APIRouter(prefix="/admin/merchant/settlements", tags=["merchant-settlements"])
demo_router = APIRouter(prefix="/admin/merchant/settlement-demo", tags=["merchant-settlement-demo"])
generation_router = APIRouter(prefix="/admin/merchant/transaction-generation", tags=["merchant-transaction-generation"])
logger = logging.getLogger(__name__)


class SettlementDemoSeedRequest(BaseModel):
    company_id: UUID
    period_ym: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class GeneratedPeriodRequest(BaseModel):
    company_id: UUID
    period_ym: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


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


def _require_test_for_demo(is_demo: bool) -> None:
    if is_demo and PopbillConfig.from_settings(get_settings()).is_test is not True:
        raise _error(409, "SETTLEMENT_DEMO_TEST_MODE_REQUIRED", "데모 문서는 팝빌 테스트 환경에서만 처리할 수 있어요")


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _ordinary_issue_deadline_passed(detail: dict, *, today: date | None = None) -> bool:
    """Conservatively reject only after the entire following month has elapsed.

    The statutory day can move for holidays. Popbill remains authoritative within
    the following month; this guard catches unequivocally stale older periods.
    """
    invoices = detail.get("tax_invoices") if isinstance(detail, dict) else None
    original = next(
        (
            item
            for item in invoices or []
            if isinstance(item, dict) and item.get("document_type") == "original"
        ),
        None,
    )
    raw_write_date = original.get("write_date") if original else None
    if not isinstance(raw_write_date, str):
        return False
    try:
        write_date = date.fromisoformat(raw_write_date)
    except ValueError:
        return False
    second_month_index = write_date.year * 12 + (write_date.month - 1) + 2
    month_after_following = date(
        second_month_index // 12,
        second_month_index % 12 + 1,
        1,
    )
    current = today or datetime.now(ZoneInfo("Asia/Seoul")).date()
    return current >= month_after_following


def _rpc_error(exc: SupabaseHttpError) -> HTTPException:
    body = exc.body
    mapping = (
        ("INVALID_DATE_RANGE", 422, "INVALID_DATE_RANGE", "정산 기간을 확인해 주세요"),
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
        ("SETTLEMENT_DEMO_FORBIDDEN", 403, "FORBIDDEN", "이 데모를 처리할 권한이 없어요"),
        ("SETTLEMENT_DEMO_NOT_SEEDED", 409, "SETTLEMENT_DEMO_NOT_SEEDED", "먼저 데모 데이터를 준비해 주세요"),
        ("SETTLEMENT_DEMO_NOT_CREATED", 409, "SETTLEMENT_DEMO_NOT_CREATED", "먼저 데모 정산을 생성해 주세요"),
        ("SETTLEMENT_DEMO_STATE_CONFLICT", 409, "SETTLEMENT_DEMO_STATE_CONFLICT", "현재 데모 단계에서는 처리할 수 없어요"),
        ("SETTLEMENT_DEMO_MEMBERSHIP_INVALID", 409, "SETTLEMENT_DEMO_MEMBERSHIP_INVALID", "데모 데이터 연결을 확인해 주세요"),
        ("SETTLEMENT_DEMO_NO_UNUSED_PERIOD", 409, "SETTLEMENT_DEMO_NO_UNUSED_PERIOD", "사용 가능한 데모 정산 기간이 없어요"),
        ("SETTLEMENT_DEMO_COMPANY_INELIGIBLE", 422, "SETTLEMENT_DEMO_COMPANY_INELIGIBLE", "선택한 회사는 정산 데모 대상이 아니에요"),
        ("SETTLEMENT_DEMO_COMPANY_ADMIN_REQUIRED", 422, "SETTLEMENT_DEMO_COMPANY_ADMIN_REQUIRED", "활성 회사 관리자가 필요해요"),
        ("SETTLEMENT_DEMO_EMPLOYEE_REQUIRED", 422, "SETTLEMENT_DEMO_EMPLOYEE_REQUIRED", "활성 직원 또는 고객이 필요해요"),
        ("SETTLEMENT_DEMO_CREATE_RESULT_MISMATCH", 409, "SETTLEMENT_DEMO_CREATE_RESULT_MISMATCH", "데모 정산 결과가 예상 거래와 일치하지 않아요"),
        ("DEMO_PERIOD_TRANSACTION_CONFLICT", 409, "DEMO_PERIOD_TRANSACTION_CONFLICT", "데모 기간에 다른 거래가 포함되어 있어요"),
        ("GENERATED_PERIOD_NOT_EMPTY", 409, "GENERATED_PERIOD_NOT_EMPTY", "선택한 회사와 월에 이미 정산이 있어요"),
        ("GENERATED_SETTLEMENT_SET_CONFLICT", 409, "GENERATED_SETTLEMENT_SET_CONFLICT", "정산 구성이 변경되어 처리할 수 없어요"),
        ("GENERATED_STATE_EXTERNAL_REFERENCE", 409, "GENERATED_STATE_EXTERNAL_REFERENCE", "외부 처리 내역이 있어 현재 상태를 초기화할 수 없어요"),
        ("SETTLEMENT_GENERATION_STATE_CONFLICT", 409, "SETTLEMENT_GENERATION_STATE_CONFLICT", "현재 정산 상태에서는 처리할 수 없어요"),
        ("SETTLEMENT_GENERATION_NOT_CREATED", 409, "SETTLEMENT_GENERATION_NOT_CREATED", "먼저 거래를 생성해 주세요"),
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
    if exc.code == "POPBILL_CERTIFICATE_NOT_READY":
        return _error(
            422,
            "POPBILL_CERTIFICATE_NOT_READY",
            "팝빌 전자세금계산서용 인증서를 확인해 주세요",
        )
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


def _company_detail(settlement_id: UUID, token: str, repo: SettlementRepository, include_transactions: bool = False):
    actor = _actor(repo, token, "company_admin")
    assert actor.company_id is not None
    try:
        row = (repo.company_detail(settlement_id, actor.company_id, include_transactions=True)
               if include_transactions else repo.company_detail(settlement_id, actor.company_id))
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
        summary = repo.company_month_summary(actor, resolved_ym)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    # Keep the legacy month summary while exposing the canonical paginated item shape.
    return {"ok": True, "data": {"items": items, "limit": limit, "offset": offset,
            "period_ym": resolved_ym, "single_merchant": True, "summary": summary}, "error": None}


@company_router.get("/{settlement_id}")
@company_alias_router.get("/{settlement_id}")
def company_detail(settlement_id: UUID, include_transactions: bool = False, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return {"ok": True, "data": _company_detail(settlement_id, token, repo, include_transactions), "error": None}


@company_router.post("/{settlement_id}/confirm-and-request-tax-invoice")
@company_alias_router.post("/{settlement_id}/confirm-and-request-tax-invoice")
def confirm_and_request(settlement_id: UUID, _: ConfirmTaxInvoiceRequest, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "company_admin")
    assert actor.company_id is not None
    try:
        if repo.company_detail(settlement_id, actor.company_id) is None:
            raise _error(404, "SETTLEMENT_NOT_FOUND", "정산을 찾을 수 없어요")
        result = repo.confirm(actor, settlement_id)
        return {"ok": True, "data": _public(result), "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


@company_router.post("/{settlement_id}/dispute")
@company_alias_router.post("/{settlement_id}/dispute")
def dispute(settlement_id: UUID, payload: SettlementDisputeRequest, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "company_admin")
    assert actor.company_id is not None
    try:
        if repo.company_detail(settlement_id, actor.company_id) is None:
            raise _error(404, "SETTLEMENT_NOT_FOUND", "정산을 찾을 수 없어요")
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
    assert actor.company_id is not None
    row = _company_detail(settlement_id, token, repo)
    if row["tax_invoice_status"] not in ("issued", "nts_sending", "nts_accepted"):
        raise _error(409, "POPBILL_DOCUMENT_NOT_FOUND", "발행된 세금계산서가 없어요")
    try:
        _require_test_for_demo(getattr(repo, "is_company_demo_settlement", lambda _company_id, _sid: False)(actor.company_id, settlement_id))
        service = _provider(service)
        key = _invoice_key(repo, actor, settlement_id)
        result = service.get_view_url(key) if kind == "view" else service.get_pdf_url(key)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
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
    certificate = {
        "certificate_verified": False,
        "certificate_expires_on": None,
    }
    try:
        current_demo = getattr(repo, "has_current_demo", lambda _merchant_id: False)(actor.merchant_id)
        if current_demo and config.is_test is not True:
            configured = False
        else:
            try:
                service = PopbillService(config)
                configured = True
            except PopbillError:
                configured = False
            else:
                try:
                    provider = service.certificate_readiness()
                    certificate = {
                        "certificate_verified": provider.certificate_verified,
                        "certificate_expires_on": provider.certificate_expires_on,
                    }
                except PopbillError:
                    pass
        supplier = repo.supplier_popbill_readiness(actor.merchant_id, config.corp_num)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    return {"ok": True, "data": {
        "configured": configured,
        "is_test": config.is_test,
        **certificate,
        **supplier,
    }, "error": None}


def _merchant_detail(
    settlement_id: UUID, token: str, repo: SettlementRepository,
    include_transactions: bool = False, allow_demo: bool = False,
):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    try:
        row = (repo.merchant_detail(settlement_id, actor.merchant_id, include_transactions=True)
               if include_transactions else repo.merchant_detail(settlement_id, actor.merchant_id))
        if allow_demo and row is None and repo.is_demo_settlement(actor.merchant_id, settlement_id):
            row = repo.merchant_demo_detail(
                settlement_id, actor.merchant_id, include_transactions=include_transactions,
            )
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    if row is None:
        raise _error(404, "SETTLEMENT_NOT_FOUND", "정산을 찾을 수 없어요")
    return _public(row)


@merchant_router.get("/{settlement_id}")
def merchant_detail(settlement_id: UUID, include_transactions: bool = False, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return {"ok": True, "data": _merchant_detail(
        settlement_id, token, repo, include_transactions, allow_demo=True,
    ), "error": None}


@merchant_router.post("/{settlement_id}/send")
def merchant_send(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    try:
        if repo.merchant_detail(settlement_id, actor.merchant_id) is None:
            raise _error(404, "SETTLEMENT_NOT_FOUND", "정산을 찾을 수 없어요")
        return {"ok": True, "data": _public(repo.send(actor, settlement_id)), "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


@merchant_router.post("/{settlement_id}/begin-revision")
def merchant_begin_revision(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    try:
        if repo.merchant_detail(settlement_id, actor.merchant_id) is None:
            raise _error(404, "SETTLEMENT_NOT_FOUND", "정산을 찾을 수 없어요")
        return {"ok": True, "data": _public(repo.begin_revision(actor, settlement_id)), "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


@merchant_router.patch("/{settlement_id}/period")
def merchant_update_period(settlement_id: UUID, payload: SettlementPeriodUpdateRequest, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    try:
        # This ordinary filtered lookup prevents generic mutation of demo evidence.
        if repo.merchant_detail(settlement_id, actor.merchant_id) is None:
            raise _error(404, "SETTLEMENT_NOT_FOUND", "정산을 찾을 수 없어요")
        return {"ok": True, "data": _public(repo.update_period(actor, settlement_id, payload)), "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


@merchant_router.post("/{settlement_id}/mark-paid")
def merchant_mark_paid(settlement_id: UUID, payload: SettlementPaymentRequest, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    try:
        if repo.merchant_detail(settlement_id, actor.merchant_id) is None:
            raise _error(404, "SETTLEMENT_NOT_FOUND", "정산을 찾을 수 없어요")
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


def _merchant_issue_invoice(
    settlement_id: UUID,
    token: str,
    repo: SettlementRepository,
    service: PopbillService,
    *,
    allow_delayed_issue: bool,
    include_demo: bool = False,
    readiness_verified: bool = False,
):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    # Tenant-scoped existence precedes provider configuration; provider construction
    # still precedes the mutating claim. Detail scope is explicit and independent
    # from Popbill's delayed-issue option.
    if include_demo:
        detail = repo.merchant_demo_detail(settlement_id, actor.merchant_id)
        if detail is None:
            raise _error(404, "SETTLEMENT_NOT_FOUND", "정산을 찾을 수 없어요")
    else:
        detail = _merchant_detail(settlement_id, token, repo)
    if not isinstance(detail, dict):
        raise _error(502, "SETTLEMENT_RESPONSE_INVALID", "정산 정보를 확인할 수 없어요")
    if not allow_delayed_issue and _ordinary_issue_deadline_passed(detail):
        raise _error(
            422,
            "TAX_INVOICE_ISSUE_DEADLINE_PASSED",
            "세금계산서 발행기한이 지났어요. 지연발행 가능 여부를 세무 담당자와 확인해 주세요",
        )
    try:
        is_demo = repo.is_demo_settlement(actor.merchant_id, settlement_id)
        generated = repo.is_generated_settlement(actor.merchant_id, settlement_id)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    # Generated development rows are ordinary business rows, but provider actions
    # remain fail-closed to Popbill's development backend until this feature is removed.
    if (is_demo or generated) and PopbillConfig.from_settings(get_settings()).is_test is not True:
        raise _error(409, "SETTLEMENT_TEST_MODE_REQUIRED", "이 문서는 팝빌 개발 환경에서만 발행할 수 있어요")
    service = _provider(service)
    if not readiness_verified:
        config = PopbillConfig.from_settings(get_settings())
        try:
            supplier = repo.supplier_popbill_readiness(actor.merchant_id, config.corp_num)
        except SupabaseHttpError as exc:
            raise _rpc_error(exc) from exc
        if not supplier["supplier_ready"]:
            raise _error(
                422,
                "SUPPLIER_PROFILE_INCOMPLETE",
                "공급자 필수 사업자 정보를 모두 입력해 주세요",
            )
        if not supplier["corp_matches"]:
            raise _error(
                422,
                "POPBILL_CORP_NUMBER_MISMATCH",
                "식당 사업자번호와 팝빌 연동 사업자번호가 일치하지 않아요",
            )
        try:
            service.certificate_readiness()
        except PopbillError as exc:
            logger.warning(
                "Popbill issue preflight failed code=%s provider_code=%s",
                exc.code,
                exc.provider_code,
            )
            raise _popbill_error(exc) from exc
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
        issued = service.issue(invoice, allow_delayed_issue=allow_delayed_issue)
    except PopbillError as exc:
        logger.warning(
            "Popbill invoice issue failed code=%s provider_code=%s",
            exc.code,
            exc.provider_code,
        )
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


@merchant_router.post("/{settlement_id}/tax-invoice/issue")
def merchant_issue_invoice(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository), service: PopbillService = Depends(get_popbill_service)):
    # Delayed issuance has legal meaning and remains disabled for the ordinary path.
    return _merchant_issue_invoice(
        settlement_id, token, repo, service, allow_delayed_issue=False,
    )


@merchant_router.post("/{settlement_id}/tax-invoice/refresh-status")
def merchant_refresh_invoice_status(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository), service: PopbillService = Depends(get_popbill_service)):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    row = _merchant_detail(settlement_id, token, repo)
    if row["tax_invoice_status"] not in ("issuing", "issued", "nts_sending", "nts_accepted"):
        raise _error(409, "POPBILL_DOCUMENT_NOT_FOUND", "발행된 세금계산서가 없어요")
    try:
        protected = repo.is_demo_settlement(actor.merchant_id, settlement_id) or repo.is_generated_settlement(
            actor.merchant_id, settlement_id,
        )
        _require_test_for_demo(protected)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    service = _provider(service)
    result = _refresh_status(actor, settlement_id, repo, service, _invoice_key(repo, actor, settlement_id))
    return {"ok": True, "data": _public(result), "error": None}


def _merchant_provider_document(settlement_id: UUID, token: str, repo: SettlementRepository, service: PopbillService, kind: str):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    row = _merchant_detail(settlement_id, token, repo)
    if row["tax_invoice_status"] not in ("issued", "nts_sending", "nts_accepted"):
        raise _error(409, "POPBILL_DOCUMENT_NOT_FOUND", "발행된 세금계산서가 없어요")
    try:
        protected = repo.is_demo_settlement(actor.merchant_id, settlement_id) or repo.is_generated_settlement(
            actor.merchant_id, settlement_id,
        )
        _require_test_for_demo(protected)
        service = _provider(service)
        key = _invoice_key(repo, actor, settlement_id)
        result = service.get_view_url(key) if kind == "view" else service.get_pdf_url(key)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
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


def _demo_action(action: str, token: str, repo: SettlementRepository, *args):
    actor = _actor(repo, token, "merchant_admin")
    try:
        method = getattr(repo, f"demo_{action}")
        result = method(actor, *args)
        return {"ok": True, "data": _public(result), "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


def _demo_readiness(actor, repo: SettlementRepository) -> dict:
    config = PopbillConfig.from_settings(get_settings())
    result = {
        "configured": False, "is_test": config.is_test,
        "certificate_verified": False, "certificate_expires_on": None,
    }
    current_demo = getattr(repo, "has_current_demo", lambda _merchant_id: False)(actor.merchant_id)
    if not current_demo or config.is_test is True:
        try:
            service = PopbillService(config)
            result["configured"] = True
            ready = service.certificate_readiness()
            result.update(certificate_verified=ready.certificate_verified,
                          certificate_expires_on=ready.certificate_expires_on)
        except PopbillError:
            pass
    result.update(repo.supplier_popbill_readiness(actor.merchant_id, config.corp_num))
    return result


@demo_router.get("")
def settlement_demo_state(token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    try:
        state = repo.demo_state(actor)
        readiness = _demo_readiness(actor, repo)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    public_state = _public(state)
    assert isinstance(public_state, dict)
    return {"ok": True, "data": {**public_state, "readiness": readiness}, "error": None}


@demo_router.post("/seed")
def settlement_demo_seed(payload: SettlementDemoSeedRequest, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return _demo_action("seed", token, repo, payload.company_id, payload.period_ym)


@demo_router.post("/create")
def settlement_demo_create(token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return _demo_action("create", token, repo)


@demo_router.post("/confirm")
def settlement_demo_confirm(token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return _demo_action("confirm", token, repo)


@demo_router.post("/issue")
def settlement_demo_issue(token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository), service: PopbillService = Depends(get_popbill_service)):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    try:
        member = repo.demo_assert_issue(actor)
        config = PopbillConfig.from_settings(get_settings())
        supplier = repo.supplier_popbill_readiness(actor.merchant_id, config.corp_num)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    if config.is_test is not True:
        raise _error(409, "SETTLEMENT_DEMO_TEST_MODE_REQUIRED", "데모 발행은 팝빌 테스트 환경에서만 가능해요")
    if not supplier["supplier_ready"] or not supplier["corp_matches"]:
        raise _error(422, "SETTLEMENT_DEMO_SUPPLIER_NOT_READY", "공급자 정보와 팝빌 테스트 사업자번호를 확인해 주세요")
    service = _provider(service)
    try:
        certificate = service.certificate_readiness()
    except PopbillError as exc:
        raise _popbill_error(exc) from exc
    if certificate.certificate_verified is not True:
        raise _error(503, "SETTLEMENT_DEMO_CERTIFICATE_NOT_READY", "팝빌 인증서를 확인해 주세요")
    # Membership and every readiness condition precede the existing mutating claim/provider/finalize path.
    # This route is already fail-closed to IsTest=true above. Past-period demo
    # settlements therefore opt in to Popbill's test-only delayed issuance.
    return _merchant_issue_invoice(
        UUID(str(member["settlement_id"])), token, repo, service,
        allow_delayed_issue=True, include_demo=True, readiness_verified=True,
    )


def _demo_provider_document(
    settlement_id: UUID, token: str, repo: SettlementRepository,
    service: PopbillService, kind: str,
):
    actor = _actor(repo, token, "merchant_admin")
    assert actor.merchant_id is not None
    try:
        row = repo.merchant_demo_detail(settlement_id, actor.merchant_id)
        if row is None:
            raise _error(404, "SETTLEMENT_NOT_FOUND", "정산을 찾을 수 없어요")
        if row["tax_invoice_status"] not in ("issued", "nts_sending", "nts_accepted"):
            raise _error(409, "POPBILL_DOCUMENT_NOT_FOUND", "발행된 세금계산서가 없어요")
        _require_test_for_demo(True)
        key = repo.demo_invoice_management_key(actor.merchant_id, settlement_id)
        if not key:
            raise _error(404, "POPBILL_DOCUMENT_NOT_FOUND", "세금계산서를 찾을 수 없어요")
        service = _provider(service)
        result = service.get_view_url(key) if kind == "view" else service.get_pdf_url(key)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    except PopbillError as exc:
        raise _popbill_error(exc) from exc
    return {"ok": True, "data": {"url": result.url, "expires_in": result.expires_in}, "error": None}


@demo_router.get("/{settlement_id}/tax-invoice/view-url")
@demo_router.get("/{settlement_id}/tax-invoice/view")
def settlement_demo_invoice_view(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository), service: PopbillService = Depends(get_popbill_service)):
    return _demo_provider_document(settlement_id, token, repo, service, "view")


@demo_router.get("/{settlement_id}/tax-invoice/pdf-url")
@demo_router.get("/{settlement_id}/tax-invoice/pdf")
def settlement_demo_invoice_pdf(settlement_id: UUID, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository), service: PopbillService = Depends(get_popbill_service)):
    return _demo_provider_document(settlement_id, token, repo, service, "pdf")


@demo_router.post("/mark-paid")
def settlement_demo_mark_paid(token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return _demo_action("mark_paid", token, repo)


@demo_router.post("/reset")
def settlement_demo_reset(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=1, max_length=200),
    token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository),
):
    return _demo_action("reset", token, repo, idempotency_key)


def _generated_action(action: str, payload: GeneratedPeriodRequest, token: str, repo: SettlementRepository):
    actor = _actor(repo, token, "merchant_admin")
    try:
        result = getattr(repo, f"generated_{action}")(actor, payload.company_id, payload.period_ym)
        return {"ok": True, "data": _public(result), "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc


@generation_router.get("")
def generated_state(
    company_id: UUID | None = None,
    period_ym: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository),
):
    actor = _actor(repo, token, "merchant_admin")
    if (company_id is None) != (period_ym is None):
        raise _error(422, "SETTLEMENT_INPUT_INVALID", "회사와 대상 월을 함께 선택해 주세요")
    try:
        state = repo.generated_state(actor, company_id, period_ym)
        readiness = _demo_readiness(actor, repo)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    public_state = _public(state)
    assert isinstance(public_state, dict)
    return {"ok": True, "data": {**public_state, "readiness": readiness}, "error": None}


@generation_router.post("/seed")
def generated_seed(payload: GeneratedPeriodRequest, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return _generated_action("seed", payload, token, repo)


@generation_router.post("/create")
def generated_create(payload: GeneratedPeriodRequest, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return _generated_action("create", payload, token, repo)


@generation_router.post("/confirm")
def generated_confirm(payload: GeneratedPeriodRequest, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return _generated_action("confirm", payload, token, repo)


@generation_router.post("/issue")
def generated_issue(
    payload: GeneratedPeriodRequest, token: str = Depends(bearer_token),
    repo: SettlementRepository = Depends(get_settlement_repository), service: PopbillService = Depends(get_popbill_service),
):
    actor = _actor(repo, token, "merchant_admin")
    try:
        member = repo.generated_assert_issue(actor, payload.company_id, payload.period_ym)
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
    if PopbillConfig.from_settings(get_settings()).is_test is not True:
        raise _error(409, "SETTLEMENT_TEST_MODE_REQUIRED", "이 화면의 발행은 팝빌 개발 환경에서만 가능해요")
    return _merchant_issue_invoice(
        UUID(str(member["settlement_id"])), token, repo, _provider(service),
        allow_delayed_issue=True, include_demo=False,
    )


@generation_router.post("/mark-paid")
def generated_mark_paid(payload: GeneratedPeriodRequest, token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository)):
    return _generated_action("mark_paid", payload, token, repo)


@generation_router.post("/reset")
def generated_reset(
    payload: GeneratedPeriodRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
    token: str = Depends(bearer_token), repo: SettlementRepository = Depends(get_settlement_repository),
):
    actor = _actor(repo, token, "merchant_admin")
    try:
        result = repo.generated_reset(actor, payload.company_id, payload.period_ym, idempotency_key)
        return {"ok": True, "data": _public(result), "error": None}
    except SupabaseHttpError as exc:
        raise _rpc_error(exc) from exc
