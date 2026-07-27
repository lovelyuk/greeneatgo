import os
from decimal import Decimal
from pathlib import Path

import pytest


MIGRATIONS = Path(__file__).resolve().parents[3] / "infra" / "migrations"
MIGRATION_0036 = MIGRATIONS / "0036_runtime_tax_snapshots.sql"


def _reset_and_apply_through_0035(conn):
    conn.execute("drop schema if exists public cascade; create schema public")
    conn.execute("drop schema if exists auth cascade; create schema auth")
    conn.execute("drop schema if exists storage cascade; create schema storage")
    conn.execute(
        """
        do $$ begin
          if not exists(select 1 from pg_roles where rolname='anon') then create role anon nologin; end if;
          if not exists(select 1 from pg_roles where rolname='authenticated') then create role authenticated nologin; end if;
          if not exists(select 1 from pg_roles where rolname='service_role') then create role service_role nologin bypassrls; end if;
        end $$;
        create table auth.users(id uuid primary key);
        create function auth.uid() returns uuid language sql stable as $$ select null::uuid $$;
        create table storage.buckets(
          id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]
        );
        """
    )
    if not conn.execute(
        "select exists(select 1 from pg_publication where pubname='supabase_realtime')"
    ).fetchone()[0]:
        conn.execute("create publication supabase_realtime")
    for migration in sorted(MIGRATIONS.glob("*.sql")):
        if migration.name >= "0036_runtime_tax_snapshots.sql":
            break
        conn.execute(migration.read_text(encoding="utf-8"))


@pytest.fixture
def legacy_bonus_db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL for PostgreSQL 16 legacy bonus-voucher migration tests")
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(url, autocommit=True) as conn:
        version = int(conn.execute("show server_version_num").fetchone()[0])
        assert 160000 <= version < 170000, "legacy bonus-voucher integration requires PostgreSQL 16"
        _reset_and_apply_through_0035(conn)
    return url


def _seed_legacy_bonus_orders(conn):
    user_id = conn.execute(
        "insert into app_users(id,display_name,role,status) values (gen_random_uuid(),'legacy buyer','customer','active') returning id"
    ).fetchone()[0]
    merchant_id = conn.execute(
        "insert into merchants(name,qr_token,view_token) values ('legacy merchant','legacy-qr','legacy-view') returning id"
    ).fetchone()[0]
    product_id = conn.execute(
        """insert into voucher_products(
             merchant_id,name,voucher_count,bonus_count,unit_price,tax_type
           ) values (%s,'10 plus 1',10,1,8000,'taxable') returning id""",
        (merchant_id,),
    ).fetchone()[0]

    orders = {}
    for status in ("done", "ready"):
        orders[status] = conn.execute(
            """insert into payment_orders(
                 order_id,checkout_token,user_id,merchant_id,merchant_name,product_name,
                 amount,status,pay_type,voucher_product_id,voucher_count,voucher_purchase_price,
                 fulfilled_at,paid_voucher_count,bonus_voucher_count
               ) values (%s,%s,%s,%s,'legacy merchant','10 plus 1',80000,%s,'voucher',
                         %s,11,7272.7273,%s,10,1) returning id""",
            (
                f"legacy-{status}",
                f"legacy-token-{status}",
                user_id,
                merchant_id,
                status,
                product_id,
                "2026-01-01T00:00:00Z" if status == "done" else None,
            ),
        ).fetchone()[0]

    conn.execute(
        """insert into vouchers(
             user_id,merchant_id,product_id,order_id,issue_index,purchase_price,status,used_at
           )
           select %s,%s,%s,%s,n,7272.7273,
                  case when n=5 then 'used' else 'unused' end,
                  case when n=5 then '2026-01-02T00:00:00Z'::timestamptz else null end
           from generate_series(1,11) n""",
        (user_id, merchant_id, product_id, orders["done"]),
    )
    return user_id, merchant_id, product_id, orders


