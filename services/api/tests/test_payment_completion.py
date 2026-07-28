import json

from app.services.payment_completion import present_payment_completion


PROD = "https://api.kiwoompay.co.kr"
DEV = "https://apitest.kiwoompay.co.kr"
CPID = "merchant CPID"


def _order(**overrides):
    order = {
        "id": "internal-db-id",
        "user_id": "internal-user-id",
        "merchant_id": "internal-merchant-id",
        "order_id": "GE-public-order",
        "status": "done",
        "product_name": "식권 10+1",
        "merchant_name": "그린식당",
        "amount": 72000,
        "pay_type": "voucher",
        "payment_method": "CARD",
        "provider_payment_key": "trx /?&=123",
        "approved_at": "2026-07-27T01:02:03Z",
        "voucher_count": 11,
        "provider_response": {},
    }
    order.update(overrides)
    return order


def test_card_completion_maps_official_production_receipts_and_allowlisted_details():
    result = present_payment_completion(
        _order(provider_response={
            "CARDNAME": "국민카드",
            "CARDNO": "1234-5678-9012-3456",
            "AUTHNO": "approval-1",
        }),
        base_url=PROD,
        cpid=CPID,
    )

    payment, receipts = result["payment"], result["receipts"]
    assert payment["method"] == "CARD"
    assert payment["method_label"] == "카드"
    assert payment["issuer_name"] == "국민카드"
    assert payment["masked_card_number"] == "****-****-****-3456"
    assert payment["authorization_number"] == "approval-1"
    assert receipts["sales_slip_url"] == (
        "https://agent.kiwoompay.co.kr/common/PayInfoPrintDirectCard.jsp?"
        "DAOUTRX=trx+%2F%3F%26%3D123&STATUS=A"
    )
    assert receipts["transaction_confirmation_url"] == (
        "https://agent.kiwoompay.co.kr/common/PayInfoPrint.jsp?"
        "CPID=merchant+CPID&DAOUTRX=trx+%2F%3F%26%3D123"
    )
    assert receipts["cash_receipt_url"] is None
    assert payment["cash_receipt_status"] is None
    assert result["issued_count"] == 11
    assert result["fulfillment"] == {"issued_count": 11, "voucher_balance": None}


def test_naverpay_card_payment_uses_provider_card_receipt_type():
    result = present_payment_completion(
        _order(
            payment_method="NAVERPAY",
            provider_response={
                "PAYMENTTYPE": "CARD",
                "CARDNAME": "신한카드 - 체크",
                "CARDNO": "****-****-****-8900",
            },
        ),
        base_url=PROD,
        cpid="CPID",
    )

    payment, receipts = result["payment"], result["receipts"]
    assert payment["method"] == "NAVERPAY"
    assert payment["method_label"] == "네이버페이"
    assert payment["issuer_name"] == "신한카드 - 체크"
    assert payment["masked_card_number"] == "****-****-****-8900"
    assert "PayInfoPrintDirectCard.jsp" in receipts["sales_slip_url"]
    assert receipts["cash_receipt_url"] is None


def test_bank_completion_uses_official_bank_receipt():
    result = present_payment_completion(
        _order(payment_method="bank", provider_response={"BANKNAME": "테스트은행"}),
        base_url=PROD,
        cpid="CPID",
    )

    payment, receipts = result["payment"], result["receipts"]
    assert payment["method"] == "BANK"
    assert payment["method_label"] == "계좌이체"
    assert payment["bank_name"] == "테스트은행"
    assert payment["issuer_name"] is None
    assert "PayInfoPrintBank.jsp" in receipts["sales_slip_url"]
    assert receipts["sales_slip_url"].endswith("DAOUTRX=trx+%2F%3F%26%3D123&STATUS=A")
    assert receipts["cash_receipt_url"] is None


def test_production_bank_cash_receipt_requires_provider_authorization():
    result = present_payment_completion(
        _order(payment_method="BANK", provider_response={"CASHRECAUTHNO": "cash-auth-1"}),
        base_url=PROD,
        cpid="CPID",
    )

    payment, receipts = result["payment"], result["receipts"]
    assert payment["cash_receipt_authorization_number"] == "cash-auth-1"
    assert payment["cash_receipt_status"] == "ISSUED"
    assert receipts["cash_receipt_url"] == (
        "https://agent.kiwoompay.co.kr/common/CashRecInfoPrint.jsp?"
        "DAOUTRX=trx+%2F%3F%26%3D123"
    )


