from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SQL = (ROOT / "infra/migrations/0058_direct_payment_refunds.sql").read_text()
ROUTER = (ROOT / "services/api/app/routers/merchant_admin.py").read_text()


def test_direct_refund_migration_reuses_locked_refund_pipeline():
    assert "o.pay_type not in ('direct','voucher','subsidized')" in SQL
    assert "if o.pay_type='direct' then" in SQL
    assert "card_refund:=greatest(o.amount-already_refunded,0)" in SQL
    assert "paid_remaining:=0; unused_bonus:=0; point_refund:=0" in SQL
    assert "perform 1 from vouchers where order_id=o.id order by issue_index,id for update" in SQL
    assert "snapshot_paid_total<>o.amount" in SQL
    assert "status='refund_processing'" in SQL
    assert "processing_token" in SQL and "lease_expires_at" in SQL


def test_direct_orders_are_discoverable_in_both_refund_queries():
    assert ROUTER.count('"pay_type": "in.(direct,voucher,subsidized)"') == 2
