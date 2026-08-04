from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from app.repositories.settlements import (
    COMPANY_VISIBLE_SETTLEMENT_STATUSES, LIST_FIELDS, LIST_INVOICE_FIELDS, PAYMENT_FIELDS, TRANSACTION_FIELDS,
    SettlementRepository,
)
from app.services.join_flow import UserProfile


class DetailClient:
    def __init__(self):
        self.calls = []

    def rest_get(self, table, params):
        self.calls.append((table, params))
        if table == "settlement_demo_runs":
            return [{"id": "run-1"}]
        if table in {"normal_settlements", "settlements"}:
            tenant_filter = params.get("company_id") or params.get("merchant_id")
            if tenant_filter not in {"eq.company-own", "eq.merchant-own"}:
                return []
            return [{
                "id": "settlement-1",
                "company_id": "company-own",
                "merchant_id": "merchant-own",
                "period_from": "2026-07-01",
                "period_to": "2026-07-31",
            }]
        if table == "tax_invoices":
            return []
        if table == "settlement_events":
            return []
        if table == "companies":
            return [{"id": "company-own", "name": "Company"}]
        if table == "merchants":
            return [{
                "name": "Merchant", "bank_name": "그린은행",
                "account_number": "123-456", "account_holder": "Merchant Owner",
            }]
        if table == "settlement_payments":
            return [{
                "id": "payment-1",
                "amount": 400,
                "depositor_name": "Depositor",
                "deposited_at": "2026-07-01T00:00:00Z",
                "memo": "first payment",
                "confirmed_at": "2026-07-01T00:01:00Z",
                "created_at": "2026-07-01T00:01:00Z",
            }]
        if table in {"normal_meal_transactions", "meal_transactions"}:
            return [{
                "id": "transaction-1", "user_id": "user-1", "kind": "spend",
                "tx_code": "TX-1", "meal_window": "중식", "product_name": None,
                "pay_type": "ledger", "is_demo": table == "meal_transactions", "settlement_tax_type": "taxable",
                "settlement_supply_amount": 6455, "settlement_vat_amount": 645,
                "settlement_total_amount": 7100, "created_at": "2026-07-01T03:00:00Z",
            }]
        if table == "app_users":
            return [{"id": "user-1", "display_name": "김직원", "employee_no": "A-1", "department": "개발팀"}]
        raise AssertionError(f"unexpected table: {table}")


def repository_with(client):
    repository = SettlementRepository.__new__(SettlementRepository)
    repository.client = client
    return repository


class RpcClient:
    def __init__(self):
        self.calls = []

    def rpc(self, name, payload):
        # Exercise the real JSON boundary instead of accepting arbitrary Python objects.
        import json
        json.dumps(payload)
        self.calls.append((name, payload))
        return {"ok": True}


def test_workflow_rpc_boundaries_serialize_fastapi_uuid_parameters_as_strings():
    client = RpcClient()
    repository = repository_with(client)
    settlement_id = UUID("11111111-1111-4111-8111-111111111111")
    attempt_token = UUID("22222222-2222-4222-8222-222222222222")
    actor = UserProfile(
        id="actor-1", email="actor@example.com", display_name="Actor",
        company_id="company-1", merchant_id="merchant-1", role="merchant_admin", status="active",
    )
    payment = SimpleNamespace(
        amount=100, depositor_name="입금자", deposited_at=datetime.now(timezone.utc),
        memo=None, idempotency_key="payment-key",
    )
    provider_status = SimpleNamespace(
        provider_state_code="300", nts_result_code=None, nts_confirm_number=None,
        issued_at=None, nts_sent_at=None, nts_result_at=None,
    )

    repository.confirm(actor, settlement_id)
    repository.dispute(actor, settlement_id, "금액 확인", "dispute-key")
    repository.send(actor, settlement_id)
    repository.begin_revision(actor, settlement_id)
    repository.update_period(actor, settlement_id, SimpleNamespace(
        period_from=date(2026, 7, 2), period_to=date(2026, 7, 30),
        idempotency_key="period-key",
    ))
    repository.mark_paid(actor, settlement_id, payment)
    repository.claim_invoice_issue(actor, settlement_id)
    repository.finalize_invoice_issue(actor, settlement_id, attempt_token, "issued")
    repository.apply_invoice_status(actor, settlement_id, provider_status)
    repository.reset_stale_invoice_issue(actor, settlement_id, attempt_token, False)

    assert len(client.calls) == 10
    for _, payload in client.calls:
        assert payload["p_settlement_id"] == str(settlement_id)
    token_payloads = [payload for _, payload in client.calls if "p_attempt_token" in payload]
    assert token_payloads and all(payload["p_attempt_token"] == str(attempt_token) for payload in token_payloads)
    period_call = next(call for call in client.calls if call[0] == "merchant_update_settlement_period")
    assert period_call[1] == {
        "p_actor_id": "actor-1", "p_merchant_id": "merchant-1",
        "p_settlement_id": str(settlement_id), "p_period_from": "2026-07-02",
        "p_period_to": "2026-07-30", "p_idempotency_key": "period-key",
    }


