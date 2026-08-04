from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.routers.merchant_admin import (
    charge_prepurchase,
    list_prepurchase_charges,
    list_prepurchase_inventory,
    update_company_contract,
)
from app.routers.pay import _map_rpc_error
from app.repositories.supabase_http import SupabaseHttpError
from app.schemas import (
    MerchantCompanyContractUpdateRequest,
    MerchantCompanyPrepurchaseChargeRequest,
)


SQL = (
    Path(__file__).parents[3]
    / "infra"
    / "migrations"
    / "0062_merchant_company_prepurchase.sql"
).read_text().lower()


def test_contract_flag_is_optional_for_old_clients_and_persisted_when_sent():
    old = MerchantCompanyContractUpdateRequest(settlement_cycle="month_end", unit_price=9000)
    assert old.prepurchase_enabled is None
    assert "prepurchase_enabled" not in old.model_dump(exclude_unset=True)

    with patch("app.routers.merchant_admin.JoinRepository") as repo_class, patch(
        "app.routers.merchant_admin._merchant_admin", return_value=(object(), "merchant-1")
    ), patch("app.routers.merchant_admin._require_company_link") as require:
        require.return_value = {"id": "link-1", "status": "active"}
        repo_class.return_value.client.rest_patch.return_value = [{
            "id": "link-1", "settlement_cycle": "month_end", "settlement_day": None,
            "unit_price": 9000, "prepurchase_enabled": True,
        }]
        result = update_company_contract(
            "company-1",
            MerchantCompanyContractUpdateRequest(
                settlement_cycle="month_end", unit_price=9000, prepurchase_enabled=True
            ),
            "token",
        )
        values = repo_class.return_value.client.rest_patch.call_args.args[2]
        assert values["prepurchase_enabled"] is True
        assert result["data"]["contract"]["prepurchase_enabled"] is True


@pytest.mark.parametrize(
    "values",
    [
        {"quantity": 0, "unit_price": 9000, "idempotency_key": "x"},
        {"quantity": 1, "unit_price": 0, "idempotency_key": "x"},
        {"quantity": 1, "unit_price": 9000, "idempotency_key": ""},
        {"quantity": 1_000_001, "unit_price": 9000, "idempotency_key": "x"},
    ],
)
def test_charge_schema_rejects_invalid_input(values):
    with pytest.raises(ValidationError):
        MerchantCompanyPrepurchaseChargeRequest(**values)


@patch("app.routers.merchant_admin._require_company_link")
@patch(
    "app.routers.merchant_admin._merchant_admin",
    return_value=(SimpleNamespace(id="actor-1"), "merchant-1"),
)
@patch("app.routers.merchant_admin.JoinRepository")
def test_charge_is_tenant_scoped_and_amount_is_not_client_input(repo_class, _admin, require):
    repo = repo_class.return_value
    repo.client.rpc.return_value = {"id": "batch-1", "amount": 27000, "duplicate": False}

    result = charge_prepurchase(
        "company-1",
        MerchantCompanyPrepurchaseChargeRequest(quantity=3, unit_price=9000, idempotency_key="charge-1"),
        "token",
    )

    require.assert_not_called()
    assert repo.client.rpc.call_args.args == (
        "charge_merchant_company_prepurchase",
        {
            "p_merchant_id": "merchant-1", "p_company_id": "company-1",
            "p_actor_id": "actor-1", "p_quantity": 3, "p_unit_price": 9000,
            "p_idempotency_key": "charge-1",
        },
    )
    assert "p_amount" not in repo.client.rpc.call_args.args[1]
    assert result["data"]["amount"] == 27000


@patch("app.routers.merchant_admin._merchant_admin", return_value=(object(), "merchant-1"))
@patch("app.routers.merchant_admin.JoinRepository")
def test_inventory_list_is_scoped_to_authenticated_merchant(repo_class, _admin):
    repo = repo_class.return_value
    repo.client.rpc.return_value = {"items": [{"company_name": "회사", "total_remaining": 4}]}
    result = list_prepurchase_inventory("token")
    repo.client.rpc.assert_called_once_with(
        "list_merchant_company_prepurchase_inventory", {"p_merchant_id": "merchant-1"}
    )
    assert result["data"]["items"][0]["total_remaining"] == 4


