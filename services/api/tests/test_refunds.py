from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.repositories.supabase_http import SupabaseHttpError
from app.routers.merchant_admin import payment_history, refund_purchase_order
from app.schemas import MerchantRefundRequest
from app.services.refunds import calculate_refund
from app.services.kiwoom_payment import KiwoomCancellationOutcomeUnknown, KiwoomPaymentError


def _vouchers(used: int, paid: int, bonus: int):
    rows = []
    for index in range(1, paid + bonus + 1):
        rows.append({"issue_index": index, "status": "used" if index <= used else "unused"})
    return rows


def _configure_card_refund_repo(repo, *, order_id="GE-V-safety", transaction_id="safety-trx"):
    repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-123", email="a@example.com")
    repo.get_profile.return_value = SimpleNamespace(
        id="admin-123", role="merchant_admin", status="active", merchant_id="merchant-1"
    )
    repo.client.rest_get.return_value = [{
        "id": "internal-order", "order_id": order_id, "user_id": "account-123",
        "merchant_id": "merchant-1", "pay_type": "voucher", "status": "done",
        "amount": 8000, "point_amount": 0, "provider_payment_key": transaction_id,
        "payment_method": "CARD",
    }]


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


def test_subsidized_package_refunds_only_unused_paid_and_forfeits_bonus():
    order = {"status": "done", "pay_type": "subsidized", "amount": 42_000,
             "point_amount": 10_000, "total_employee_burden": 52_000,
             "paid_voucher_count": 10, "bonus_voucher_count": 1}
    quote = calculate_refund(order, _vouchers(used=2, paid=10, bonus=1))
    assert quote.refundable is True
    assert quote.refund_amount == 33_600
    assert quote.point_amount == 8_000
    assert quote.refunded_voucher_count == 8
    assert quote.forfeited_voucher_count == 1


def test_subsidized_refund_conserves_indivisible_employee_and_point_totals():
    for burden, card in ((10, 9), (11, 10)):
        order = {"status": "done", "pay_type": "subsidized", "amount": card,
                 "point_amount": 1, "total_employee_burden": burden,
                 "paid_voucher_count": 3, "bonus_voucher_count": 0}

        full = calculate_refund(order, _vouchers(used=0, paid=3, bonus=0))
        assert (full.refund_amount, full.point_amount) == (card, 1)


def test_subsidized_partial_refund_uses_conserved_remainder_formula():
    order = {"status": "done", "pay_type": "subsidized", "amount": 10,
             "point_amount": 1, "total_employee_burden": 11,
             "paid_voucher_count": 3, "bonus_voucher_count": 0}

    one_used = calculate_refund(order, _vouchers(used=1, paid=3, bonus=0))
    two_used = calculate_refund(order, _vouchers(used=2, paid=3, bonus=0))

    # Paid snapshots are [4, 4, 3], so FIFO use leaves burdens 7 then 3.
    assert (one_used.refund_amount, one_used.point_amount) == (6, 1)
    assert (two_used.refund_amount, two_used.point_amount) == (2, 1)


def test_subsidized_partial_refund_split_is_exact_and_component_bounded():
    cases = (
        # burden, card, points, paid, used, expected card/points
        (11, 10, 1, 3, 2, (2, 1)),  # reviewer case: total is 3, never 5
        (2, 0, 2, 3, 1, (0, 1)),
        (10, 1, 9, 3, 2, (0, 3)),
        (10, 10, 0, 3, 1, (6, 0)),
    )
    for burden, card, points, paid, used, expected in cases:
        order = {"status": "done", "pay_type": "subsidized", "amount": card,
                 "point_amount": points, "total_employee_burden": burden,
                 "paid_voucher_count": paid}
        quote = calculate_refund(order, _vouchers(used=used, paid=paid, bonus=0))
        base, remainder = divmod(burden, paid)
        exact_remaining = burden - (base * used + min(used, remainder))
        assert (quote.refund_amount, quote.point_amount) == expected
        assert quote.refund_amount + quote.point_amount == exact_remaining
        assert 0 <= quote.refund_amount <= card
        assert 0 <= quote.point_amount <= points


