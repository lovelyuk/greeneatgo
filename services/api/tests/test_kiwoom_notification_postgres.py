import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).resolve().parents[3] / "infra" / "migrations"


@pytest.fixture(scope="module")
def notification_db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL for PostgreSQL 16 notification integration")
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(url, autocommit=True) as conn:
        assert 160000 <= int(conn.execute("show server_version_num").fetchone()[0]) < 170000
        conn.execute("drop schema if exists public cascade; create schema public")
        conn.execute("drop schema if exists auth cascade; create schema auth")
        conn.execute("drop schema if exists storage cascade; create schema storage")
        conn.execute("""
          do $$ begin
            if not exists(select 1 from pg_roles where rolname='anon') then create role anon nologin; end if;
            if not exists(select 1 from pg_roles where rolname='authenticated') then create role authenticated nologin; end if;
            if not exists(select 1 from pg_roles where rolname='service_role') then create role service_role nologin bypassrls; end if;
          end $$;
          create table auth.users(id uuid primary key);
          create function auth.uid() returns uuid language sql stable as $$ select null::uuid $$;
          create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);
        """)
        if not conn.execute("select exists(select 1 from pg_publication where pubname='supabase_realtime')").fetchone()[0]:
            conn.execute("create publication supabase_realtime")
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(migration.read_text(encoding="utf-8"))
        # Replaying the newest evolution is required and must preserve behavior.
        conn.execute((MIGRATIONS / "0038_atomic_kiwoom_notifications.sql").read_text(encoding="utf-8"))
    return url


@pytest.fixture
def pg(notification_db):
    import psycopg
    with psycopg.connect(notification_db) as conn:
        yield conn
        conn.rollback()


def parties(pg):
    user = pg.execute("insert into app_users(id,display_name,role,status) values(gen_random_uuid(),'buyer','customer','active') returning id").fetchone()[0]
    merchant = pg.execute("insert into merchants(name,qr_token,view_token) values('merchant',%s,%s) returning id", (str(uuid.uuid4()), str(uuid.uuid4()))).fetchone()[0]
    company = pg.execute("insert into companies(name) values('company') returning id").fetchone()[0]
    return user, merchant, company


def direct_order(pg, user, merchant, suffix, tax_type="taxable", legacy=False):
    product = pg.execute("insert into merchant_products(merchant_id,name,price,tax_type) values(%s,%s,1100,%s) returning id", (merchant, suffix, tax_type)).fetchone()[0]
    if legacy:
        pg.execute("set local session_replication_role=replica")
    row = pg.execute("""insert into payment_orders(order_id,checkout_token,user_id,merchant_id,product_id,
        merchant_name,product_name,amount,status,pay_type,tax_type,tax_review_required)
        values(%s,%s,%s,%s,%s,'merchant',%s,1100,'ready','direct',%s,%s) returning id,order_id""",
        (f"GE-{suffix}", f"token-{suffix}", user, merchant, product, suffix,
         "unclassified" if legacy else tax_type, legacy)).fetchone()
    if legacy:
        pg.execute("set local session_replication_role=origin")
    return row, product


def complete(pg, order, trx, payload=None, amount=1100, payment_method="CARD"):
    from psycopg.types.json import Jsonb
    body = payload or {
        "CPID": "CPID", "ORDERNO": order[1], "AMOUNT": str(amount),
        "PAYMETHOD": payment_method, "DAOUTRX": trx,
    }
    return pg.execute("select complete_kiwoom_payment_notification(%s,%s,'CPID',%s,%s,%s,%s,'127.0.0.1')",
                      (order[0], order[1], amount, payment_method, trx, Jsonb(body))).fetchone()[0]


def test_normal_direct_is_atomic_durable_duplicate_safe_and_conflicts(pg):
    import psycopg
    user, merchant, _ = parties(pg)
    order, _ = direct_order(pg, user, merchant, "direct")
    first = complete(pg, order, "trx-direct")
    duplicate = complete(pg, order, "trx-direct")
    assert first["duplicate"] is False and duplicate["duplicate"] is True
    assert pg.execute("select status,provider_payment_key from payment_orders where id=%s", (order[0],)).fetchone() == ("done", "trx-direct")
    assert pg.execute("select count(*),min(review_status) from payment_notification_inbox where order_id=%s", (order[0],)).fetchone() == (1, "released")
    with pytest.raises(psycopg.errors.RaiseException, match="NOTIFICATION_IDEMPOTENCY_CONFLICT"):
        with pg.transaction():
            complete(pg, order, "trx-direct", {"changed": True})
    other, _ = direct_order(pg, user, merchant, "other")
    with pytest.raises(psycopg.errors.RaiseException, match="NOTIFICATION_IDEMPOTENCY_CONFLICT"):
        with pg.transaction():
            complete(pg, other, "trx-direct")
    assert pg.execute("select status from payment_orders where id=%s", (other[0],)).fetchone()[0] == "ready"