def test_company_detail_includes_same_ordered_public_payment_history_as_merchant_detail():
    company_client = DetailClient()
    company = repository_with(company_client).company_detail("settlement-1", "company-own")
    merchant_client = DetailClient()
    merchant = repository_with(merchant_client).merchant_detail("settlement-1", "merchant-own")

    assert company is not None
    assert merchant is not None
    assert company["payments"] == merchant["payments"]
    assert [payment["amount"] for payment in company["payments"]] == [400]
    assert company["supplier_information"]["bank_name"] == "그린은행"
    assert merchant["supplier_information"]["account_number"] == "123-456"

    for client in (company_client, merchant_client):
        supplier_call = next(params for table, params in client.calls if table == "merchants")
        assert {"bank_name", "account_number", "account_holder"} <= set(supplier_call["select"].split(","))
        payment_calls = [params for table, params in client.calls if table == "settlement_payments"]
        assert payment_calls == [{
            "select": PAYMENT_FIELDS,
            "settlement_id": "eq.settlement-1",
            "order": "created_at.asc,id.asc",
        }]
        selected_fields = set(payment_calls[0]["select"].split(","))
        assert selected_fields.isdisjoint({
            "match_method", "confirmed_by", "idempotency_key", "external_reference",
            "audit_metadata", "created_by", "updated_by",
        })


def test_settlement_detail_includes_period_transactions_with_snapshot_amounts_and_people():
    client = DetailClient()
    detail = repository_with(client).merchant_detail(
        "settlement-1", "merchant-own", include_transactions=True,
    )

    assert detail is not None
    assert detail["transactions"] == [{
        "id": "transaction-1", "created_at": "2026-07-01T03:00:00Z",
        "employee_name": "김직원", "employee_no": "A-1", "department": "개발팀",
        "kind": "spend", "pay_type": "ledger", "meal_window": "중식",
        "item": "중식", "tx_code": "TX-1",
        "tax_type": "taxable", "supply_amount": 6455, "vat_amount": 645,
        "total_amount": 7100, "is_demo": False,
    }]
    transaction_calls = [params for table, params in client.calls if table == "normal_meal_transactions"]
    assert transaction_calls == [{
        "select": TRANSACTION_FIELDS,
        "merchant_id": "eq.merchant-own", "company_id": "eq.company-own",
        "pay_type": "in.(ledger,subsidized)", "kind": "in.(spend,refund,cancel)",
        "and": "(created_at.gte.2026-07-01T00:00:00+09:00,created_at.lt.2026-08-01T00:00:00+09:00)",
        "order": "created_at.asc,id.asc", "limit": "1000", "offset": "0",
    }]


def test_company_detail_cross_tenant_denial_does_not_query_payment_history():
    client = DetailClient()

    assert repository_with(client).company_detail("settlement-1", "company-other") is None
    assert client.calls == [("normal_settlements", {
        "select": LIST_FIELDS,
        "id": "eq.settlement-1",
        "company_id": "eq.company-other",
        "limit": "1",
        "settlement_status": f"in.({','.join(COMPANY_VISIBLE_SETTLEMENT_STATUSES)})",
    })]
    assert all(table != "settlement_payments" for table, _ in client.calls)