def test_subsidized_corrupt_snapshot_still_cannot_exceed_payment_components():
    order = {"status": "done", "pay_type": "subsidized", "amount": 1,
             "point_amount": 1, "total_employee_burden": 100,
             "paid_voucher_count": 3}
    quote = calculate_refund(order, _vouchers(used=0, paid=3, bonus=0))
    assert (quote.refund_amount, quote.point_amount) == (1, 1)


def test_voucher_full_refund_conserves_indivisible_card_total():
    order = {"status": "done", "pay_type": "voucher", "amount": 100,
             "paid_voucher_count": 3}
    quote = calculate_refund(order, _vouchers(used=0, paid=3, bonus=0))
    assert quote.refund_amount == 100


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
        {"status": "provider_in_flight"},
        {"status": "provider_succeeded"},
        {"refund_request_id": "refund-1", "status": "completed", "point_amount": 5000},
    ]

    result = refund_purchase_order(MerchantRefundRequest(
        account_id="account-123", order_id="GE-S-order123"
    ), "token")

    assert result["data"]["status"] == "completed"
    cancel.assert_not_called()
    assert repo.client.rpc.call_args_list[0].args[0] == "claim_purchase_order_refund"
    assert repo.client.rpc.call_args_list[1].args[0] == "mark_purchase_order_refund_provider_attempt_started"
    assert repo.client.rpc.call_args_list[2].args[0] == "record_purchase_order_refund_provider_success"
    assert repo.client.rpc.call_args_list[3].args[0] == "finalize_purchase_order_refund"


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
    responses = iter([
        {"refund_request_id": "refund-1", "refund_amount": 72000, "provider_payment_key": "pay-key",
         "acquired": True, "processing_token": "lease-token"},
        {"status": "provider_in_flight"},
        {"status": "provider_succeeded"},
        {"status": "completed", "refund_amount": 72000},
    ])
    events = []

    def rpc(name, params):
        events.append(f"rpc:{name}")
        return next(responses)

    repo.client.rpc.side_effect = rpc
    settings.return_value.kiwoompay_base_url = "https://apitest.kiwoompay.co.kr"
    settings.return_value.kiwoompay_authorization_key = "auth-key"
    settings.return_value.kiwoompay_cpid = "CPID"
    def provider_cancel(*args, **kwargs):
        events.append("provider:cancel_payment")
        return {"RESULTCODE": "0000", "AMOUNT": "72000"}

    cancel.side_effect = provider_cancel

    refund_purchase_order(MerchantRefundRequest(
        account_id="account-123", order_id="GE-V-order123"
    ), "token")

    assert cancel.call_args.args == (
        "https://apitest.kiwoompay.co.kr", "auth-key", "CPID", "pay-key", 72000,
    )
    assert cancel.call_args.kwargs["pay_method"] == "CARD"
    assert events.index("rpc:mark_purchase_order_refund_provider_attempt_started") < events.index("provider:cancel_payment")
    assert repo.client.rpc.call_args_list[1].args[0] == "mark_purchase_order_refund_provider_attempt_started"
    record = repo.client.rpc.call_args_list[2].args[1]
    assert record["p_pg_response"]["RESULTCODE"] == "0000"
    assert record["p_processing_token"] == "lease-token"
    finalize = repo.client.rpc.call_args_list[3].args[1]
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
        {"status": "provider_in_flight"},
        {"status": "provider_succeeded"},
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
        {"status": "provider_in_flight"},
        {"status": "provider_succeeded"},
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