@patch("app.routers.merchant_admin._require_company_link")
@patch("app.routers.merchant_admin._merchant_admin", return_value=(object(), "merchant-1"))
@patch("app.routers.merchant_admin.JoinRepository")
def test_charge_history_requires_active_tenant_link(repo_class, _admin, require):
    repo = repo_class.return_value
    require.return_value = {"id": "link-1", "status": "active"}
    repo.client.rpc.return_value = {"items": [], "total": 0, "total_remaining": 0}
    list_prepurchase_charges("company-1", 25, 5, "token")
    require.assert_called_once_with(repo, "merchant-1", "company-1")
    assert repo.client.rpc.call_args.args[1]["p_merchant_id"] == "merchant-1"
    assert repo.client.rpc.call_args.args[1]["p_company_id"] == "company-1"


def test_empty_inventory_has_explicit_pay_error_mapping():
    exc = SupabaseHttpError(400, '{"message":"PREPURCHASE_INVENTORY_EMPTY"}')
    mapped = _map_rpc_error(exc)
    assert mapped.status_code == 409
    assert mapped.detail["code"] == "PREPURCHASE_INVENTORY_EMPTY"


def test_migration_has_auditable_batches_server_amount_and_idempotent_charge():
    assert "create table if not exists public.merchant_company_prepurchase_batches" in SQL
    assert "purchase_quantity integer not null" in SQL
    assert "remaining_quantity integer not null" in SQL
    assert "total_amount = purchase_quantity::bigint * unit_price::bigint" in SQL
    assert "actor_id uuid not null" in SQL
    assert "unique (merchant_id, idempotency_key)" in SQL
    charge = SQL.split("create or replace function public.charge_merchant_company_prepurchase", 1)[1].split("end $$", 1)[0]
    assert "p_quantity::bigint*p_unit_price::bigint" in charge
    assert "on conflict(merchant_id,idempotency_key) do nothing" in charge
    assert "raise exception 'idempotency_conflict'" in charge


def test_process_pay_blocks_empty_and_consumes_one_fifo_ticket_after_duplicate_check():
    process = SQL.split("create or replace function public.process_meal_pay", 1)[1].split("end $$", 1)[0]
    duplicate_pos = process.index("select * into existing")
    fifo_pos = process.index("order by purchased_at,id limit 1 for update")
    decrement_pos = process.index("remaining_quantity=remaining_quantity-1")
    assert duplicate_pos < fifo_pos < decrement_pos
    assert process.count("remaining_quantity=remaining_quantity-1") == 1
    assert "raise exception 'prepurchase_inventory_empty'" in process
    assert "insert into merchant_company_prepurchase_consumptions" in process
    assert "if contract.prepurchase_enabled then" in process
    # The ordinary ledger insert remains outside the prepaid branch.
    assert process.index("if contract.prepurchase_enabled then") < process.index("insert into meal_transactions")


def test_migration_preserves_nonprepaid_tax_snapshots_signature_and_service_only_access():
    assert "process_meal_pay(p_user_id uuid,p_company_id uuid,p_merchant_id uuid,p_amount int,p_tx_code text" in SQL
    assert "split_tax_inclusive(p_amount,contract.tax_type)" in SQL
    assert "settlement_supply_amount" in SQL and "settlement_vat_amount" in SQL
    assert "if contract.prepurchase_enabled then" in SQL
    assert "alter table public.merchant_company_prepurchase_batches enable row level security" in SQL
    assert "revoke all on table public.merchant_company_prepurchase_batches from public, anon, authenticated, service_role" in SQL
    assert "grant select on table public.merchant_company_prepurchase_batches to service_role" in SQL
    assert "where mc.merchant_id=p_merchant_id" in SQL
    assert "mc.status='active' and mc.prepurchase_enabled" in SQL
    assert "where b.merchant_id=p_merchant_id and b.company_id=p_company_id" in SQL


def test_prepaid_settlement_snapshots_flags_and_ordinary_full_amount_are_explicit():
    process = SQL.split("create or replace function public.process_meal_pay", 1)[1].split("end $$", 1)[0]
    assert "jsonb_build_object('prepurchase',true,'prepurchase_batch_id',consumed_batch_id)" in process
    assert "settlement_supply:=0; settlement_vat:=0; settlement_total:=0" in process
    assert "contract.tax_type,settlement_supply,settlement_vat,settlement_total" in process
    assert "settlement_supply:=s.supply_amount" in process
    summary = SQL.split("create or replace function public.merchant_ledger_summary", 1)[1]
    assert "coalesce(settlement_total_amount,abs(amount))" in summary
    assert "'total_count',count(*)" in summary