def test_legacy_product_resolution_audits_and_missing_classification_rolls_back_then_retries(pg):
    import psycopg
    user, merchant, _ = parties(pg)
    order, _ = direct_order(pg, user, merchant, "legacy-product", legacy=True)
    result = complete(pg, order, "trx-legacy")
    assert result["tax_type"] == "taxable"
    assert pg.execute("select tax_type,tax_review_required,status from payment_orders where id=%s", (order[0],)).fetchone() == ("taxable", False, "done")
    proof = pg.execute("select selected_tax_type,reason from tax_classification_audit where order_id=%s", (order[0],)).fetchone()
    assert proof[0] == "taxable" and "merchant_product:" in proof[1]

    blocked, product = direct_order(pg, user, merchant, "legacy-blocked", tax_type="unclassified", legacy=True)
    with pytest.raises(psycopg.errors.RaiseException, match="TAX_TYPE_UNCLASSIFIED"):
        with pg.transaction():
            complete(pg, blocked, "trx-blocked")
    assert pg.execute("select status,tax_review_required from payment_orders where id=%s", (blocked[0],)).fetchone() == ("ready", True)
    assert pg.execute("select count(*) from payment_notification_inbox where order_id=%s", (blocked[0],)).fetchone()[0] == 0
    pg.execute("update merchant_products set tax_type='tax_free' where id=%s", (product,))
    assert complete(pg, blocked, "trx-blocked")["tax_type"] == "tax_free"


def test_old_pending_inbox_retry_uses_authoritative_completion_and_conflicts_stay_pending(pg):
    import psycopg
    from psycopg.types.json import Jsonb

    user, merchant, _ = parties(pg)
    order, _ = direct_order(pg, user, merchant, "old-pending", legacy=True)
    old_payload = {
        "CPID": "CPID", "ORDERNO": order[1], "AMOUNT": "1100",
        "PAYMETHOD": "CARD", "DAOUTRX": "trx-old-pending",
    }
    inbox_id = pg.execute("""insert into payment_notification_inbox(
          order_id,merchant_id,provider_transaction_id,provider_order_id,cpid,amount,
          payment_method,normalized_payload,source_ip)
        values(%s,%s,'trx-old-pending',%s,'CPID',1100,'CARD',%s,'127.0.0.1') returning id""",
        (order[0], merchant, order[1], Jsonb(old_payload))).fetchone()[0]

    retry_payload = {**old_payload, "source_ip": "127.0.0.1"}
    with pytest.raises(psycopg.errors.RaiseException, match="NOTIFICATION_IDEMPOTENCY_CONFLICT"):
        with pg.transaction():
            complete(pg, order, "trx-old-pending", {**retry_payload, "SETTDATE": "conflict"})
    assert pg.execute("select review_status from payment_notification_inbox where id=%s", (inbox_id,)).fetchone()[0] == "pending"
    assert pg.execute("select status,tax_type,tax_review_required from payment_orders where id=%s", (order[0],)).fetchone() == ("ready", "unclassified", True)
    assert pg.execute("select count(*) from tax_classification_audit where order_id=%s", (order[0],)).fetchone()[0] == 0

    first = complete(pg, order, "trx-old-pending", retry_payload)
    duplicate = complete(pg, order, "trx-old-pending", retry_payload)
    assert first["duplicate"] is False and duplicate["duplicate"] is True
    assert pg.execute("select status,tax_type,tax_review_required from payment_orders where id=%s", (order[0],)).fetchone() == ("done", "taxable", False)
    assert pg.execute("select review_status from payment_notification_inbox where id=%s", (inbox_id,)).fetchone()[0] == "released"
    assert pg.execute("select count(*) from tax_classification_audit where inbox_id=%s", (inbox_id,)).fetchone()[0] == 1


def test_service_role_cannot_invoke_retired_manual_tax_release(pg):
    import psycopg

    assert pg.execute("select to_regprocedure('public.release_legacy_tax_review(uuid,uuid,uuid,text,text)')").fetchone()[0] is None
    with pytest.raises(psycopg.errors.UndefinedFunction):
        with pg.transaction():
            pg.execute("set local role service_role")
            pg.execute("select public.release_legacy_tax_review(gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),'taxable','manual')")