def test_company_reads_apply_server_side_workflow_visibility_boundary():
    client = DetailClient()
    repository = repository_with(client)

    repository.list_company("company-own", 20, 0, "2026-07")
    repository.company_detail("settlement-1", "company-own")

    expected = f"in.({','.join(COMPANY_VISIBLE_SETTLEMENT_STATUSES)})"
    list_params = client.calls[0][1]
    detail_params = next(params for table, params in client.calls
                         if table == "normal_settlements" and "id" in params)
    assert list_params["settlement_status"] == expected
    assert detail_params["settlement_status"] == expected
    assert not {"draft", "calculating", "revising"} & set(COMPANY_VISIBLE_SETTLEMENT_STATUSES)
    assert {"sent", "disputed", "completed"} <= set(COMPANY_VISIBLE_SETTLEMENT_STATUSES)


def test_demo_detail_explicitly_uses_base_tables_while_normal_detail_uses_filtered_views():
    normal_client = DetailClient()
    normal = repository_with(normal_client).merchant_detail(
        "settlement-1", "merchant-own", include_transactions=True,
    )
    demo_client = DetailClient()
    demo = repository_with(demo_client).merchant_demo_detail(
        "settlement-1", "merchant-own", include_transactions=True,
    )

    assert normal_client.calls[0][0] == "normal_settlements"
    assert any(table == "normal_meal_transactions" for table, _ in normal_client.calls)
    assert all(table != "meal_transactions" for table, _ in normal_client.calls)
    assert normal is not None and normal["transactions"][0]["is_demo"] is False
    assert demo_client.calls[0][0] == "settlement_demo_runs"
    assert demo_client.calls[1][0] == "settlements"
    assert any(table == "meal_transactions" for table, _ in demo_client.calls)
    assert all(table != "normal_meal_transactions" for table, _ in demo_client.calls)
    assert demo is not None and demo["transactions"][0]["is_demo"] is True


class ListNameClient:
    def __init__(self):
        self.calls = []

    def rest_get(self, table, params):
        self.calls.append((table, params))
        if table in {"normal_settlements", "settlements"}:
            return [{
                "id": "settlement-1", "company_id": "company-1",
                "merchant_id": "merchant-1", "period_ym": "2026-07",
                "is_demo": table == "settlements",
            }]
        if table == "merchants":
            return [{"id": "merchant-1", "name": "그린 식당"}]
        if table == "companies":
            return [{"id": "company-1", "name": "그린 업체"}]
        if table == "tax_invoices":
            return [{
                "id": "invoice-1", "settlement_id": "settlement-1",
                "document_type": "original", "write_date": "2026-07-31",
                "nts_confirm_num": "NTS-1", "issued_at": "2026-08-01T01:00:00Z",
                "failure_message": "provider internal detail",
                "supplier_snapshot": {"bank_name": "비공개 은행"},
                "recipient_snapshot": {
                    "name": "그린 업체", "biz_reg_no": "1234567890",
                    "tax_email": "private@example.test",
                },
            }]
        raise AssertionError(f"unexpected table: {table}")


def test_lists_attach_only_safe_party_names_without_deposit_information():
    company_client = ListNameClient()
    company_rows = repository_with(company_client).list_company("company-1", 20, 0)
    merchant_client = ListNameClient()
    merchant_rows = repository_with(merchant_client).list_merchant("merchant-1", 20, 0)

    assert company_rows[0]["supplier_information"] == {"name": "그린 식당"}
    assert merchant_rows[0]["business_information"] == {"name": "그린 업체"}
    assert merchant_rows[0]["tax_invoices"] == [{
        "document_type": "original", "write_date": "2026-07-31",
        "nts_confirm_num": "NTS-1", "issued_at": "2026-08-01T01:00:00Z",
        "recipient_snapshot": {"name": "그린 업체", "biz_reg_no": "1234567890"},
    }]
    assert merchant_rows[0]["is_demo"] is True
    assert merchant_client.calls[0][0] == "settlements"
    assert company_client.calls[1] == (
        "merchants", {"select": "id,name", "id": "in.(merchant-1)"},
    )
    assert merchant_client.calls[1] == (
        "companies", {"select": "id,name", "id": "in.(company-1)"},
    )
    assert merchant_client.calls[2] == (
        "tax_invoices", {
            "select": LIST_INVOICE_FIELDS,
            "settlement_id": "in.(settlement-1)",
            "document_type": "eq.original",
        },
    )
    for client in (company_client, merchant_client):
        selected = set(client.calls[1][1]["select"].split(","))
        assert selected == {"id", "name"}
        assert selected.isdisjoint({"bank_name", "account_number", "account_holder"})