def test_0036_upgrades_legacy_bonus_orders_and_vouchers_before_0037_0038(legacy_bonus_db):
    import psycopg

    with psycopg.connect(legacy_bonus_db, autocommit=True) as conn:
        user_id, merchant_id, _, orders = _seed_legacy_bonus_orders(conn)

        migration_0036 = MIGRATION_0036.read_text(encoding="utf-8")
        conn.execute(migration_0036)

        for order_id in orders.values():
            assert conn.execute(
                """select voucher_purchase_price,tax_type
                   from payment_orders where id=%s""",
                (order_id,),
            ).fetchone() == (8000, "unclassified")

        prices = conn.execute(
            """select issue_index,purchase_price,purchase_price_won,status
               from vouchers where order_id=%s order by issue_index""",
            (orders["done"],),
        ).fetchall()
        assert sum(row[2] for row in prices[:10]) == 80000
        assert all(row[1] == 8000 and row[2] == 8000 for row in prices[:10])
        assert prices[4] == (5, 8000, 8000, "used")
        assert prices[10] == (11, 0, 0, "unused")
        assert conn.execute(
            "select count(*) from vouchers where order_id=%s", (orders["ready"],)
        ).fetchone()[0] == 0

        before_replay = conn.execute(
            """select issue_index,purchase_price,purchase_price_won,status,used_at
               from vouchers where order_id=%s order by issue_index""",
            (orders["done"],),
        ).fetchall()
        conn.execute(migration_0036)
        assert conn.execute(
            """select issue_index,purchase_price,purchase_price_won,status,used_at
               from vouchers where order_id=%s order by issue_index""",
            (orders["done"],),
        ).fetchall() == before_replay

        conn.execute((MIGRATIONS / "0037_atomic_settlement_workflows.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0038_atomic_kiwoom_notifications.sql").read_text(encoding="utf-8"))
        assert conn.execute(
            """select convalidated from pg_constraint
               where conrelid='public.payment_orders'::regclass
                 and conname='payment_orders_voucher_columns_check'"""
        ).fetchone() == (True,)

        refund = conn.execute(
            "select claim_purchase_order_refund(%s,%s,%s,%s,null)",
            (orders["done"], merchant_id, user_id, user_id),
        ).fetchone()[0]
        assert refund["refund_amount"] == 72000
        assert refund["refunded_voucher_count"] == 9
        assert refund["forfeited_voucher_count"] == 1


def _migration_state(conn):
    return (
        conn.execute(
            """select id,status,voucher_purchase_price,fulfilled_at
               from payment_orders order by id"""
        ).fetchall(),
        conn.execute(
            """select id,order_id,issue_index,purchase_price,status,used_at,
                      user_id,merchant_id,product_id,company_id,
                      company_subsidy_amount,restaurant_subsidy_amount,pg_transaction_id
               from vouchers order by order_id,issue_index"""
        ).fetchall(),
    )


def _assert_0036_aborts_without_mutation(conn, psycopg, message):
    before = _migration_state(conn)
    with pytest.raises(psycopg.errors.RaiseException, match=message):
        with conn.transaction():
            conn.execute(MIGRATION_0036.read_text(encoding="utf-8"))
    assert _migration_state(conn) == before
    assert conn.execute(
        """select exists(
             select 1 from pg_attribute
             where attrelid='public.vouchers'::regclass
               and attname='purchase_price_won' and not attisdropped
           )"""
    ).fetchone() == (False,)


def test_0036_rejects_done_order_with_wrong_legacy_voucher_price(legacy_bonus_db):
    import psycopg

    with psycopg.connect(legacy_bonus_db, autocommit=True) as conn:
        _, _, _, orders = _seed_legacy_bonus_orders(conn)
        conn.execute(
            """update vouchers set purchase_price=7000
               where order_id=%s and issue_index=6""",
            (orders["done"],),
        )

        _assert_0036_aborts_without_mutation(
            conn, psycopg, "LEGACY_BONUS_DONE_ORDER_MALFORMED"
        )


def test_0036_rejects_partial_done_voucher_set(legacy_bonus_db):
    import psycopg

    with psycopg.connect(legacy_bonus_db, autocommit=True) as conn:
        _, _, _, orders = _seed_legacy_bonus_orders(conn)
        conn.execute(
            "delete from vouchers where order_id=%s and issue_index=11",
            (orders["done"],),
        )

        _assert_0036_aborts_without_mutation(
            conn, psycopg, "LEGACY_BONUS_DONE_ORDER_MALFORMED"
        )


