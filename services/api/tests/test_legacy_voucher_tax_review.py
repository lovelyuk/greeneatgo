from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.repositories.supabase_http import SupabaseHttpError
from app.routers.merchant_admin import classify_active_legacy_voucher, list_active_legacy_vouchers
from app.schemas import LegacyVoucherClassifyRequest


VOUCHER_ID = UUID("11111111-1111-4111-8111-111111111111")


def _authorized(repo):
    repo.auth_user_from_token.return_value = SimpleNamespace(id="actor-1", email="admin@example.com")
    repo.get_profile.return_value = SimpleNamespace(
        id="actor-1", email="admin@example.com", role="merchant_admin", status="active", merchant_id="merchant-1"
    )


def test_legacy_voucher_list_is_authenticated_tenant_scoped_bounded_rpc_and_pii_free():
    with patch("app.routers.merchant_admin.JoinRepository") as repo_class:
        repo = repo_class.return_value
        _authorized(repo)
        repo.client.rpc.return_value = {"items": [{
            "id": str(VOUCHER_ID), "purchase_price_won": 1100,
            "status": "unused", "tax_type": "unclassified",
        }], "limit": 25, "offset": 50}
        result = list_active_legacy_vouchers(limit=25, offset=50, token="token")

    repo.client.rpc.assert_called_once_with("list_active_legacy_vouchers", {
        "p_merchant_id": "merchant-1", "p_limit": 25, "p_offset": 50,
    })
    item = result["data"]["items"][0]
    assert "user_id" not in item and "phone" not in item and "email" not in item
    repo.client.rest_get.assert_not_called()


def test_legacy_voucher_endpoints_reject_non_merchant_admin_before_rpc():
    with patch("app.routers.merchant_admin.JoinRepository") as repo_class:
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="customer-1", email=None)
        repo.get_profile.return_value = SimpleNamespace(
            id="customer-1", role="customer", status="active", merchant_id=None
        )
        with pytest.raises(HTTPException) as caught:
            list_active_legacy_vouchers(limit=50, offset=0, token="token")
    assert caught.value.status_code == 403
    repo.client.rpc.assert_not_called()


def test_legacy_voucher_classification_passes_authoritative_tenant_and_actor_and_keeps_duplicate():
    payload = LegacyVoucherClassifyRequest(tax_type="taxable", reason="  catalog reviewed  ")
    with patch("app.routers.merchant_admin.JoinRepository") as repo_class:
        repo = repo_class.return_value
        _authorized(repo)
        repo.client.rpc.return_value = {"id": str(VOUCHER_ID), "tax_type": "taxable", "duplicate": True}
        result = classify_active_legacy_voucher(VOUCHER_ID, payload, "token")

    assert result["data"]["duplicate"] is True
    repo.client.rpc.assert_called_once_with("classify_legacy_voucher", {
        "p_voucher_id": str(VOUCHER_ID), "p_merchant_id": "merchant-1",
        "p_actor_id": "actor-1", "p_tax_type": "taxable", "p_reason": "catalog reviewed",
    })
    repo.client.rest_get.assert_not_called()
    repo.client.rest_patch.assert_not_called()


@pytest.mark.parametrize(
    "values",
    [
        {"tax_type": "unclassified", "reason": "valid reason"},
        {"tax_type": "taxable", "reason": "  x  "},
        {"tax_type": "tax_free", "reason": "   "},
        {"tax_type": "taxable", "reason": "valid", "unexpected": True},
    ],
)
def test_legacy_voucher_classification_rejects_invalid_type_reason_and_extra_fields(values):
    with pytest.raises(ValidationError):
        LegacyVoucherClassifyRequest.model_validate(values)


def test_legacy_voucher_conflicting_type_has_stable_409_without_database_leak():
    payload = LegacyVoucherClassifyRequest(tax_type="tax_free", reason="conflicting classification")
    raw = "VOUCHER_NOT_CLASSIFIABLE relation public.vouchers secret"
    with patch("app.routers.merchant_admin.JoinRepository") as repo_class:
        repo = repo_class.return_value
        _authorized(repo)
        repo.client.rpc.side_effect = SupabaseHttpError(400, raw)
        with pytest.raises(HTTPException) as caught:
            classify_active_legacy_voucher(VOUCHER_ID, payload, "token")
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "VOUCHER_NOT_CLASSIFIABLE"
    assert raw not in str(caught.value.detail)
