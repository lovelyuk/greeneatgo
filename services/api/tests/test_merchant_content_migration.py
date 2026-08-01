from pathlib import Path


MIGRATION = Path(__file__).parents[3] / "infra" / "migrations" / "0055_merchant_content_management.sql"


def test_merchant_content_migration_contract():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "discount_amount_per_voucher" in sql
    assert "status in ('active', 'sold_out')" in sql
    assert "deleted_at timestamptz" in sql
    assert "generated always as" in sql
    assert "voucher_products_sale_price_positive_check check (sale_price > 0)" in sql
    assert "discount_rate = 0 or discount_amount_per_voucher = 0" in sql
    assert "create table if not exists public.merchant_coupons" in sql
    assert "discount_type in ('percent', 'fixed')" in sql
    assert sql.index("drop constraint if exists voucher_products_status_check") < sql.index("set status = 'sold_out'")
    assert "enable row level security" in sql
    assert "grant select, insert, update, delete" in sql
