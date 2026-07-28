from app.repositories.settlements import LIST_FIELDS, PAYMENT_FIELDS, TRANSACTION_FIELDS, SettlementRepository


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
            return [{"name": "Merchant"}]
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
        if table == "meal_transactions":
            return [{
                "id": "transaction-1", "user_id": "user-1", "kind": "spend",
                "tx_code": "TX-1", "meal_window": "중식", "product_name": None,
                "pay_type": "ledger", "is_demo": True, "settlement_tax_type": "taxable",
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


def test_company_detail_includes_same_ordered_public_payment_history_as_merchant_detail():
    company_client = DetailClient()
    company = repository_with(company_client).company_detail("settlement-1", "company-own")
    merchant_client = DetailClient()
    merchant = repository_with(merchant_client).merchant_detail("settlement-1", "merchant-own")

    assert company is not None
    assert merchant is not None
    assert company["payments"] == merchant["payments"]
    assert [payment["amount"] for payment in company["payments"]] == [400]

    for client in (company_client, merchant_client):
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
        "kind": "spend", "pay_type": "ledger", "item": "중식", "tx_code": "TX-1",
        "tax_type": "taxable", "supply_amount": 6455, "vat_amount": 645,
        "total_amount": 7100, "is_demo": True,
    }]
    transaction_calls = [params for table, params in client.calls if table == "meal_transactions"]
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
    })]
    assert all(table != "settlement_payments" for table, _ in client.calls)


def test_demo_detail_explicitly_uses_base_table_while_normal_detail_uses_filtered_view():
    normal_client = DetailClient()
    repository_with(normal_client).merchant_detail("settlement-1", "merchant-own")
    demo_client = DetailClient()
    repository_with(demo_client).merchant_demo_detail("settlement-1", "merchant-own")

    assert normal_client.calls[0][0] == "normal_settlements"
    assert demo_client.calls[0][0] == "settlement_demo_runs"
    assert demo_client.calls[1][0] == "settlements"
