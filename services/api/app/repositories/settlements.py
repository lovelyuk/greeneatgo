from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from app.repositories.join_repository import JoinRepository
from app.services.join_flow import JoinErrorCode, JoinFlowError, UserProfile


LIST_FIELDS = (
    "id,company_id,merchant_id,period_ym,period_from,period_to,tx_count,total_amount,"
    "supply_amount,vat_amount,settlement_tax_type,status,settlement_status,tax_invoice_status,payment_status,"
    "sent_at,confirmed_at,finalized_at,due_date,paid_at,is_demo,created_at,updated_at"
)

INVOICE_FIELDS = (
    "id,settlement_id,company_id,merchant_id,document_type,tax_type,"
    "write_date,supply_amount,vat_amount,total_amount,supplier_snapshot,recipient_snapshot,"
    "popbill_status,nts_status,nts_confirm_num,requested_at,issue_requested_at,issued_at,nts_sent_at,"
    "nts_accepted_at,failure_code,failed_at,created_at,updated_at"
)

PAYMENT_FIELDS = "id,amount,depositor_name,deposited_at,memo,confirmed_at,created_at"
COMPANY_VISIBLE_SETTLEMENT_STATUSES = (
    "sent", "confirmed", "disputed", "finalized", "completed", "cancelled",
)
TRANSACTION_FIELDS = (
    "id,user_id,amount,kind,tx_code,meal_window,product_name,pay_type,is_demo,"
    "settlement_tax_type,settlement_supply_amount,settlement_vat_amount,"
    "settlement_total_amount,created_at"
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

    @staticmethod
    def _party_ids(rows: list[dict[str, Any]], key: str) -> list[str]:
        return sorted({str(row[key]) for row in rows if row.get(key)})

    def _attach_party_names(
        self, rows: list[dict[str, Any]], *, id_key: str, table: str, output_key: str,
    ) -> list[dict[str, Any]]:
        ids = self._party_ids(rows, id_key)
        if not ids:
            return rows
        parties = self.client.rest_get(table, {
            "select": "id,name", "id": f"in.({','.join(ids)})",
        })
        names = {str(party["id"]): party.get("name") for party in parties if party.get("id")}
        return [
            {**row, output_key: {"name": names.get(str(row.get(id_key))) or ""}}
            for row in rows
        ]

    def list_company(self, company_id: str, limit: int, offset: int, period_ym: str | None = None) -> list[dict[str, Any]]:
        params = {
            "select": LIST_FIELDS, "company_id": f"eq.{company_id}",
            "settlement_status": f"in.({','.join(COMPANY_VISIBLE_SETTLEMENT_STATUSES)})",
            "order": "created_at.desc,id.desc", "limit": str(limit), "offset": str(offset),
        }
        if period_ym is not None:
            params["period_ym"] = f"eq.{period_ym}"
        rows = self.client.rest_get("normal_settlements", params)
        return self._attach_party_names(
            rows, id_key="merchant_id", table="merchants", output_key="supplier_information",
        )

    def company_month_summary(self, actor: UserProfile, period_ym: str) -> dict[str, Any]:
        return self.client.rpc("company_settlement_month_summary", {
            "p_actor_id": actor.id, "p_company_id": actor.company_id, "p_period_ym": period_ym,
        })

    def list_merchant(self, merchant_id: str, limit: int, offset: int) -> list[dict[str, Any]]:
        # Merchant history intentionally includes its own demo settlements so a
        # guided run can be reconciled against the normal monthly screens. Demo
        # mutations remain isolated behind the dedicated demo endpoints.
        rows = self.client.rest_get("settlements", {
            "select": LIST_FIELDS, "merchant_id": f"eq.{merchant_id}",
            "order": "created_at.desc,id.desc", "limit": str(limit), "offset": str(offset),
        })
        return self._attach_party_names(
            rows, id_key="company_id", table="companies", output_key="business_information",
        )

    def supplier_popbill_readiness(self, merchant_id: str, configured_corp_num: str) -> dict[str, bool]:
        rows = self.client.rest_get("merchants", {
            "select": "name,biz_reg_no,representative_name,address,business_type,business_item,tax_invoice_email,owner_phone",
            "id": f"eq.{merchant_id}", "limit": "1",
        })
        row = rows[0] if rows else {}
        required = (
            "name", "biz_reg_no", "representative_name", "address", "business_type",
            "business_item", "tax_invoice_email", "owner_phone",
        )
        supplier_ready = all(isinstance(row.get(key), str) and row[key].strip() for key in required)
        supplier_corp = "".join(char for char in str(row.get("biz_reg_no") or "") if char.isdigit())
        configured_corp = "".join(char for char in configured_corp_num if char.isdigit())
        return {
            "supplier_ready": supplier_ready,
            "corp_matches": bool(supplier_corp and configured_corp and supplier_corp == configured_corp),
        }

    def _demo_rpc(self, name: str, actor: UserProfile) -> dict[str, Any]:
        return self.client.rpc(name, {
            "p_actor_id": actor.id,
            "p_merchant_id": actor.merchant_id,
        })

    def demo_state(self, actor: UserProfile) -> dict[str, Any]:
        return self._demo_rpc("settlement_demo_state", actor)

    def demo_seed(self, actor: UserProfile, company_id: str | UUID, period_ym: str) -> dict[str, Any]:
        return self.client.rpc("settlement_demo_seed", {
            "p_actor_id": actor.id, "p_merchant_id": actor.merchant_id,
            "p_company_id": str(company_id), "p_period_ym": period_ym,
        })

    def demo_create(self, actor: UserProfile) -> dict[str, Any]:
        return self._demo_rpc("settlement_demo_create", actor)

    def demo_confirm(self, actor: UserProfile) -> dict[str, Any]:
        return self._demo_rpc("settlement_demo_confirm", actor)

    def demo_assert_issue(self, actor: UserProfile) -> dict[str, Any]:
        return self._demo_rpc("settlement_demo_assert_issue", actor)

    def demo_mark_paid(self, actor: UserProfile) -> dict[str, Any]:
        return self._demo_rpc("settlement_demo_mark_paid", actor)

    def demo_reset(self, actor: UserProfile, idempotency_key: str | None = None) -> dict[str, Any]:
        return self.client.rpc("settlement_demo_reset", {
            "p_actor_id": actor.id, "p_merchant_id": actor.merchant_id,
            "p_idempotency_key": idempotency_key,
        })

    def generated_state(
        self, actor: UserProfile, company_id: str | UUID | None = None, period_ym: str | None = None,
    ) -> dict[str, Any]:
        return self.client.rpc("generated_transactions_state", {
            "p_actor_id": actor.id, "p_merchant_id": actor.merchant_id,
            "p_company_id": str(company_id) if company_id is not None else None,
            "p_period_ym": period_ym,
        })

    def generated_seed(self, actor: UserProfile, company_id: str | UUID, period_ym: str) -> dict[str, Any]:
        return self.client.rpc("generate_company_month_transactions", {
            "p_actor_id": actor.id, "p_merchant_id": actor.merchant_id,
            "p_company_id": str(company_id), "p_period_ym": period_ym,
        })

    def _generated_action(self, name: str, actor: UserProfile, company_id: str | UUID, period_ym: str) -> dict[str, Any]:
        return self.client.rpc(name, {
            "p_actor_id": actor.id, "p_merchant_id": actor.merchant_id,
            "p_company_id": str(company_id), "p_period_ym": period_ym,
        })

    def generated_create(self, actor: UserProfile, company_id: str | UUID, period_ym: str) -> dict[str, Any]:
        return self._generated_action("generated_transactions_create_settlement", actor, company_id, period_ym)

    def generated_confirm(self, actor: UserProfile, company_id: str | UUID, period_ym: str) -> dict[str, Any]:
        return self._generated_action("generated_transactions_confirm", actor, company_id, period_ym)

    def generated_assert_issue(self, actor: UserProfile, company_id: str | UUID, period_ym: str) -> dict[str, Any]:
        return self._generated_action("generated_transactions_assert_issue", actor, company_id, period_ym)

    def generated_mark_paid(self, actor: UserProfile, company_id: str | UUID, period_ym: str) -> dict[str, Any]:
        return self._generated_action("generated_transactions_mark_paid", actor, company_id, period_ym)

    def generated_reset(self, actor: UserProfile, company_id: str | UUID, period_ym: str, idempotency_key: str) -> dict[str, Any]:
        return self.client.rpc("reset_generated_company_month_state", {
            "p_actor_id": actor.id, "p_merchant_id": actor.merchant_id,
            "p_company_id": str(company_id), "p_period_ym": period_ym,
            "p_idempotency_key": idempotency_key,
        })

    def is_generated_settlement(self, merchant_id: str, settlement_id: str | UUID) -> bool:
        rows = self.client.rest_get("generated_transaction_runs", {
            "select": "id", "merchant_id": f"eq.{merchant_id}",
            "settlement_id": f"eq.{settlement_id}", "limit": "1",
        })
        return bool(rows)

    def is_demo_settlement(self, merchant_id: str, settlement_id: str | UUID) -> bool:
        """Check explicit demo membership with both document and tenant scope."""
        rows = self.client.rest_get("settlement_demo_runs", {
            "select": "id", "merchant_id": f"eq.{merchant_id}",
            "settlement_id": f"eq.{settlement_id}", "limit": "1",
        })
        return bool(rows)

    def is_company_demo_settlement(self, company_id: str, settlement_id: str | UUID) -> bool:
        """Check explicit membership through the authenticated company tenant."""
        rows = self.client.rest_get("settlement_demo_runs", {
            "select": "id", "company_id": f"eq.{company_id}",
            "settlement_id": f"eq.{settlement_id}", "limit": "1",
        })
        return bool(rows)

    def has_current_demo(self, merchant_id: str) -> bool:
        rows = self.client.rest_get("settlement_demo_runs", {
            "select": "id", "merchant_id": f"eq.{merchant_id}",
            "is_current": "eq.true", "limit": "1",
        })
        return bool(rows)

    def _detail(
        self, settlement_id: str | UUID, tenant_column: str, tenant_id: str, *,
        include_demo: bool = False, include_transactions: bool = False,
        company_visible_only: bool = False,
    ) -> dict[str, Any] | None:
        params = {
            "select": LIST_FIELDS, "id": f"eq.{settlement_id}", tenant_column: f"eq.{tenant_id}", "limit": "1",
        }
        if company_visible_only:
            params["settlement_status"] = f"in.({','.join(COMPANY_VISIBLE_SETTLEMENT_STATUSES)})"
        rows = self.client.rest_get("settlements" if include_demo else "normal_settlements", params)
        if not rows:
            return None
        row = rows[0]
        invoices = self.client.rest_get("tax_invoices", {
            "select": INVOICE_FIELDS,
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
        supplier = self.client.rest_get("merchants", {
            "select": "name,biz_reg_no,representative_name,address,business_type,business_item,tax_invoice_email,contact_phone:owner_phone,bank_name,account_number,account_holder",
            "id": f"eq.{row['merchant_id']}", "limit": "1",
        })
        payments = self.client.rest_get("settlement_payments", {
            "select": PAYMENT_FIELDS,
            "settlement_id": f"eq.{settlement_id}", "order": "created_at.asc,id.asc",
        })
        transactions = self._settlement_transactions(row) if include_transactions else []
        return {**row, "business_information": company[0] if company else None,
                "supplier_information": supplier[0] if supplier else None,
                "tax_invoices": invoices, "events": events, "payments": payments,
                "transactions": transactions}

    def _settlement_transactions(self, settlement: dict[str, Any]) -> list[dict[str, Any]]:
        period_from = date.fromisoformat(str(settlement["period_from"]))
        period_to = date.fromisoformat(str(settlement["period_to"])) + timedelta(days=1)
        params = {
            "select": TRANSACTION_FIELDS,
            "merchant_id": f"eq.{settlement['merchant_id']}",
            "company_id": f"eq.{settlement['company_id']}",
            "pay_type": "in.(ledger,subsidized)",
            "kind": "in.(spend,refund,cancel)",
            "and": (
                f"(created_at.gte.{period_from.isoformat()}T00:00:00+09:00,"
                f"created_at.lt.{period_to.isoformat()}T00:00:00+09:00)"
            ),
            "order": "created_at.asc,id.asc",
        }
        rows: list[dict[str, Any]] = []
        page_size = 1000
        while True:
            page = self.client.rest_get("meal_transactions", {
                **params, "limit": str(page_size), "offset": str(len(rows)),
            })
            rows.extend(page)
            if len(page) < page_size:
                break

        users: dict[str, dict[str, Any]] = {}
        user_ids = sorted({str(row["user_id"]) for row in rows if row.get("user_id")})
        for start in range(0, len(user_ids), 100):
            chunk = user_ids[start:start + 100]
            user_rows = self.client.rest_get("app_users", {
                "select": "id,display_name,employee_no,department",
                "id": f"in.({','.join(chunk)})",
            })
            users.update({str(user["id"]): user for user in user_rows})

        result = []
        for row in rows:
            user = users.get(str(row.get("user_id")), {})
            sign = 1 if row.get("kind") == "spend" else -1
            result.append({
                "id": row.get("id"),
                "created_at": row.get("created_at"),
                "employee_name": user.get("display_name") or "직원",
                "employee_no": user.get("employee_no"),
                "department": user.get("department"),
                "kind": row.get("kind"),
                "pay_type": row.get("pay_type"),
                "item": row.get("product_name") or row.get("meal_window") or "식대 사용",
                "tx_code": row.get("tx_code"),
                "tax_type": row.get("settlement_tax_type"),
                "supply_amount": sign * int(row.get("settlement_supply_amount") or 0),
                "vat_amount": sign * int(row.get("settlement_vat_amount") or 0),
                "total_amount": sign * int(row.get("settlement_total_amount") or 0),
                "is_demo": bool(row.get("is_demo")),
            })
        return result

    def company_detail(
        self, settlement_id: str | UUID, company_id: str, *, include_transactions: bool = False,
    ) -> dict[str, Any] | None:
        return self._detail(
            settlement_id, "company_id", company_id,
            include_transactions=include_transactions, company_visible_only=True,
        )

    def merchant_detail(
        self, settlement_id: str | UUID, merchant_id: str, *, include_transactions: bool = False,
    ) -> dict[str, Any] | None:
        return self._detail(settlement_id, "merchant_id", merchant_id, include_transactions=include_transactions)

    def merchant_demo_detail(
        self, settlement_id: str | UUID, merchant_id: str, *, include_transactions: bool = False,
    ) -> dict[str, Any] | None:
        """Demo-panel-only detail path after explicit run membership validation."""
        if not self.is_demo_settlement(merchant_id, settlement_id):
            return None
        return self._detail(
            settlement_id, "merchant_id", merchant_id,
            include_demo=True, include_transactions=include_transactions,
        )

    def demo_invoice_management_key(self, merchant_id: str, settlement_id: str | UUID) -> str | None:
        """Resolve a provider key only for an explicitly merchant-owned demo run."""
        if not self.is_demo_settlement(merchant_id, settlement_id):
            return None
        invoices = self.client.rest_get("tax_invoices", {
            "select": "invoicer_mgt_key", "settlement_id": f"eq.{settlement_id}",
            "merchant_id": f"eq.{merchant_id}", "document_type": "eq.original", "limit": "1",
        })
        return invoices[0].get("invoicer_mgt_key") if invoices else None

    def confirm(self, actor: UserProfile, settlement_id: str | UUID) -> dict[str, Any]:
        return self.client.rpc("company_confirm_and_request_tax_invoice", {
            "p_actor_id": actor.id, "p_company_id": actor.company_id, "p_settlement_id": str(settlement_id),
        })

    def dispute(self, actor: UserProfile, settlement_id: str | UUID, reason: str, key: str) -> dict[str, Any]:
        return self.client.rpc("company_dispute_settlement", {
            "p_actor_id": actor.id, "p_company_id": actor.company_id, "p_settlement_id": str(settlement_id),
            "p_reason": reason, "p_idempotency_key": key,
        })

    def send(self, actor: UserProfile, settlement_id: str | UUID) -> dict[str, Any]:
        return self.client.rpc("merchant_send_settlement", {
            "p_actor_id": actor.id, "p_merchant_id": actor.merchant_id, "p_settlement_id": str(settlement_id),
        })

    def begin_revision(self, actor: UserProfile, settlement_id: str | UUID) -> dict[str, Any]:
        return self.client.rpc("merchant_begin_settlement_revision", {
            "p_actor_id": actor.id, "p_merchant_id": actor.merchant_id,
            "p_settlement_id": str(settlement_id),
        })

    def mark_paid(self, actor: UserProfile, settlement_id: str | UUID, payload: Any) -> dict[str, Any]:
        return self.client.rpc("merchant_mark_settlement_paid", {
            "p_actor_id": actor.id, "p_merchant_id": actor.merchant_id, "p_settlement_id": str(settlement_id),
            "p_amount": payload.amount, "p_depositor_name": payload.depositor_name,
            "p_deposited_at": payload.deposited_at.isoformat(), "p_memo": payload.memo,
            "p_idempotency_key": payload.idempotency_key,
        })

    def claim_invoice_issue(self, actor: UserProfile, settlement_id: str | UUID) -> dict[str, Any]:
        return self.client.rpc("merchant_claim_tax_invoice_issue", {
            "p_actor_id": actor.id, "p_merchant_id": actor.merchant_id,
            "p_settlement_id": str(settlement_id),
        })

    def finalize_invoice_issue(
        self, actor: UserProfile, settlement_id: str | UUID, attempt_token: str | UUID,
        outcome: str, failure_code: str | None = None, failure_message: str | None = None,
    ) -> dict[str, Any]:
        return self.client.rpc("merchant_finalize_tax_invoice_issue", {
            "p_actor_id": actor.id, "p_merchant_id": actor.merchant_id,
            "p_settlement_id": str(settlement_id), "p_attempt_token": str(attempt_token),
            "p_outcome": outcome, "p_failure_code": failure_code,
            "p_failure_message": failure_message,
        })

    def apply_invoice_status(self, actor: UserProfile, settlement_id: str | UUID, status: Any) -> dict[str, Any]:
        return self.client.rpc("merchant_apply_tax_invoice_status", {
            "p_actor_id": actor.id, "p_merchant_id": actor.merchant_id,
            "p_settlement_id": str(settlement_id), "p_state_code": status.provider_state_code,
            "p_nts_result": status.nts_result_code,
            "p_nts_confirm_num": status.nts_confirm_number,
            "p_issued_at": status.issued_at, "p_nts_sent_at": status.nts_sent_at,
            "p_nts_result_at": status.nts_result_at,
        })

    def reset_stale_invoice_issue(
        self, actor: UserProfile, settlement_id: str | UUID, attempt_token: str | UUID,
        management_key_in_use: bool,
    ) -> dict[str, Any]:
        return self.client.rpc("merchant_reset_stale_tax_invoice_issue", {
            "p_actor_id": actor.id, "p_merchant_id": actor.merchant_id,
            "p_settlement_id": str(settlement_id), "p_attempt_token": str(attempt_token),
            "p_management_key_in_use": management_key_in_use,
        })

    def original_invoice_management_key(
        self, actor: UserProfile, settlement_id: str | UUID
    ) -> str | None:
        """Fetch provider identity only through an independently tenant-scoped path."""
        tenant_column = "company_id" if actor.role == "company_admin" else "merchant_id"
        tenant_id = actor.company_id if actor.role == "company_admin" else actor.merchant_id
        if not tenant_id:
            return None
        settlements = self.client.rest_get("normal_settlements", {
            "select": "id", "id": f"eq.{settlement_id}", tenant_column: f"eq.{tenant_id}", "limit": "1",
        })
        if not settlements:
            return None
        invoices = self.client.rest_get("tax_invoices", {
            "select": "invoicer_mgt_key", "settlement_id": f"eq.{settlement_id}",
            "document_type": "eq.original", tenant_column: f"eq.{tenant_id}", "limit": "1",
        })
        return invoices[0].get("invoicer_mgt_key") if invoices else None
