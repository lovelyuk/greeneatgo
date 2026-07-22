from types import SimpleNamespace
from unittest.mock import patch

from app.routers.merchant_admin import payment_history, refund_purchase_order
from app.schemas import MerchantRefundRequest
from app.services.refunds import calculate_refund


def _vouchers(used: int, paid: int, bonus: int):
    rows = []
    for index in range(1, paid + bonus + 1):
        rows.append({"issue_index": index, "status": "used" if index <= used else "unused"})
    return rows


def test_ten_plus_one_one_used_refunds_nine_and_forfeits_bonus():
    order = {"status": "done", "pay_type": "voucher", "amount": 80_000, "paid_voucher_count": 10}
    quote = calculate_refund(order, _vouchers(used=1, paid=10, bonus=1))
    assert quote.refundable is True
    assert quote.refund_amount == 72_000
    assert quote.refunded_voucher_count == 9
    assert quote.forfeited_voucher_count == 1


def test_paid_exhausted_allows_zero_cash_bonus_forfeit():
    order = {"status": "done", "pay_type": "voucher", "amount": 80_000, "paid_voucher_count": 10}
    quote = calculate_refund(order, _vouchers(used=10, paid=10, bonus=1))
    assert quote.refundable is True
    assert quote.refund_amount == 0
    assert quote.reason == "PAID_VOUCHERS_EXHAUSTED"
    assert quote.forfeited_voucher_count == 1


def test_subsidized_card_and_points_are_both_restored():
    order = {"status": "done", "pay_type": "subsidized", "amount": 3_000, "point_amount": 2_000}
    quote = calculate_refund(order, [{"issue_index": 1, "status": "unused"}])
    assert quote.refundable is True
    assert quote.refund_amount == 3_000
    assert quote.point_amount == 2_000
    assert quote.refunded_voucher_count == 1


def test_subsidized_point_only_does_not_require_card_refund():
    order = {"status": "done", "pay_type": "subsidized", "amount": 0, "point_amount": 5_000}
    quote = calculate_refund(order, [{"issue_index": 1, "status": "unused"}])
    assert quote.refundable is True
    assert quote.refund_amount == 0
    assert quote.point_amount == 5_000


def test_used_subsidized_voucher_is_not_refundable():
    order = {"status": "done", "pay_type": "subsidized", "amount": 3_000, "point_amount": 2_000}
    quote = calculate_refund(order, [{"issue_index": 1, "status": "used"}])
    assert quote.refundable is False
    assert quote.reason == "ORDER_ALREADY_USED"


def test_refund_never_exceeds_remaining_payment_balance():
    order = {"status": "done", "pay_type": "voucher", "amount": 100, "paid_voucher_count": 3}
    quote = calculate_refund(order, _vouchers(used=0, paid=3, bonus=0), already_refunded=50)
    assert quote.refund_amount == 50


@patch("app.routers.merchant_admin.cancel_payment")
@patch("app.routers.merchant_admin.JoinRepository")
def test_point_only_refund_skips_pg_and_finalizes_atomically(repo_class, cancel):
    repo = repo_class.return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-123", email="a@example.com")
    repo.get_profile.return_value = SimpleNamespace(
        id="admin-123", role="merchant_admin", status="active", merchant_id="merchant-1"
    )
    repo.client.rest_get.return_value = [{
        "id": "internal-order", "order_id": "GE-S-order123", "user_id": "account-123",
        "merchant_id": "merchant-1", "pay_type": "subsidized", "status": "done",
        "amount": 0, "point_amount": 5000, "provider_payment_key": None,
    }]
    repo.client.rpc.side_effect = [
        {"refund_request_id": "refund-1", "refund_amount": 0, "point_amount": 5000},
        {"refund_request_id": "refund-1", "status": "completed", "point_amount": 5000},
    ]

    result = refund_purchase_order(MerchantRefundRequest(
        account_id="account-123", order_id="GE-S-order123"
    ), "token")

    assert result["data"]["status"] == "completed"
    cancel.assert_not_called()
    assert repo.client.rpc.call_args_list[0].args[0] == "claim_purchase_order_refund"
    assert repo.client.rpc.call_args_list[1].args[0] == "finalize_purchase_order_refund"


@patch("app.routers.merchant_admin.cancel_payment")
@patch("app.routers.merchant_admin.get_settings")
@patch("app.routers.merchant_admin.JoinRepository")
def test_card_refund_uses_claimed_amount_and_order_provider_payment_key(repo_class, settings, cancel):
    repo = repo_class.return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-123", email="a@example.com")
    repo.get_profile.return_value = SimpleNamespace(
        id="admin-123", role="merchant_admin", status="active", merchant_id="merchant-1"
    )
    repo.client.rest_get.return_value = [{
        "id": "internal-order", "order_id": "GE-V-order123", "user_id": "account-123",
        "merchant_id": "merchant-1", "pay_type": "voucher", "status": "done",
        "amount": 80000, "point_amount": 0, "provider_payment_key": "pay-key",
        "payment_method": "CARD",
    }]
    repo.client.rpc.side_effect = [
        {"refund_request_id": "refund-1", "refund_amount": 72000, "provider_payment_key": "pay-key"},
        {"status": "completed", "refund_amount": 72000},
    ]
    settings.return_value.kiwoompay_base_url = "https://apitest.kiwoompay.co.kr"
    settings.return_value.kiwoompay_authorization_key = "auth-key"
    settings.return_value.kiwoompay_cpid = "CPID"
    cancel.return_value = {"RESULTCODE": "0000", "AMOUNT": "72000"}

    refund_purchase_order(MerchantRefundRequest(
        account_id="account-123", order_id="GE-V-order123"
    ), "token")

    assert cancel.call_args.args == (
        "https://apitest.kiwoompay.co.kr", "auth-key", "CPID", "pay-key", 72000,
    )
    assert cancel.call_args.kwargs["pay_method"] == "CARD"
    finalize = repo.client.rpc.call_args_list[1].args[1]
    assert finalize["p_pg_response"]["RESULTCODE"] == "0000"