@patch("app.routers.merchant_admin.cancel_payment")
@patch("app.routers.merchant_admin.get_settings")
@patch("app.routers.merchant_admin.JoinRepository")
def test_provider_success_survives_finalize_failure_and_retry_skips_second_cancel(repo_class, settings, cancel):
    repo = repo_class.return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-123", email="a@example.com")
    repo.get_profile.return_value = SimpleNamespace(
        id="admin-123", role="merchant_admin", status="active", merchant_id="merchant-1"
    )
    repo.client.rest_get.return_value = [{
        "id": "internal-order", "order_id": "GE-V-retry", "user_id": "account-123",
        "merchant_id": "merchant-1", "pay_type": "voucher", "status": "done",
        "amount": 8000, "point_amount": 0, "provider_payment_key": "retry-trx",
        "payment_method": "CARD",
    }]
    repo.client.rpc.side_effect = [
        {"refund_request_id": "refund-retry", "refund_amount": 8000,
         "provider_payment_key": "retry-trx", "provider_succeeded": False},
        {"status": "provider_in_flight"},
        {"status": "provider_succeeded"},
        SupabaseHttpError(500, "simulated finalize failure"),
        {"refund_request_id": "refund-retry", "refund_amount": 8000,
         "provider_payment_key": "retry-trx", "provider_succeeded": True},
        {"status": "completed", "refund_amount": 8000},
    ]
    settings.return_value.kiwoompay_base_url = "https://apitest.kiwoompay.co.kr"
    settings.return_value.kiwoompay_authorization_key = "auth-key"
    settings.return_value.kiwoompay_cpid = "CPID"
    cancel.return_value = {"RESULTCODE": "0000", "AMOUNT": "8000"}
    payload = MerchantRefundRequest(account_id="account-123", order_id="GE-V-retry")

    with pytest.raises(HTTPException) as first:
        refund_purchase_order(payload, "token")
    assert first.value.status_code == 502

    result = refund_purchase_order(payload, "token")

    assert result["data"]["status"] == "completed"
    cancel.assert_called_once()
    assert [call.args[0] for call in repo.client.rpc.call_args_list] == [
        "claim_purchase_order_refund", "mark_purchase_order_refund_provider_attempt_started",
        "record_purchase_order_refund_provider_success",
        "finalize_purchase_order_refund", "claim_purchase_order_refund",
        "finalize_purchase_order_refund",
    ]


@patch("app.routers.merchant_admin.cancel_payment")
@patch("app.routers.merchant_admin.JoinRepository")
def test_active_refund_lease_returns_409_without_provider_call(repo_class, cancel):
    repo = repo_class.return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-123", email="a@example.com")
    repo.get_profile.return_value = SimpleNamespace(
        id="admin-123", role="merchant_admin", status="active", merchant_id="merchant-1"
    )
    repo.client.rest_get.return_value = [{
        "id": "internal-order", "order_id": "GE-V-active", "user_id": "account-123",
        "merchant_id": "merchant-1", "pay_type": "voucher", "status": "refund_processing",
        "amount": 8000, "point_amount": 0, "provider_payment_key": "active-trx",
        "payment_method": "CARD",
    }]
    repo.client.rpc.return_value = {
        "refund_request_id": "refund-active", "refund_amount": 8000,
        "provider_payment_key": "active-trx", "provider_succeeded": False,
        "acquired": False, "error_code": "REFUND_IN_PROGRESS",
    }

    with pytest.raises(HTTPException) as raised:
        refund_purchase_order(MerchantRefundRequest(
            account_id="account-123", order_id="GE-V-active"
        ), "token")

    assert raised.value.status_code == 409
    assert isinstance(raised.value.detail, dict)
    assert raised.value.detail["code"] == "REFUND_IN_PROGRESS"
    cancel.assert_not_called()
    assert [call.args[0] for call in repo.client.rpc.call_args_list] == [
        "claim_purchase_order_refund"
    ]


@patch("app.routers.merchant_admin.cancel_payment")
@patch("app.routers.merchant_admin.get_settings")
@patch("app.routers.merchant_admin.JoinRepository")
def test_uncertain_cancel_marks_reconciliation_without_fail_or_release(repo_class, settings, cancel):
    repo = repo_class.return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-123", email="a@example.com")
    repo.get_profile.return_value = SimpleNamespace(
        id="admin-123", role="merchant_admin", status="active", merchant_id="merchant-1"
    )
    repo.client.rest_get.return_value = [{
        "id": "internal-order", "order_id": "GE-V-unknown", "user_id": "account-123",
        "merchant_id": "merchant-1", "pay_type": "voucher", "status": "done",
        "amount": 8000, "provider_payment_key": "unknown-trx", "payment_method": "CARD",
    }]
    repo.client.rpc.side_effect = [{
        "refund_request_id": "refund-unknown", "refund_amount": 8000,
        "provider_payment_key": "unknown-trx", "acquired": True, "processing_token": "lease-token",
    }, {"status": "provider_in_flight"}, {"status": "reconciliation_required"}]
    settings.return_value.kiwoompay_base_url = "https://apitest.kiwoompay.co.kr"
    settings.return_value.kiwoompay_authorization_key = "auth"
    settings.return_value.kiwoompay_cpid = "CPID"
    cancel.side_effect = KiwoomCancellationOutcomeUnknown(
        502, "KIWOOMPAY_CANCEL_OUTCOME_UNKNOWN", "manual reconciliation",
        details={"transaction_id": "unknown-trx"},
    )

    with pytest.raises(HTTPException) as raised:
        refund_purchase_order(MerchantRefundRequest(account_id="account-123", order_id="GE-V-unknown"), "token")

    assert raised.value.status_code == 502
    assert [call.args[0] for call in repo.client.rpc.call_args_list] == [
        "claim_purchase_order_refund", "mark_purchase_order_refund_provider_attempt_started",
        "mark_purchase_order_refund_reconciliation_required",
    ]
    marked = repo.client.rpc.call_args_list[2].args[1]
    assert marked["p_processing_token"] == "lease-token"
    assert marked["p_reconciliation_details"]["transaction_id"] == "unknown-trx"


