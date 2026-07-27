import base64
import os
import uuid
from datetime import date
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).resolve().parents[3] / "infra" / "migrations"
MIGRATION_39 = (MIGRATIONS / "0039_popbill_tax_invoice_issuance.sql").read_text(encoding="utf-8")


@pytest.fixture
def legacy_db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL for PostgreSQL 16 legacy migration integration")
    psycopg = pytest.importorskip("psycopg")
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from psycopg import sql

    admin = conninfo_to_dict(url)
    dbname = f"greeneatgo_legacy_{uuid.uuid4().hex}"
    test_url = make_conninfo(**{**admin, "dbname": dbname})
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("create database {}").format(sql.Identifier(dbname)))
    try:
        with psycopg.connect(test_url, autocommit=True) as conn:
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
              create publication supabase_realtime;
            """)
            for migration in sorted(MIGRATIONS.glob("*.sql")):
                if migration.name >= "0039":
                    break
                conn.execute(migration.read_text(encoding="utf-8"))
            # Models the value that 0039's conservative classifier has established before
            # it reviews the corresponding historical invoice snapshot.
            conn.execute("alter table settlements add column settlement_tax_type text")
        yield test_url
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("select pg_terminate_backend(pid) from pg_stat_activity where datname=%s", (dbname,))
            conn.execute(sql.SQL("drop database if exists {}").format(sql.Identifier(dbname)))


def _seed_original(conn, *, key: str, active: bool, legal_mismatch: bool = False):
    company = conn.execute("insert into companies(name) values ('legacy company') returning id").fetchone()[0]
    merchant = conn.execute(
        "insert into merchants(name,qr_token,view_token) values ('legacy merchant',%s,%s) returning id",
        (str(uuid.uuid4()), str(uuid.uuid4())),
    ).fetchone()[0]
    sid = conn.execute("""
      insert into settlements(company_id,merchant_id,period_ym,period_from,period_to,tx_count,
        supply_amount,vat_amount,total_amount,settlement_tax_type,status,settlement_status,tax_invoice_status)
      values(%s,%s,%s,'2026-07-01','2026-07-31',1,100,0,100,'taxable','draft','sent','not_requested') returning id
    """, (company, merchant, uuid.uuid4().hex)).fetchone()[0]
    tax_type, write_date, supply, vat, total = (
        ("tax_free", "2026-07-30", 90, 0, 90) if legal_mismatch
        else ("taxable", "2026-07-31", 100, 0, 100)
    )
    conn.execute("""
      insert into tax_invoices(settlement_id,company_id,merchant_id,document_type,invoicer_mgt_key,
        tax_type,write_date,supply_amount,vat_amount,total_amount,supplier_snapshot,recipient_snapshot,
        issued_at,provider_response,popbill_status_message)
      values(%s,%s,%s,'original',%s,%s,%s,%s,%s,%s,
        '{"frozen":"supplier"}'::jsonb,'{"frozen":"recipient"}'::jsonb,
        case when %s then '2026-07-31T01:00:00Z'::timestamptz end,
        '{"raw":"provider-pii"}'::jsonb,'raw provider PII')
    """, (sid, company, merchant, key, tax_type, write_date, supply, vat, total, active))
    return sid


def _canonical(sid: uuid.UUID) -> str:
    return "GE" + base64.urlsafe_b64encode(sid.bytes).decode().rstrip("=")


def test_inactive_valid_noncanonical_legacy_is_canonicalized_and_legal_snapshot_repaired(legacy_db):
    import psycopg
    with psycopg.connect(legacy_db, autocommit=True) as conn:
        sid = _seed_original(conn, key="VALID_BUT_OLD", active=False, legal_mismatch=True)
        conn.execute(MIGRATION_39)
        row = conn.execute("""select invoicer_mgt_key,tax_type,write_date,supply_amount,vat_amount,total_amount,
                              supplier_snapshot,recipient_snapshot,provider_response,popbill_status_message
                              from tax_invoices where settlement_id=%s""", (sid,)).fetchone()
        assert row[:6] == (_canonical(sid), "taxable", date(2026, 7, 31), 100, 0, 100)
        assert row[6:8] == ({"frozen": "supplier"}, {"frozen": "recipient"})
        assert row[8:] == (None, None)


def test_active_valid_noncanonical_legacy_key_aborts(legacy_db):
    import psycopg
    with psycopg.connect(legacy_db, autocommit=True) as conn:
        _seed_original(conn, key="VALID_BUT_WRONG", active=True)
        with pytest.raises(psycopg.errors.RaiseException, match="LEGACY_POPBILL_KEY_REVIEW_REQUIRED"):
            conn.execute(MIGRATION_39)


def test_active_legacy_legal_mismatch_aborts(legacy_db):
    import psycopg
    with psycopg.connect(legacy_db, autocommit=True) as conn:
        # Seed once to obtain normal party IDs, then align identity to its settlement UUID.
        seeded = _seed_original(conn, key="TEMP", active=True, legal_mismatch=True)
        conn.execute("update tax_invoices set invoicer_mgt_key=%s where settlement_id=%s", (_canonical(seeded), seeded))
        with pytest.raises(psycopg.errors.RaiseException, match="LEGACY_TAX_INVOICE_SNAPSHOT_REVIEW_REQUIRED"):
            conn.execute(MIGRATION_39)
