from __future__ import annotations

from typing import Any
from uuid import UUID

from app.repositories.join_repository import JoinRepository
from app.services.join_flow import JoinErrorCode, JoinFlowError, UserProfile


LIST_FIELDS = (
    "id,company_id,merchant_id,period_ym,period_from,period_to,tx_count,total_amount,"
    "supply_amount,vat_amount,status,settlement_status,tax_invoice_status,payment_status,"
    "sent_at,confirmed_at,finalized_at,due_date,paid_at,created_at,updated_at"
)


class SettlementRepository:
    """Service-role data access with explicit actor and tenant scoping."""

    def __init__(self, join_repo: JoinRepository | None = None):
        self.join_repo = join_repo or JoinRepository()
        self.client = self.join_repo.client

    def actor(self, token: str, role: str) -> UserProfile:
        auth = self.join_repo.auth_user_from_token(token)
        actor = self.join_repo.get_profile(auth.id, email=auth.email)
        tenant = actor.company_id if role == "company_admin" and actor else actor.merchant_id if actor else None
        if actor is None or actor.status != "active" or actor.role != role or not tenant:
            raise JoinFlowError(JoinErrorCode.FORBIDDEN, "이 정산을 처리할 권한이 없어요")
        return actor

    def list_company(self, company_id: str, limit: int, offset: int, period_ym: str | None = None) -> list[dict[str, Any]]:
        params = {
            "select": LIST_FIELDS, "company_id": f"eq.{company_id}",
            "order": "created_at.desc,id.desc", "limit": str(limit), "offset": str(offset),
        }
        if period_ym is not None:
            params["period_ym"] = f"eq.{period_ym}"
        return self.client.rest_get("settlements", params)

    def company_month_summary(self, company_id: str, period_ym: str) -> dict[str, Any]:
        return self.client.rpc("company_settlement_month_summary", {
            "p_company_id": company_id, "p_period_ym": period_ym,
        })

    def list_merchant(self, merchant_id: str, limit: int, offset: int) -> list[dict[str, Any]]:
        return self.client.rest_get("settlements", {
            "select": LIST_FIELDS, "merchant_id": f"eq.{merchant_id}",
            "order": "created_at.desc,id.desc", "limit": str(limit), "offset": str(offset),
        })

    def _detail(self, settlement_id: str | UUID, tenant_column: str, tenant_id: str) -> dict[str, Any] | None:
        rows = self.client.rest_get("settlements", {
            "select": LIST_FIELDS, "id": f"eq.{settlement_id}", tenant_column: f"eq.{tenant_id}", "limit": "1",
        })
        if not rows:
            return None
        row = rows[0]
        invoices = self.client.rest_get("tax_invoices", {
            "select": "id,settlement_id,document_type,invoicer_mgt_key,tax_type,write_date,supply_amount,vat_amount,total_amount,supplier_snapshot,recipient_snapshot,popbill_status,nts_status,requested_at,issued_at,nts_sent_at,nts_accepted_at,failure_code,failure_message,created_at",
            "settlement_id": f"eq.{settlement_id}", "order": "created_at.asc,id.asc",
        })
        events = self.client.rest_get("settlement_events", {
            "select": "id,event_type,payload,created_at", "settlement_id": f"eq.{settlement_id}",
            "order": "created_at.asc,id.asc",
        })
        company = self.client.rest_get("companies", {
            "select": "id,name,biz_reg_no,representative_name,address,business_type,business_item,tax_invoice_email,contact_name,contact_phone,status,contact_email,created_at",
            "id": f"eq.{row['company_id']}", "limit": "1",
        })
        return {**row, "business_information": company[0] if company else None,
                "tax_invoices": invoices, "events": events}

    def company_detail(self, settlement_id: str | UUID, company_id: str) -> dict[str, Any] | None:
        return self._detail(settlement_id, "company_id", company_id)

    def merchant_detail(self, settlement_id: str | UUID, merchant_id: str) -> dict[str, Any] | None:
        row = self._detail(settlement_id, "merchant_id", merchant_id)
        if row is not None:
            row["payments"] = self.client.rest_get("settlement_payments", {
                "select": "id,amount,depositor_name,deposited_at,memo,confirmed_at,created_at",
                "settlement_id": f"eq.{settlement_id}", "order": "created_at.asc,id.asc",
            })
        return row

    def confirm(self, actor: UserProfile, settlement_id: str | UUID) -> dict[str, Any]:
        return self.client.rpc("company_confirm_and_request_tax_invoice", {
            "p_actor_id": actor.id, "p_company_id": actor.company_id, "p_settlement_id": settlement_id,
        })

    def dispute(self, actor: UserProfile, settlement_id: str | UUID, reason: str, key: str) -> dict[str, Any]:
        return self.client.rpc("company_dispute_settlement", {
            "p_actor_id": actor.id, "p_company_id": actor.company_id, "p_settlement_id": settlement_id,
            "p_reason": reason, "p_idempotency_key": key,
        })

    def send(self, actor: UserProfile, settlement_id: str | UUID) -> dict[str, Any]:
        return self.client.rpc("merchant_send_settlement", {
            "p_actor_id": actor.id, "p_merchant_id": actor.merchant_id, "p_settlement_id": settlement_id,
        })

    def mark_paid(self, actor: UserProfile, settlement_id: str | UUID, payload: Any) -> dict[str, Any]:
        return self.client.rpc("merchant_mark_settlement_paid", {
            "p_actor_id": actor.id, "p_merchant_id": actor.merchant_id, "p_settlement_id": settlement_id,
            "p_amount": payload.amount, "p_depositor_name": payload.depositor_name,
            "p_deposited_at": payload.deposited_at.isoformat(), "p_memo": payload.memo,
            "p_idempotency_key": payload.idempotency_key,
        })