@patch("app.routers.merchant_admin.cancel_payment")
@patch("app.routers.merchant_admin.get_settings")
@patch("app.routers.merchant_admin.JoinRepository")
def test_attempt_start_persistence_failure_never_calls_provider(repo_class, settings, cancel):
    repo = repo_class.return_value
    _configure_card_refund_repo(repo, order_id="GE-V-attempt-fail")
    repo.client.rpc.side_effect = [
        {"refund_request_id": "refund-attempt-fail", "refund_amount": 8000,
         "provider_payment_key": "safety-trx", "acquired": True, "processing_token": "lease-token"},
        SupabaseHttpError(500, "attempt start write failed"),
    ]
    settings.return_value.kiwoompay_base_url = "https://apitest.kiwoompay.co.kr"

    with pytest.raises(HTTPException) as raised:
        refund_purchase_order(
            MerchantRefundRequest(account_id="account-123", order_id="GE-V-attempt-fail"), "token"
        )

    assert raised.value.status_code == 502
    cancel.assert_not_called()
    assert [call.args[0] for call in repo.client.rpc.call_args_list] == [
        "claim_purchase_order_refund", "mark_purchase_order_refund_provider_attempt_started"
    ]


@patch("app.routers.merchant_admin.cancel_payment")
@patch("app.routers.merchant_admin.JoinRepository")
def test_provider_in_flight_crash_retry_requires_reconciliation_without_provider_call(repo_class, cancel):
    repo = repo_class.return_value
    _configure_card_refund_repo(repo, order_id="GE-V-crashed")
    repo.client.rpc.return_value = {
        "refund_request_id": "refund-crashed", "refund_amount": 8000,
        "provider_succeeded": False, "acquired": False,
        "error_code": "REFUND_PROVIDER_ATTEMPT_IN_FLIGHT",
    }

    with pytest.raises(HTTPException) as raised:
        refund_purchase_order(
            MerchantRefundRequest(account_id="account-123", order_id="GE-V-crashed"), "token"
        )

    assert raised.value.status_code == 409
    assert isinstance(raised.value.detail, dict)
    assert raised.value.detail["code"] == "REFUND_PROVIDER_ATTEMPT_IN_FLIGHT"
    cancel.assert_not_called()
    assert [call.args[0] for call in repo.client.rpc.call_args_list] == ["claim_purchase_order_refund"]


