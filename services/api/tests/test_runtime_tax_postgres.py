import os
from pathlib import Path

import pytest


MIGRATIONS = Path(__file__).resolve().parents[3] / "infra" / "migrations"


@pytest.fixture(scope="module")
def runtime_db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to run PostgreSQL 16 runtime-tax integration tests")
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(url, autocommit=True) as conn:
        version = int(conn.execute("show server_version_num").fetchone()[0])
        assert 160000 <= version < 170000, "runtime-tax integration requires PostgreSQL 16"
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
            create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);
            """
        )
        if not conn.execute("select exists(select 1 from pg_publication where pubname='supabase_realtime')").fetchone()[0]:
            conn.execute("create publication supabase_realtime")
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(migration.read_text(encoding="utf-8"))
        # Replaying the newest evolution is a required production property.
        conn.execute((MIGRATIONS / "0038_atomic_kiwoom_notifications.sql").read_text(encoding="utf-8"))
    return url


@pytest.fixture
def pg(runtime_db):
    import psycopg

    with psycopg.connect(runtime_db) as conn:
        yield conn
        conn.rollback()


def _actor_and_merchants(pg):
    actor = pg.execute(
        "insert into app_users(id,display_name,role,status) values (gen_random_uuid(),'reviewer','merchant_admin','active') returning id"
    ).fetchone()[0]
    merchants = [
        pg.execute(
            "insert into merchants(name,qr_token,view_token) values (%s,%s,%s) returning id",
            (name, f"qr-{name}", f"view-{name}"),
        ).fetchone()[0]
        for name in ("runtime-a", "runtime-b")
    ]
    pg.execute("update app_users set merchant_id=%s where id=%s", (merchants[0], actor))
    return actor, merchants


def _legacy_direct_order(pg, actor, merchant, suffix="one"):
    product = pg.execute(
        "insert into merchant_products(merchant_id,name,price,tax_type) values (%s,%s,1100,'taxable') returning id",
        (merchant, f"product-{suffix}"),
    ).fetchone()[0]
    pg.execute("set local session_replication_role=replica")
    order = pg.execute(
        """insert into payment_orders(
               order_id,checkout_token,user_id,merchant_id,product_id,merchant_name,product_name,
               amount,status,pay_type,tax_type,tax_review_required
             ) values (%s,%s,%s,%s,%s,'runtime','legacy',1100,'ready','direct','unclassified',true)
             returning id,order_id""",
        (f"GE-{suffix}", f"token-{suffix}", actor, merchant, product),
    ).fetchone()
    pg.execute("set local session_replication_role=origin")
    return order


@pytest.mark.parametrize(
    "tax_type,supply,vat,total",
    [
        ("taxable", None, None, None),
        ("tax_free", None, None, None),
        ("taxable", 1000, None, 1100),
        ("tax_free", 1100, 0, None),
        ("taxable", 999, 101, 1100),
        ("tax_free", 1099, 0, 1100),
        ("unclassified", 1000, 100, 1100),
    ],
)
def test_postgres_rejects_incomplete_wrong_or_unclassified_full_snapshots(pg, tax_type, supply, vat, total):
    import psycopg

    actor, _ = _actor_and_merchants(pg)
    company = pg.execute("insert into companies(name) values ('tax-shape') returning id").fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        with pg.transaction():
            pg.execute(
                """insert into meal_transactions(user_id,company_id,amount,kind,tax_type,supply_amount,vat_amount,total_amount)
                     values (%s,%s,-1100,'spend',%s,%s,%s,%s)""",
                (actor, company, tax_type, supply, vat, total),
            )


def test_postgres_accepts_exact_full_and_empty_unclassified_snapshots_for_both_targets(pg):
    actor, _ = _actor_and_merchants(pg)
    company = pg.execute("insert into companies(name) values ('valid-tax-shape') returning id").fetchone()[0]
    pg.execute(
        """insert into meal_transactions(
             user_id,company_id,amount,kind,tax_type,supply_amount,vat_amount,total_amount,
             settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount)
           values (%s,%s,-1100,'spend','taxable',1000,100,1100,'tax_free',1100,0,1100),
                  (%s,%s,-1,'spend','unclassified',null,null,null,'unclassified',null,null,null)""",
        (actor, company, actor, company),
    )


def test_service_role_has_read_only_tables_direct_release_is_blocked_and_function_is_audited(pg):
    import psycopg

    actor, merchants = _actor_and_merchants(pg)
    order_id, provider_order = _legacy_direct_order(pg, actor, merchants[0])
    inbox_id = pg.execute(
        """insert into payment_notification_inbox(
             order_id,merchant_id,provider_transaction_id,provider_order_id,cpid,amount,
             payment_method,normalized_payload,source_ip)
           values(%s,%s,'trx-one',%s,'CPID',1100,'CARD','{}','127.0.0.1') returning id""",
        (order_id, merchants[0], provider_order),
    ).fetchone()[0]

    privileges = pg.execute(
        """select has_table_privilege('service_role','payment_notification_inbox','select'),
                  has_table_privilege('service_role','payment_notification_inbox','update'),
                  has_table_privilege('service_role','payment_notification_inbox','delete'),
                  has_table_privilege('service_role','payment_notification_inbox','truncate'),
                  has_table_privilege('service_role','tax_classification_audit','insert'),
                  has_table_privilege('service_role','tax_classification_audit','update'),
                  has_table_privilege('service_role','tax_classification_audit','delete'),
                  has_table_privilege('service_role','tax_classification_audit','truncate')"""
    ).fetchone()
    assert privileges == (True, False, False, False, False, False, False, False)

    # Caller-controlled custom settings prove nothing.
    with pytest.raises(psycopg.errors.RaiseException, match="AUDITED_TAX_CLASSIFICATION_REQUIRED"):
        with pg.transaction():
            pg.execute("set local app.audited_tax_release='on'")
            pg.execute("set local app.audited_notification_release='on'")
            pg.execute("update payment_orders set tax_type='taxable' where id=%s", (order_id,))
    with pytest.raises(psycopg.errors.RaiseException, match="AUDITED_TAX_CLASSIFICATION_REQUIRED"):
        with pg.transaction():
            pg.execute("update payment_orders set tax_type='taxable' where id=%s", (order_id,))
    # A proof with the wrong selected type cannot authorize this target mutation.
    with pytest.raises(psycopg.errors.RaiseException, match="AUDITED_TAX_CLASSIFICATION_REQUIRED"):
        with pg.transaction():
            pg.execute(
                """insert into tax_classification_audit
                     (merchant_id,order_id,inbox_id,actor_id,previous_tax_type,selected_tax_type,reason)
                   values (%s,%s,%s,%s,'unclassified','tax_free','mismatched proof')""",
                (merchants[0], order_id, inbox_id, actor),
            )
            pg.execute("update payment_orders set tax_type='taxable' where id=%s", (order_id,))
    with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.RaiseException)):
        with pg.transaction():
            pg.execute("set local role service_role")
            pg.execute("update payment_orders set tax_type='taxable' where id=%s", (order_id,))

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with pg.transaction():
            pg.execute("set local role service_role")
            pg.execute("update public.payment_notification_inbox set review_status='released' where id=%s", (inbox_id,))
    with pytest.raises(psycopg.errors.RaiseException, match="COMPLETED_NOTIFICATION_REQUIRED"):
        with pg.transaction():
            pg.execute(
                "update payment_notification_inbox set review_status='released',processed_at=now(),processed_by=%s where id=%s",
                (actor, inbox_id),
            )

    assert pg.execute("select to_regprocedure('public.release_legacy_tax_review(uuid,uuid,uuid,text,text)')").fetchone()[0] is None
    pg.execute("set local role service_role")
    result = pg.execute(
        "select public.complete_kiwoom_payment_notification(%s,%s,'CPID',1100,'CARD','trx-one','{}','127.0.0.1')",
        (order_id, provider_order),
    ).fetchone()[0]
    pg.execute("reset role")
    assert result["status"] == "done" and result["duplicate"] is False
    assert pg.execute("select count(*) from tax_classification_audit where inbox_id=%s", (inbox_id,)).fetchone()[0] == 1
    assert pg.execute("select review_status,processed_by from payment_notification_inbox where id=%s", (inbox_id,)).fetchone() == ("released", actor)

    same = pg.execute(
        "select complete_kiwoom_payment_notification(%s,%s,'CPID',1100,'CARD','trx-one','{}','127.0.0.1')",
        (order_id, provider_order),
    ).fetchone()[0]
    assert same["duplicate"] is True
    with pytest.raises(psycopg.errors.RaiseException, match="NOTIFICATION_IDEMPOTENCY_CONFLICT"):
        with pg.transaction():
            pg.execute(
                "select complete_kiwoom_payment_notification(%s,%s,'CPID',1100,'CARD','trx-one','{\"changed\":true}','127.0.0.1')",
                (order_id, provider_order),
            )

    audit_id = pg.execute("select id from tax_classification_audit where inbox_id=%s", (inbox_id,)).fetchone()[0]
    for statement in (
        "update tax_classification_audit set reason='tampered audit' where id=%s",
        "delete from tax_classification_audit where id=%s",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="IMMUTABLE_TAX_CLASSIFICATION_AUDIT"):
            with pg.transaction():
                pg.execute(statement, (audit_id,))
    with pytest.raises(psycopg.errors.RaiseException, match="IMMUTABLE_TAX_CLASSIFICATION_AUDIT"):
        with pg.transaction():
            pg.execute("truncate tax_classification_audit")


def test_legacy_voucher_list_and_classification_are_tenant_scoped_idempotent_and_conflict_safe(pg):
    import psycopg

    actor, merchants = _actor_and_merchants(pg)
    order_id, _ = _legacy_direct_order(pg, actor, merchants[0], "voucher-parent")
    product = pg.execute(
        """insert into voucher_products(merchant_id,name,voucher_count,unit_price,tax_type)
             values (%s,'legacy voucher',1,1100,'taxable') returning id""",
        (merchants[0],),
    ).fetchone()[0]
    voucher = pg.execute(
        """insert into vouchers(user_id,merchant_id,product_id,order_id,issue_index,purchase_price,purchase_price_won,tax_type)
             values (%s,%s,%s,%s,1,1100,1100,'unclassified') returning id""",
        (actor, merchants[0], product, order_id),
    ).fetchone()[0]
    own = pg.execute("select list_active_legacy_vouchers(%s,10,0)", (merchants[0],)).fetchone()[0]
    other = pg.execute("select list_active_legacy_vouchers(%s,10,0)", (merchants[1],)).fetchone()[0]
    assert [item["id"] for item in own["items"]] == [str(voucher)]
    assert other["items"] == []
    assert "user_id" not in own["items"][0]

    with pytest.raises(psycopg.errors.RaiseException, match="VOUCHER_NOT_FOUND"):
        with pg.transaction():
            pg.execute(
                "select classify_legacy_voucher(%s,%s,%s,'taxable','wrong tenant')",
                (voucher, merchants[1], actor),
            )
    first = pg.execute(
        "select classify_legacy_voucher(%s,%s,%s,'taxable','catalog reviewed')",
        (voucher, merchants[0], actor),
    ).fetchone()[0]
    same = pg.execute(
        "select classify_legacy_voucher(%s,%s,%s,'taxable','safe retry')",
        (voucher, merchants[0], actor),
    ).fetchone()[0]
    assert first["duplicate"] is False and same["duplicate"] is True
    with pytest.raises(psycopg.errors.RaiseException, match="VOUCHER_NOT_CLASSIFIABLE"):
        with pg.transaction():
            pg.execute(
                "select classify_legacy_voucher(%s,%s,%s,'tax_free','conflicting type')",
                (voucher, merchants[0], actor),
            )


def test_legacy_payment_review_rpc_paginates_large_tenant_scoped_fixture(pg):
    actor, merchants = _actor_and_merchants(pg)
    for index in range(101):
        order_id, provider_order = _legacy_direct_order(pg, actor, merchants[0], f"page-{index:03d}")
        pg.execute(
            """insert into payment_notification_inbox(
                 order_id,merchant_id,provider_transaction_id,provider_order_id,cpid,amount,
                 payment_method,normalized_payload,source_ip)
               values(%s,%s,%s,%s,'CPID',1100,'CARD','{}','127.0.0.1')""",
            (order_id, merchants[0], f"trx-page-{index:03d}", provider_order),
        )
    first = pg.execute("select list_legacy_tax_reviews(%s,500,0)", (merchants[0],)).fetchone()[0]
    last = pg.execute("select list_legacy_tax_reviews(%s,50,100)", (merchants[0],)).fetchone()[0]
    other = pg.execute("select list_legacy_tax_reviews(%s,50,0)", (merchants[1],)).fetchone()[0]
    assert first["limit"] == 100 and len(first["items"]) == 100
    assert first["total"] == 101 and first["has_more"] is True
    assert last["offset"] == 100 and len(last["items"]) == 1 and last["has_more"] is False
    assert other["items"] == [] and other["total"] == 0
