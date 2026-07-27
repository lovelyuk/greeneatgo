from pathlib import Path
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.routers.voucher_products import _require_classified_product
from app.schemas import MerchantCompanyContractUpdateRequest, VoucherProductCreateRequest, VoucherProductUpdateRequest


MIGRATIONS = Path(__file__).parents[3] / "infra" / "migrations"
SQL_0032 = (MIGRATIONS / "0032_product_subsidized_vouchers.sql").read_text().lower()
SQL = (MIGRATIONS / "0036_runtime_tax_snapshots.sql").read_text().lower()


def _voucher_constraint(sql: str) -> str:
    return sql.split("add constraint payment_orders_voucher_columns_check check (", 1)[1].split(
        "alter table vouchers", 1
    )[0]


def test_immutable_0032_keeps_original_constraint_and_0036_owns_its_evolution():
    original = _voucher_constraint(SQL_0032)
    evolved = _voucher_constraint(SQL)

    # 0032 remains the committed historical source: ordinary pricing used the
    # total voucher count, and the paid/bonus correction must not be backported.
    assert "voucher_purchase_price = round(amount::numeric / voucher_count, 4)" in original
    original_voucher_branch = original.split("pay_type = 'voucher'", 1)[1].split(
        "pay_type = 'subsidized'", 1
    )[0]
    assert "paid_voucher_count" not in original_voucher_branch
    assert "bonus_voucher_count" not in original_voucher_branch

    # 0036 rerun-safely replaces the constraint and changes only the ordinary
    # rule while retaining direct, historical subsidized, and package branches.
    assert "drop constraint if exists payment_orders_voucher_columns_check" in SQL
    assert "voucher_purchase_price = round(amount::numeric / paid_voucher_count, 4)" in evolved
    assert "paid_voucher_count + bonus_voucher_count = voucher_count" in evolved
    assert "pay_type = 'direct'" in evolved
    assert "voucher_product_id is null" in evolved
    assert "voucher_count = 1 and paid_voucher_count = 1 and bonus_voucher_count = 0" in evolved
    assert "voucher_product_id is not null" in evolved
    assert "voucher_purchase_price = round(total_employee_burden::numeric / paid_voucher_count, 4)" in evolved


def test_tax_split_uses_postgres_numeric_round_and_conserves_total():
    assert "round(p_total::numeric/1.1)::int" in SQL
    assert "vat_amount:=p_total-supply_amount" in SQL
    assert "supply_amount:=p_total; vat_amount:=0" in SQL
    # PostgreSQL numeric ROUND(9000 / 1.1) = 8182; VAT is the conserved remainder 818.
    assert "create or replace function split_tax_inclusive" in SQL


def test_all_money_flows_snapshot_and_block_unclassified():
    for function in ("process_meal_pay", "consume_voucher", "consume_subsidized_voucher"):
        section = SQL.split(f"create or replace function {function}", 1)[1]
        assert "tax_type_unclassified" in section
        assert "supply_amount" in section
        assert "vat_amount" in section
        assert "total_amount" in section
    assert "settlement_split from split_tax_inclusive(v.company_subsidy_amount,v.tax_type)" in SQL
    assert "'unclassified') returning * into tx" in SQL  # ordinary voucher has no company target


def test_product_authority_is_tenant_scoped_and_client_tax_is_overridden():
    trigger = SQL.split("create or replace function snapshot_payment_order_tax", 1)[1].split("end $$", 1)[0]
    assert "voucher_products" in trigger and "id=new.voucher_product_id and merchant_id=new.merchant_id" in trigger
    assert "merchant_products" in trigger and "id=new.product_id and merchant_id=new.merchant_id" in trigger
    assert "new.tax_type:=authoritative" in trigger


def test_voucher_snapshot_and_idempotent_returns_include_tax_facts():
    assert "add column if not exists tax_type text not null default 'unclassified'" in SQL
    assert "o.tax_type" in SQL
    assert SQL.count("'duplicate',true") >= 3
    assert "immutable_tax_snapshot" in SQL


def test_fastapi_blocks_unclassified_before_order_creation():
    with pytest.raises(HTTPException) as exc:
        _require_classified_product({"id": "product-1", "tax_type": "unclassified"})
    assert exc.value.status_code == 409
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail["code"] == "TAX_TYPE_UNCLASSIFIED"
    _require_classified_product({"id": "product-1", "tax_type": "taxable"})
    _require_classified_product({"id": "product-1", "tax_type": "tax_free"})


def test_tax_management_schema_contracts():
    create = VoucherProductCreateRequest(name="식권", voucher_count=1, unit_price=Decimal("9000"), tax_type="taxable")
    update = VoucherProductUpdateRequest(tax_type="tax_free")
    contract = MerchantCompanyContractUpdateRequest(settlement_cycle="month_end", unit_price=9000, tax_type="taxable")
    assert create.tax_type == "taxable"
    assert update.tax_type == "tax_free"
    assert contract.tax_type == "taxable"