def test_refund_cancel_restoration_is_auditable_locked_exactly_once_and_restricted():
    assert "create table if not exists public.merchant_company_prepurchase_reversals" in SQL
    assert "consumption_id uuid not null unique" in SQL
    assert "reversal_meal_transaction_id bigint not null unique" in SQL
    assert "where id=consumption.batch_id for update" in SQL
    assert "on conflict(consumption_id) do nothing" in SQL
    assert "remaining_quantity<purchase_quantity" in SQL
    assert "new.kind not in ('refund','cancel')" in SQL
    assert "after insert on public.meal_transactions" in SQL
    assert "enable row level security" in SQL
    assert "revoke all on table public.merchant_company_prepurchase_reversals from public,anon,authenticated,service_role" in SQL


def test_charge_retry_precedes_current_contract_checks_and_price_snapshot_is_intentional():
    charge = SQL.split("create or replace function public.charge_merchant_company_prepurchase", 1)[1].split("end $$", 1)[0]
    retry = charge.index("select * into batch from public.merchant_company_prepurchase_batches")
    contract = charge.index("select * into contract from public.merchant_companies")
    assert retry < contract
    assert "batch.unit_price<>p_unit_price" in charge
    assert "return jsonb_build_object" in charge[retry:contract]
    assert "immutable price snapshot for this purchased ticket entitlement" in SQL
    assert "may differ from the current merchant-company contract unit_price" in SQL


@pytest.mark.parametrize("endpoint", ["inventory", "charge"])
def test_missing_prepurchase_rpcs_map_to_migration_0062(endpoint):
    missing = SupabaseHttpError(
        404,
        '{"code":"PGRST202","message":"Could not find the function public.'
        + ("list_merchant_company_prepurchase_inventory" if endpoint == "inventory" else "charge_merchant_company_prepurchase")
        + '"}',
    )
    with patch("app.routers.merchant_admin.JoinRepository") as repo_class, patch(
        "app.routers.merchant_admin._merchant_admin",
        return_value=(SimpleNamespace(id="actor-1"), "merchant-1"),
    ):
        repo_class.return_value.client.rpc.side_effect = missing
        with pytest.raises(HTTPException) as raised:
            if endpoint == "inventory":
                list_prepurchase_inventory("token")
            else:
                charge_prepurchase(
                    "company-1",
                    MerchantCompanyPrepurchaseChargeRequest(quantity=1, unit_price=8700, idempotency_key="retry"),
                    "token",
                )
    error = raised.value
    assert error.status_code == 400
    assert isinstance(error.detail, dict)
    assert error.detail["code"] == "MIGRATION_REQUIRED"
    assert "0062_merchant_company_prepurchase.sql" in error.detail["message"]


def test_missing_prepurchase_column_and_pay_rpc_name_migration_0062():
    missing_column = SupabaseHttpError(400, '{"code":"42703","message":"column prepurchase_enabled does not exist"}')
    with patch("app.routers.merchant_admin.JoinRepository") as repo_class, patch(
        "app.routers.merchant_admin._merchant_admin", return_value=(object(), "merchant-1")
    ), patch("app.routers.merchant_admin._require_company_link", side_effect=missing_column):
        with pytest.raises(HTTPException) as raised:
            update_company_contract(
                "company-1",
                MerchantCompanyContractUpdateRequest(settlement_cycle="month_end", unit_price=9000, prepurchase_enabled=True),
                "token",
            )
    assert isinstance(raised.value.detail, dict)
    assert raised.value.detail["code"] == "MIGRATION_REQUIRED"
    assert "0062_merchant_company_prepurchase.sql" in raised.value.detail["message"]

    mapped = _map_rpc_error(SupabaseHttpError(404, '{"code":"PGRST202","message":"process_meal_pay"}'))
    assert mapped.status_code == 400
    assert isinstance(mapped.detail, dict)
    assert mapped.detail["code"] == "MIGRATION_REQUIRED"
    assert "0062_merchant_company_prepurchase.sql" in mapped.detail["message"]
