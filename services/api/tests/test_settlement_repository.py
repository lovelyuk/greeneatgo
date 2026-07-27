from app.repositories.settlements import LIST_FIELDS, PAYMENT_FIELDS, SettlementRepository


class DetailClient:
    def __init__(self):
        self.calls = []

    def rest_get(self, table, params):
        self.calls.append((table, params))
        if table == "settlements":
            tenant_filter = params.get("company_id") or params.get("merchant_id")
            if tenant_filter not in {"eq.company-own", "eq.merchant-own"}:
                return []
            return [{
                "id": "settlement-1",
                "company_id": "company-own",
                "merchant_id": "merchant-own",
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


def test_company_detail_cross_tenant_denial_does_not_query_payment_history():
    client = DetailClient()

    assert repository_with(client).company_detail("settlement-1", "company-other") is None
    assert client.calls == [("settlements", {
        "select": LIST_FIELDS,
        "id": "eq.settlement-1",
        "company_id": "eq.company-other",
        "limit": "1",
    })]
    assert all(table != "settlement_payments" for table, _ in client.calls)
