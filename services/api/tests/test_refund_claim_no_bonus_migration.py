import os
from pathlib import Path

import pytest

from tests.test_legacy_bonus_voucher_migration import _reset_and_apply_through_0035

ROOT = Path(__file__).resolve().parents[3]
INFRA = ROOT / "infra" / "migrations"
FIX = ROOT / "supabase" / "migrations" / "0071_refund_claim_no_bonus_orders.sql"
LAST_INFRA = "0058_direct_payment_refunds.sql"


def test_fix_only_changes_the_bonus_total_fallback():
    old = (INFRA / LAST_INFRA).read_text(encoding="utf-8")
    new = FIX.read_text(encoding="utf-8")

    def body(sql):
        start = sql.index("create or replace function public.claim_purchase_order_refund(")
        return sql[start:sql.index("end $$;", start)]

    changed = [line for line in body(new).splitlines() if line not in body(old).splitlines()]
    assert all(
        line.strip().startswith("--") or "bonus_voucher_count=0 then 0 else -1" in line
        or line.strip() == "coalesce(sum(purchase_price_won) filter(where issue_index>o.paid_voucher_count),"
        for line in changed
    ), changed
    assert "grant execute on function public.claim_purchase_order_refund(uuid,uuid,uuid,uuid,jsonb) to service_role" in new
    assert "from public,anon,authenticated" in new


@pytest.fixture
def refund_db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL for PostgreSQL 16 refund-claim migration tests")
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(url, autocommit=True) as conn:
        _reset_and_apply_through_0035(conn)
        for migration in sorted(INFRA.glob("*.sql")):
            if "0036_runtime_tax_snapshots.sql" <= migration.name <= LAST_INFRA:
                conn.execute(migration.read_text(encoding="utf-8"))
    return url


def _seed(conn, *, paid, bonus, unit=100):
    user_id = conn.execute(
        "insert into app_users(id,display_name,role,status) values (gen_random_uuid(),'buyer','customer','active') returning id"
    ).fetchone()[0]
    suffix = conn.execute("select replace(gen_random_uuid()::text,'-','')").fetchone()[0][:12]
    merchant_id = conn.execute(
        "insert into merchants(name,qr_token,view_token) values ('m',%s,%s) returning id",
        (f"qr-{suffix}", f"view-{suffix}"),
    ).fetchone()[0]
    product_id = conn.execute(
        """insert into voucher_products(merchant_id,name,voucher_count,bonus_count,unit_price,tax_type)
           values (%s,'p',%s,%s,%s,'taxable') returning id""",
        (merchant_id, paid, bonus, unit),
    ).fetchone()[0]
    order_id = conn.execute(
        """insert into payment_orders(
             order_id,checkout_token,user_id,merchant_id,merchant_name,product_name,amount,status,pay_type,
             voucher_product_id,voucher_count,voucher_purchase_price,fulfilled_at,paid_voucher_count,
             bonus_voucher_count,provider_payment_key,payment_method
           ) values (%s,%s,%s,%s,'m','p',%s,'done','voucher',%s,%s,%s,now(),%s,%s,%s,'NAVERPAY') returning id""",
        (f"o-{suffix}", f"t-{suffix}", user_id, merchant_id, paid * unit, product_id, paid + bonus, unit, paid, bonus, f"trx-{suffix}"),
    ).fetchone()[0]
    conn.execute(
        """insert into vouchers(user_id,merchant_id,product_id,order_id,issue_index,purchase_price,
                                purchase_price_won,status,pg_transaction_id)
           select %s,%s,%s,%s,n,case when n<=%s then %s else 0 end,case when n<=%s then %s else 0 end,'unused',%s
           from generate_series(1,%s) n""",
        (user_id, merchant_id, product_id, order_id, paid, unit, paid, unit, f"trx-{suffix}", paid + bonus),
    )
    return user_id, merchant_id, order_id


def _claim(conn, seeded):
    user_id, merchant_id, order_id = seeded
    return conn.execute(
        "select claim_purchase_order_refund(%s,%s,%s,%s,null)", (order_id, merchant_id, user_id, user_id)
    ).fetchone()[0]


def test_order_without_bonus_vouchers_can_be_refunded_after_the_fix(refund_db):
    import psycopg

    with psycopg.connect(refund_db, autocommit=True) as conn:
        single = _seed(conn, paid=1, bonus=0)
        # Before the fix: the defect this migration removes.
        with pytest.raises(psycopg.errors.RaiseException, match="VOUCHER_REFUND_SNAPSHOT_INCOMPLETE"):
            _claim(conn, single)
        assert conn.execute("select count(*) from refund_requests").fetchone()[0] == 0

        conn.execute(FIX.read_text(encoding="utf-8"))

        claim = _claim(conn, single)
        assert claim["refund_amount"] == 100 and claim["point_amount"] == 0
        assert claim["refunded_voucher_count"] == 1 and claim["forfeited_voucher_count"] == 0
        assert claim["acquired"] is True and claim["provider_succeeded"] is False

        # Orders with bonus vouchers keep working.
        bonus = _claim(conn, _seed(conn, paid=10, bonus=1, unit=8000))
        assert bonus["refund_amount"] == 80000 and bonus["forfeited_voucher_count"] == 1


def test_fix_still_fails_closed_on_broken_snapshots(refund_db):
    import psycopg

    with psycopg.connect(refund_db, autocommit=True) as conn:
        conn.execute(FIX.read_text(encoding="utf-8"))
        # A no-bonus order whose paid prices do not add up to the charge.
        wrong_total = _seed(conn, paid=2, bonus=0)
        conn.execute("update vouchers set purchase_price_won=1 where order_id=%s and issue_index=2", (wrong_total[2],))
        # An order that claims a bonus voucher but has no such row.
        missing_bonus = _seed(conn, paid=1, bonus=0)
        conn.execute("update payment_orders set bonus_voucher_count=1,voucher_count=2 where id=%s", (missing_bonus[2],))
        # A bonus voucher that carries a price.
        priced_bonus = _seed(conn, paid=1, bonus=1)
        conn.execute("update vouchers set purchase_price_won=5 where order_id=%s and issue_index=2", (priced_bonus[2],))
        for seeded in (wrong_total, missing_bonus, priced_bonus):
            with pytest.raises(psycopg.errors.RaiseException, match="VOUCHER_REFUND_SNAPSHOT_INCOMPLETE"):
                _claim(conn, seeded)
        assert conn.execute("select count(*) from refund_requests").fetchone()[0] == 0