@patch("app.routers.merchant_admin.cancel_payment")
@patch("app.routers.merchant_admin.get_settings")
@patch("app.routers.merchant_admin.JoinRepository")
def test_bank_refund_uses_bank_cancel_method(repo_class, settings, cancel):
    repo = repo_class.return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-123", email="a@example.com")
    repo.get_profile.return_value = SimpleNamespace(
        id="admin-123", role="merchant_admin", status="active", merchant_id="merchant-1"
    )
    repo.client.rest_get.return_value = [{
        "id": "internal-order", "order_id": "GE-V-bank123", "user_id": "account-123",
        "merchant_id": "merchant-1", "pay_type": "voucher", "status": "done",
        "amount": 80000, "point_amount": 0, "provider_payment_key": "bank-trx",
        "payment_method": "BANK",
    }]
    repo.client.rpc.side_effect = [
        {"refund_request_id": "refund-bank", "refund_amount": 80000,
         "provider_payment_key": "bank-trx"},
        {"status": "completed", "refund_amount": 80000},
    ]
    settings.return_value.kiwoompay_base_url = "https://apitest.kiwoompay.co.kr"
    settings.return_value.kiwoompay_authorization_key = "auth-key"
    settings.return_value.kiwoompay_cpid = "CPID"
    cancel.return_value = {"RESULTCODE": "0000", "AMOUNT": "80000"}

    refund_purchase_order(MerchantRefundRequest(
        account_id="account-123", order_id="GE-V-bank123"
    ), "token")

    assert cancel.call_args.kwargs["pay_method"] == "BANK"


@patch("app.routers.merchant_admin.cancel_payment")
@patch("app.routers.merchant_admin.get_settings")
@patch("app.routers.merchant_admin.JoinRepository")
def test_naverpay_refund_preserves_original_cancel_method(repo_class, settings, cancel):
    repo = repo_class.return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-123", email="a@example.com")
    repo.get_profile.return_value = SimpleNamespace(
        id="admin-123", role="merchant_admin", status="active", merchant_id="merchant-1"
    )
    repo.client.rest_get.return_value = [{
        "id": "internal-order", "order_id": "GE-V-naver123", "user_id": "account-123",
        "merchant_id": "merchant-1", "pay_type": "voucher", "status": "done",
        "amount": 8000, "point_amount": 0, "provider_payment_key": "naver-trx",
        "payment_method": "NAVERPAY",
    }]
    repo.client.rpc.side_effect = [
        {"refund_request_id": "refund-naver", "refund_amount": 8000,
         "provider_payment_key": "naver-trx"},
        {"status": "completed", "refund_amount": 8000},
    ]
    settings.return_value.kiwoompay_base_url = "https://apitest.kiwoompay.co.kr"
    settings.return_value.kiwoompay_authorization_key = "auth-key"
    settings.return_value.kiwoompay_cpid = "CPID"
    cancel.return_value = {"RESULTCODE": "0000", "AMOUNT": "8000"}

    refund_purchase_order(MerchantRefundRequest(
        account_id="account-123", order_id="GE-V-naver123"
    ), "token")

    assert cancel.call_args.kwargs["pay_method"] == "NAVERPAY"


@patch("app.routers.merchant_admin.JoinRepository")
def test_payment_history_separates_usage_payments_and_refunds(repo_class):
    repo = repo_class.return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-123", email="a@example.com")
    repo.get_profile.return_value = SimpleNamespace(
        id="admin-123", role="merchant_admin", status="active", merchant_id="merchant-1"
    )
    repo.client.rest_get.side_effect = [
        [{"id": "tx", "user_id": "customer-1", "amount": -8000, "kind": "spend", "pay_type": "voucher", "created_at": "2026-07-18T01:00:00Z"}],
        [{"id": "order", "user_id": "customer-1", "amount": 80000, "point_amount": 0, "pay_type": "subsidized", "approved_at": "2026-07-18T02:00:00Z"}],
        [{"id": "refund", "order_id": "order", "user_id": "customer-1", "refund_amount": 72000, "point_amount": 0, "completed_at": "2026-07-18T03:00:00Z"}],
        [{"id": "order", "pay_type": "subsidized", "product_name": "보조금 식권"}],
        [{"id": "customer-1", "display_name": "홍고객", "company_id": None}],
    ]

    result = payment_history("2026-07-18", "day", "token")

    assert [item["employee_name"] for item in result["data"]["payment"]["items"]] == ["홍고객", "홍고객"]
    assert [item["payment_type_label"] for item in result["data"]["payment"]["items"]] == ["보조금", "보조금"]
    assert result["data"]["payment"]["items"][0]["product_name"] == "보조금 식권"
    assert result["data"]["transaction"]["items"][0] == {
        "id": "tx", "user_id": "customer-1", "amount": -8000, "kind": "spend", "pay_type": "voucher",
        "created_at": "2026-07-18T01:00:00Z", "employee_name": "홍고객", "company_name": "일반 고객",
        "payment_type_label": "일반",
    }
    assert result["data"]["totals"] == {
        "transaction_count": 1, "transaction_amount": 8000,
        "payment_count": 1, "payment_amount": 80000,
        "refund_count": 1, "refund_amount": 72000, "net_payment_amount": 8000,
    }