@patch("app.routers.merchant_admin.cancel_payment")
@patch("app.routers.merchant_admin.get_settings")
@patch("app.routers.merchant_admin.JoinRepository")
def test_uncertain_marker_failure_leaves_provider_in_flight_non_reclaimable(repo_class, settings, cancel):
    repo = repo_class.return_value
    _configure_card_refund_repo(repo, order_id="GE-V-marker-fail")
    durable = {"status": "processing"}

    def rpc(name, params):
        if name == "claim_purchase_order_refund":
            return {"refund_request_id": "refund-marker-fail", "refund_amount": 8000,
                    "provider_payment_key": "safety-trx", "acquired": True,
                    "processing_token": "lease-token"}
        if name == "mark_purchase_order_refund_provider_attempt_started":
            durable["status"] = "provider_in_flight"
            return {"status": durable["status"]}
        if name == "mark_purchase_order_refund_reconciliation_required":
            raise SupabaseHttpError(500, "reconciliation marker unavailable")
        raise AssertionError(f"unexpected RPC {name}")

    repo.client.rpc.side_effect = rpc
    settings.return_value.kiwoompay_base_url = "https://apitest.kiwoompay.co.kr"
    settings.return_value.kiwoompay_authorization_key = "auth"
    settings.return_value.kiwoompay_cpid = "CPID"
    cancel.side_effect = KiwoomCancellationOutcomeUnknown(
        502, "KIWOOMPAY_CANCEL_OUTCOME_UNKNOWN", "manual reconciliation"
    )

    with pytest.raises(HTTPException):
        refund_purchase_order(
            MerchantRefundRequest(account_id="account-123", order_id="GE-V-marker-fail"), "token"
        )

    assert durable["status"] == "provider_in_flight"
    assert [call.args[0] for call in repo.client.rpc.call_args_list] == [
        "claim_purchase_order_refund", "mark_purchase_order_refund_provider_attempt_started",
        "mark_purchase_order_refund_reconciliation_required",
    ]


@patch("app.routers.merchant_admin.cancel_payment")
@patch("app.routers.merchant_admin.get_settings")
@patch("app.routers.merchant_admin.JoinRepository")
def test_explicit_provider_failure_releases_refund_and_restores_order(repo_class, settings, cancel):
    repo = repo_class.return_value
    _configure_card_refund_repo(repo, order_id="GE-V-rejected")
    repo.client.rpc.side_effect = [
        {"refund_request_id": "refund-rejected", "refund_amount": 8000,
         "provider_payment_key": "safety-trx", "acquired": True, "processing_token": "lease-token"},
        {"status": "provider_in_flight"},
        {"status": "failed"},
    ]
    settings.return_value.kiwoompay_base_url = "https://apitest.kiwoompay.co.kr"
    settings.return_value.kiwoompay_authorization_key = "auth"
    settings.return_value.kiwoompay_cpid = "CPID"
    cancel.side_effect = KiwoomPaymentError(400, "DECLINED", "provider rejected cancellation")

    with pytest.raises(HTTPException) as raised:
        refund_purchase_order(
            MerchantRefundRequest(account_id="account-123", order_id="GE-V-rejected"), "token"
        )

    assert raised.value.status_code == 400
    assert [call.args[0] for call in repo.client.rpc.call_args_list] == [
        "claim_purchase_order_refund", "mark_purchase_order_refund_provider_attempt_started",
        "fail_purchase_order_refund",
    ]
    failure = repo.client.rpc.call_args_list[2].args[1]
    assert failure["p_processing_token"] == "lease-token"
    assert failure["p_failure_code"] == "DECLINED"


@patch("app.routers.merchant_admin.cancel_payment")
@patch("app.routers.merchant_admin.JoinRepository")
def test_reconciliation_required_retry_returns_409_without_provider_call(repo_class, cancel):
    repo = repo_class.return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id="admin-123", email="a@example.com")
    repo.get_profile.return_value = SimpleNamespace(
        id="admin-123", role="merchant_admin", status="active", merchant_id="merchant-1"
    )
    repo.client.rest_get.return_value = [{
        "id": "internal-order", "order_id": "GE-V-reconcile", "user_id": "account-123",
        "merchant_id": "merchant-1", "pay_type": "voucher", "status": "refund_processing",
        "amount": 8000, "provider_payment_key": "reconcile-trx", "payment_method": "CARD",
    }]
    repo.client.rpc.return_value = {
        "refund_request_id": "refund-reconcile", "refund_amount": 8000,
        "provider_succeeded": False, "acquired": False,
        "error_code": "REFUND_RECONCILIATION_REQUIRED",
    }

    with pytest.raises(HTTPException) as raised:
        refund_purchase_order(MerchantRefundRequest(account_id="account-123", order_id="GE-V-reconcile"), "token")

    assert raised.value.status_code == 409
    assert isinstance(raised.value.detail, dict)
    assert raised.value.detail["code"] == "REFUND_RECONCILIATION_REQUIRED"
    cancel.assert_not_called()
    assert [call.args[0] for call in repo.client.rpc.call_args_list] == ["claim_purchase_order_refund"]


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
