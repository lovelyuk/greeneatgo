from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.merchant_admin import confirm_vendor_settlement_payment
from app.schemas import SettlementPaymentConfirmRequest
from app.services.join_flow import UserProfile


def test_legacy_confirm_payment_route_uses_atomic_rpc_not_rest_patch():
    actor = UserProfile(id="actor-1", email="merchant@example.com", display_name="merchant",
                        role="merchant_admin", status="active", merchant_id="merchant-1")
    repo = MagicMock()
    repo.get_profile.return_value = actor
    repo.client.rest_get.return_value = [{
        "id": "link-1", "merchant_id": "merchant-1", "company_id": "company-1", "status": "active",
    }]
    repo.client.rpc.return_value = {
        "settlement": {"id": "settlement-1", "payment_status": "paid"},
        "payment": {"amount": 1100}, "idempotent": False,
    }

    with patch("app.routers.merchant_admin.JoinRepository", return_value=repo):
        result = confirm_vendor_settlement_payment(
            "company-1", "settlement-1", SettlementPaymentConfirmRequest(paid_at="2026-07-01"), "token"
        )

    assert result["data"]["payment"]["amount"] == 1100
    repo.client.rpc.assert_called_once_with("merchant_confirm_settlement_payment_legacy", {
        "p_actor_id": "actor-1", "p_merchant_id": "merchant-1",
        "p_company_id": "company-1", "p_settlement_id": "settlement-1",
    })
    repo.client.rest_patch.assert_not_called()
    assert any(call.args[0] == "normal_settlements" for call in repo.client.rest_get.call_args_list)


def test_legacy_confirm_payment_rejects_demo_or_hidden_settlement_before_rpc():
    actor = UserProfile(id="actor-1", email="merchant@example.com", display_name="merchant",
                        role="merchant_admin", status="active", merchant_id="merchant-1")
    repo = MagicMock()
    repo.get_profile.return_value = actor
    repo.client.rest_get.side_effect = [
        [{"id": "link-1", "merchant_id": "merchant-1", "company_id": "company-1", "status": "active"}],
        [],
    ]

    with patch("app.routers.merchant_admin.JoinRepository", return_value=repo):
        with pytest.raises(HTTPException) as raised:
            confirm_vendor_settlement_payment(
                "company-1", "demo-settlement", SettlementPaymentConfirmRequest(paid_at="2026-07-01"), "token"
            )

    assert raised.value.status_code == 404
    assert isinstance(raised.value.detail, dict)
    assert raised.value.detail["code"] == "SETTLEMENT_NOT_FOUND"
    repo.client.rpc.assert_not_called()