def test_concurrent_identical_callback_fulfills_once(notification_db):
    import psycopg
    with psycopg.connect(notification_db) as setup:
        user, merchant, _ = parties(setup)
        order, _ = direct_order(setup, user, merchant, "concurrent")
        setup.commit()

    def invoke():
        with psycopg.connect(notification_db) as conn:
            result = complete(conn, order, "trx-concurrent")
            conn.commit()
            return result["duplicate"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(f.result(timeout=10) for f in (pool.submit(invoke), pool.submit(invoke)))
    assert outcomes == [False, True]
    with psycopg.connect(notification_db) as verify:
        assert verify.execute("select count(*) from payment_notification_inbox where order_id=%s", (order[0],)).fetchone()[0] == 1


def test_voucher_and_subsidized_fulfillment_and_transaction_rollback(pg):
    import psycopg
    user, merchant, company = parties(pg)
    vp = pg.execute("insert into voucher_products(merchant_id,name,voucher_count,unit_price,tax_type) values(%s,'voucher',2,1100,'taxable') returning id", (merchant,)).fetchone()[0]
    voucher = pg.execute("""insert into payment_orders(order_id,checkout_token,user_id,merchant_id,merchant_name,product_name,
      amount,status,pay_type,voucher_product_id,voucher_count,paid_voucher_count,bonus_voucher_count,voucher_purchase_price)
      values('GE-voucher','tok-voucher',%s,%s,'merchant','voucher',2200,'ready','voucher',%s,2,2,0,1100) returning id,order_id""",
      (user, merchant, vp)).fetchone()
    from psycopg.types.json import Jsonb
    body = {"CPID": "CPID", "ORDERNO": voucher[1], "AMOUNT": "2200", "PAYMETHOD": "CARD", "DAOUTRX": "trx-voucher"}
    pg.execute("select complete_kiwoom_payment_notification(%s,%s,'CPID',2200,'CARD','trx-voucher',%s,'127.0.0.1')", (voucher[0], voucher[1], Jsonb(body)))
    assert pg.execute("select count(*),sum(purchase_price_won) from vouchers where order_id=%s", (voucher[0],)).fetchone() == (2, 2200)

    pg.execute("insert into merchant_companies(merchant_id,company_id,status,unit_price,tax_type,subsidy_enabled) values(%s,%s,'active',1100,'tax_free',true)", (merchant, company))
    pg.execute("set local session_replication_role=replica")
    subsidized = pg.execute("""insert into payment_orders(order_id,checkout_token,user_id,merchant_id,merchant_name,product_name,
      amount,status,pay_type,voucher_product_id,voucher_count,paid_voucher_count,bonus_voucher_count,voucher_purchase_price,
      company_id,company_subsidy_amount,restaurant_subsidy_amount,total_employee_burden,point_amount,point_reserved,tax_type,tax_review_required)
      values('GE-subsidy','tok-subsidy',%s,%s,'merchant','legacy subsidy',1000,'ready','subsidized',null,1,1,0,1100,
      %s,50,50,1100,100,true,'unclassified',true) returning id,order_id""", (user, merchant, company)).fetchone()
    pg.execute("set local session_replication_role=origin")
    with pytest.raises(psycopg.errors.RaiseException, match="POINT_RESERVATION_CONFLICT"):
        with pg.transaction():
            complete(pg, subsidized, "trx-subsidy", {
                "CPID": "CPID", "ORDERNO": subsidized[1], "AMOUNT": "1000",
                "PAYMETHOD": "CARD", "DAOUTRX": "trx-subsidy",
            }, amount=1000)
    assert pg.execute("select status,tax_type,tax_review_required from payment_orders where id=%s", (subsidized[0],)).fetchone() == ("ready", "unclassified", True)
    assert pg.execute("select count(*) from payment_notification_inbox where order_id=%s", (subsidized[0],)).fetchone()[0] == 0
    pg.execute("update app_users set point_balance=100,point_reserved=100 where id=%s", (user,))
    result = complete(pg, subsidized, "trx-subsidy", {
        "CPID": "CPID", "ORDERNO": subsidized[1], "AMOUNT": "1000",
        "PAYMETHOD": "CARD", "DAOUTRX": "trx-subsidy",
    }, amount=1000)
    assert result["tax_type"] == "tax_free" and result["duplicate"] is False
    assert pg.execute("select status from payment_orders where id=%s", (subsidized[0],)).fetchone()[0] == "done"
    assert pg.execute("select count(*) from payment_notification_inbox where order_id=%s", (subsidized[0],)).fetchone()[0] == 1
    assert pg.execute("select count(*) from vouchers where order_id=%s", (subsidized[0],)).fetchone()[0] == 1