def test_development_maps_agenttest_but_never_emits_cash_receipt():
    result = present_payment_completion(
        _order(payment_method="BANK", provider_response={"CASHRECAUTHNO": "cash-auth-1"}),
        base_url=DEV,
        cpid="CPID",
    )

    assert result["receipts"]["sales_slip_url"].startswith(
        "https://agenttest.kiwoompay.co.kr/common/"
    )
    assert result["receipts"]["transaction_confirmation_url"].startswith(
        "https://agenttest.kiwoompay.co.kr/common/"
    )
    assert result["receipts"]["cash_receipt_url"] is None
    assert result["payment"]["cash_receipt_status"] is None


def test_unknown_or_malformed_base_host_fails_closed():
    for base_url in (
        "https://evil.example",
        "https://apitest.kiwoompay.co.kr.evil.example",
        "http://apitest.kiwoompay.co.kr",
        "https://user@apitest.kiwoompay.co.kr",
        "https://apitest.kiwoompay.co.kr:8443",
        "https://apitest.kiwoompay.co.kr:bad",
        "https://apitest.kiwoompay.co.kr/path",
        "https://apitest.kiwoompay.co.kr?unexpected=1",
        "https://apitest.kiwoompay.co.kr#unexpected",
        "https://apitest.kiwoompay.co.kr?",
        "https://apitest.kiwoompay.co.kr#",
        "https://apitest.kiwoompay.co.kr?#",
    ):
        result = present_payment_completion(_order(), base_url=base_url, cpid="CPID")
        assert result["receipts"]["sales_slip_url"] is None
        assert result["receipts"]["cash_receipt_url"] is None
        assert result["receipts"]["transaction_confirmation_url"] is None


def test_completion_does_not_expose_raw_card_or_sensitive_provider_and_internal_fields():
    raw_card = "9999888877771234"
    secret = "provider-secret-that-must-not-leak"
    result = present_payment_completion(
        _order(provider_response={
            "CARDNO": raw_card,
            "TOKEN": secret,
            "source_ip": "192.0.2.1",
            "nested": {"secret": secret},
            "DAOUTRX": "payload-transaction-must-be-ignored",
            "PAYMETHOD": "BANK",
            "SETTDATE": "payload-time-must-be-ignored",
        }),
        base_url=PROD,
        cpid="CPID",
    )
    encoded = json.dumps(result, ensure_ascii=False)
    payment = result["payment"]

    assert raw_card not in encoded
    assert "9999" not in payment["masked_card_number"]
    assert payment["masked_card_number"] == "****-****-****-1234"
    assert secret not in encoded
    assert "payload-transaction-must-be-ignored" not in encoded
    assert "payload-time-must-be-ignored" not in encoded
    assert payment["transaction_id"] == "trx /?&=123"
    assert payment["method"] == "CARD"
    assert payment["approved_at"] == "2026-07-27T01:02:03Z"
    assert "provider_response" not in result
    for internal_key in ("id", "user_id", "merchant_id", "provider_payment_key"):
        assert internal_key not in result


def test_legacy_missing_provider_payload_is_safe_and_keeps_nullable_compatibility_fields():
    result = present_payment_completion(
        _order(
            provider_response=None,
            payment_method=None,
            provider_payment_key=None,
            voucher_count=None,
            paid_voucher_count=10,
            bonus_voucher_count=1,
        ),
        base_url=PROD,
        cpid="CPID",
    )

    payment, receipts = result["payment"], result["receipts"]
    assert payment["transaction_id"] is None
    assert payment["method"] is None
    assert payment["issuer_name"] is None
    assert payment["masked_card_number"] is None
    assert receipts["sales_slip_url"] is None
    assert receipts["transaction_confirmation_url"] is None
    assert result["issued_count"] == 11
    assert result["voucher_balance"] is None