@pytest.mark.parametrize("mismatched_identity", ["user", "merchant", "product", "company"])
def test_0036_rejects_done_order_with_wrong_voucher_identity(
    legacy_bonus_db, mismatched_identity
):
    import psycopg

    with psycopg.connect(legacy_bonus_db, autocommit=True) as conn:
        _, merchant_id, _, orders = _seed_legacy_bonus_orders(conn)

        if mismatched_identity == "user":
            wrong_id = conn.execute(
                """insert into app_users(id,display_name,role,status)
                   values (gen_random_uuid(),'wrong legacy buyer','customer','active') returning id"""
            ).fetchone()[0]
            column = "user_id"
        elif mismatched_identity == "merchant":
            wrong_id = conn.execute(
                """insert into merchants(name,qr_token,view_token)
                   values ('wrong legacy merchant','wrong-legacy-qr','wrong-legacy-view')
                   returning id"""
            ).fetchone()[0]
            column = "merchant_id"
        elif mismatched_identity == "product":
            wrong_id = conn.execute(
                """insert into voucher_products(
                     merchant_id,name,voucher_count,bonus_count,unit_price,tax_type
                   ) values (%s,'wrong legacy product',10,1,8000,'taxable') returning id""",
                (merchant_id,),
            ).fetchone()[0]
            column = "product_id"
        else:
            wrong_id = conn.execute(
                "insert into companies(name) values ('wrong legacy company') returning id"
            ).fetchone()[0]
            column = "company_id"

        conn.execute(
            f"update vouchers set {column}=%s where order_id=%s and issue_index=6",
            (wrong_id, orders["done"]),
        )

        _assert_0036_aborts_without_mutation(
            conn, psycopg, "LEGACY_BONUS_DONE_ORDER_MALFORMED"
        )


def test_0036_rejects_ready_order_with_any_linked_voucher(legacy_bonus_db):
    import psycopg

    with psycopg.connect(legacy_bonus_db, autocommit=True) as conn:
        user_id, merchant_id, product_id, orders = _seed_legacy_bonus_orders(conn)
        conn.execute(
            """insert into vouchers(
                 user_id,merchant_id,product_id,order_id,issue_index,purchase_price
               ) values (%s,%s,%s,%s,1,7272.7273)""",
            (user_id, merchant_id, product_id, orders["ready"]),
        )

        _assert_0036_aborts_without_mutation(
            conn, psycopg, "LEGACY_BONUS_READY_ORDER_HAS_VOUCHERS"
        )


def test_0036_refunded_legacy_order_fails_closed_without_mutation(legacy_bonus_db):
    import psycopg

    with psycopg.connect(legacy_bonus_db, autocommit=True) as conn:
        _, _, _, orders = _seed_legacy_bonus_orders(conn)
        conn.execute(
            "update payment_orders set status='refunded' where id=%s",
            (orders["done"],),
        )

        _assert_0036_aborts_without_mutation(
            conn, psycopg, "LEGACY_BONUS_VOUCHER_STATUS_UNSUPPORTED"
        )
        assert conn.execute(
            "select status,voucher_purchase_price from payment_orders where id=%s",
            (orders["done"],),
        ).fetchone() == ("refunded", Decimal("7272.7273"))


