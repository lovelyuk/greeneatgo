from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routers.merchant_admin import list_companies, update_company_contract
from app.schemas import MerchantCompanyContractUpdateRequest


@patch("app.routers.merchant_admin._company_rows", return_value=[])
@patch("app.routers.merchant_admin._merchant_admin", return_value=(object(), "merchant-1"))
@patch("app.routers.merchant_admin.JoinRepository")
def test_list_companies_returns_persisted_subsidy_contract(repo_class, _admin, _companies):
    repo = repo_class.return_value
    repo.client.rest_get.side_effect = [
        [{
            "id": "link-1",
            "merchant_id": "merchant-1",
            "company_id": "company-1",
            "status": "active",
            "settlement_cycle": "month_end",
            "settlement_day": None,
            "unit_price": 8000,
            "subsidy_enabled": True,
            "company_subsidy_amount": 2000,
            "restaurant_subsidy_amount": 1000,
            "created_at": "2026-07-01T00:00:00Z",
        }],
        [],
    ]

    result = list_companies("token")

    select = repo.client.rest_get.call_args_list[0].args[1]["select"]
    assert "subsidy_enabled" in select
    assert "company_subsidy_amount" in select
    assert "restaurant_subsidy_amount" in select
    assert result["data"]["items"][0]["contract"] == {
        "settlement_cycle": "month_end",
        "settlement_day": None,
        "unit_price": 8000,
        "subsidy_enabled": True,
        "company_subsidy_amount": 2000,
        "restaurant_subsidy_amount": 1000,
        "cycle_label": "월말",
    }


@patch("app.routers.merchant_admin._require_company_link")
@patch("app.routers.merchant_admin._merchant_admin", return_value=(object(), "merchant-1"))
@patch("app.routers.merchant_admin.JoinRepository")
def test_update_company_contract_persists_and_returns_subsidy_values(repo_class, _admin, require_link):
    repo = repo_class.return_value
    require_link.return_value = {"id": "link-1", "status": "active"}
    repo.client.rest_patch.return_value = [{
        "id": "link-1",
        "settlement_cycle": "month_end",
        "settlement_day": None,
        "unit_price": 8000,
        "subsidy_enabled": True,
        "company_subsidy_amount": 2000,
        "restaurant_subsidy_amount": 1000,
    }]
    payload = MerchantCompanyContractUpdateRequest(
        settlement_cycle="month_end",
        unit_price=8000,
        subsidy_enabled=True,
        company_subsidy_amount=2000,
        restaurant_subsidy_amount=1000,
    )

    result = update_company_contract("company-1", payload, "token")

    values = repo.client.rest_patch.call_args.args[2]
    assert values == {
        "settlement_cycle": "month_end",
        "settlement_day": None,
        "unit_price": 8000,
        "subsidy_enabled": True,
        "company_subsidy_amount": 2000,
        "restaurant_subsidy_amount": 1000,
    }
    assert result["data"]["contract"]["subsidy_enabled"] is True
    assert result["data"]["contract"]["company_subsidy_amount"] == 2000
    assert result["data"]["contract"]["restaurant_subsidy_amount"] == 1000


@patch("app.routers.merchant_admin._require_company_link")
@patch("app.routers.merchant_admin._merchant_admin", return_value=(object(), "merchant-1"))
@patch("app.routers.merchant_admin.JoinRepository")
def test_legacy_contract_update_does_not_clear_subsidy(repo_class, _admin, require_link):
    repo = repo_class.return_value
    require_link.return_value = {"id": "link-1", "status": "active"}
    repo.client.rest_patch.return_value = [{
        "id": "link-1",
        "settlement_cycle": "month_end",
        "settlement_day": None,
        "unit_price": 9000,
        "subsidy_enabled": True,
        "company_subsidy_amount": 2000,
        "restaurant_subsidy_amount": 1000,
    }]

    update_company_contract(
        "company-1",
        MerchantCompanyContractUpdateRequest(settlement_cycle="month_end", unit_price=9000),
        "token",
    )

    values = repo.client.rest_patch.call_args.args[2]
    assert "subsidy_enabled" not in values
    assert "company_subsidy_amount" not in values
    assert "restaurant_subsidy_amount" not in values


def test_subsidy_total_must_leave_a_positive_employee_price():
    with pytest.raises(ValidationError):
        MerchantCompanyContractUpdateRequest(
            settlement_cycle="month_end",
            unit_price=8000,
            subsidy_enabled=True,
            company_subsidy_amount=7000,
            restaurant_subsidy_amount=1000,
        )


@patch("app.routers.merchant_admin._require_company_link")
@patch("app.routers.merchant_admin._merchant_admin", return_value=(object(), "merchant-1"))
@patch("app.routers.merchant_admin.JoinRepository")
def test_legacy_unit_price_update_cannot_invalidate_existing_subsidy(repo_class, _admin, require_link):
    repo = repo_class.return_value
    require_link.return_value = {
        "id": "link-1",
        "status": "active",
        "unit_price": 8000,
        "subsidy_enabled": True,
        "company_subsidy_amount": 2000,
        "restaurant_subsidy_amount": 1000,
    }

    with pytest.raises(HTTPException) as exc:
        update_company_contract(
            "company-1",
            MerchantCompanyContractUpdateRequest(settlement_cycle="month_end", unit_price=3000),
            "token",
        )

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "INVALID_SUBSIDY_CONTRACT"
    repo.client.rest_patch.assert_not_called()