def test_0036_distributes_non_even_paid_remainder_to_earliest_indexes(legacy_bonus_db):
    import psycopg

    with psycopg.connect(legacy_bonus_db, autocommit=True) as conn:
        user_id, merchant_id, _, orders = _seed_legacy_bonus_orders(conn)
        conn.execute(
            """update payment_orders
               set amount=80003,voucher_purchase_price=7273.0000
               where id=%s""",
            (orders["done"],),
        )
        conn.execute(
            "update vouchers set purchase_price=7273.0000 where order_id=%s",
            (orders["done"],),
        )
        conn.execute(
            "update vouchers set status='unused',used_at=null where order_id=%s",
            (orders["done"],),
        )

        conn.execute(MIGRATION_0036.read_text(encoding="utf-8"))

        rows = conn.execute(
            """select issue_index,purchase_price,purchase_price_won,status,used_at
               from vouchers where order_id=%s order by issue_index""",
            (orders["done"],),
        ).fetchall()
        assert [row[2] for row in rows] == [8001, 8001, 8001] + [8000] * 7 + [0]
        assert [row[1] for row in rows] == [8001, 8001, 8001] + [8000] * 7 + [0]
        assert sum(row[2] for row in rows) == 80003
        assert all(row[3:] == ("unused", None) for row in rows)
        assert conn.execute(
            "select voucher_purchase_price from payment_orders where id=%s",
            (orders["done"],),
        ).fetchone() == (Decimal("8000.3000"),)

        first_voucher_id = conn.execute(
            "select id from vouchers where order_id=%s and issue_index=1",
            (orders["done"],),
        ).fetchone()[0]
        conn.execute(
            "select classify_legacy_voucher(%s,%s,%s,'taxable','refund integration')",
            (first_voucher_id, merchant_id, user_id),
        )
        consumed = conn.execute(
            "select consume_voucher(%s,%s,'refund-fifo-non-even',null)",
            (user_id, merchant_id),
        ).fetchone()[0]
        assert consumed["voucher_id"] == str(first_voucher_id)
        assert consumed["amount"] == 8001

        refund = conn.execute(
            "select claim_purchase_order_refund(%s,%s,%s,%s,null)",
            (orders["done"], merchant_id, user_id, user_id),
        ).fetchone()[0]
        assert refund["refund_amount"] == 72002
        assert refund["refund_amount"] == conn.execute(
            """select sum(purchase_price_won) from vouchers
               where order_id=%s and status='unused'
                 and issue_index<=10""",
            (orders["done"],),
        ).fetchone()[0]
        assert refund["refunded_voucher_count"] == 9
        assert refund["forfeited_voucher_count"] == 1


def test_0036_refund_fails_closed_without_complete_integer_snapshots(legacy_bonus_db):
    import psycopg

    with psycopg.connect(legacy_bonus_db, autocommit=True) as conn:
        user_id, merchant_id, _, orders = _seed_legacy_bonus_orders(conn)
        conn.execute(MIGRATION_0036.read_text(encoding="utf-8"))
        conn.execute(
            """update vouchers set purchase_price_won=null
               where order_id=%s and issue_index=6""",
            (orders["done"],),
        )

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="VOUCHER_REFUND_SNAPSHOT_INCOMPLETE",
        ):
            conn.execute(
                "select claim_purchase_order_refund(%s,%s,%s,%s,null)",
                (orders["done"], merchant_id, user_id, user_id),
            )

        assert conn.execute(
            "select status from payment_orders where id=%s", (orders["done"],)
        ).fetchone() == ("done",)
        assert conn.execute(
            "select count(*) from refund_requests where order_id=%s", (orders["done"],)
        ).fetchone() == (0,)


def test_0036_does_not_coerce_unrelated_malformed_order_and_rolls_back(legacy_bonus_db):
    import psycopg

    with psycopg.connect(legacy_bonus_db, autocommit=True) as conn:
        _, _, product_id, orders = _seed_legacy_bonus_orders(conn)
        valid_order = orders["done"]
        valid_voucher_before = conn.execute(
            "select purchase_price,status from vouchers where order_id=%s order by issue_index",
            (valid_order,),
        ).fetchall()

        conn.execute(
            "alter table payment_orders drop constraint payment_orders_voucher_columns_check"
        )
        conn.execute(
            """update payment_orders
               set voucher_purchase_price=7000
               where id=%s""",
            (orders["ready"],),
        )

        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(MIGRATION_0036.read_text(encoding="utf-8"))

        assert conn.execute(
            "select voucher_purchase_price from payment_orders where id=%s", (valid_order,)
        ).fetchone() == (Decimal("7272.7273"),)
        assert conn.execute(
            "select purchase_price,status from vouchers where order_id=%s order by issue_index",
            (valid_order,),
        ).fetchall() == valid_voucher_before
        assert conn.execute(
            """select exists(
                 select 1 from pg_attribute
                 where attrelid='public.vouchers'::regclass
                   and attname='purchase_price_won' and not attisdropped
               )"""
        ).fetchone() == (False,)
        assert conn.execute(
            "select voucher_purchase_price from payment_orders where id=%s", (orders["ready"],)
        ).fetchone() == (7000,)
        assert conn.execute(
            "select tax_type from voucher_products where id=%s", (product_id,)
        ).fetchone() == ("taxable",)
