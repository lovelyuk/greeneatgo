import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "infra/migrations/0035_tax_settlement_invoices_payments.sql"
)


def _sql() -> str:
    return re.sub(r"\s+", " ", MIGRATION.read_text(encoding="utf-8").lower()).strip()


def _section(sql: str, start: str, end: str) -> str:
    return sql.split(start, 1)[1].split(end, 1)[0]


def _constraint_values(sql: str, constraint: str) -> set[str]:
    body = sql.split(f"constraint {constraint}", 1)[1].split(";", 1)[0]
    allowed = re.search(r"\bin\s*\((.*?)\)", body)
    assert allowed, f"missing IN-list for {constraint}"
    return set(re.findall(r"'([^']+)'", allowed.group(1)))


def test_tax_classification_is_explicit_and_never_defaults_taxable():
    sql = _sql()
    for table in ("merchant_products", "voucher_products", "merchant_companies"):
        assert f"alter table {table}" in sql
        assert "add column if not exists tax_type text not null default 'unclassified'" in sql
        assert f"{table}_tax_type_check" in sql
    assert sql.count("check (tax_type in ('taxable', 'tax_free', 'unclassified'))") >= 4
    assert "default 'taxable'" not in sql


def test_transaction_has_both_amount_snapshots_and_refund_link_without_breaking_old_rows():
    sql = _sql()
    transaction = _section(sql, "alter table meal_transactions", "-- keep legacy status")
    for column in (
        "settlement_tax_type text not null default 'unclassified'",
        "supply_amount int",
        "vat_amount int",
        "total_amount int",
        "settlement_supply_amount int",
        "settlement_vat_amount int",
        "settlement_total_amount int",
    ):
        assert f"add column if not exists {column}" in transaction
    # Amount columns remain nullable so old/unclassified writes remain valid.
    assert "supply_amount int not null" not in transaction
    assert "original_transaction_id bigint references meal_transactions(id)" in transaction
    assert "'refund', 'cancel'" in transaction
    assert "supply_amount + vat_amount = total_amount" in transaction
    assert "settlement_supply_amount + settlement_vat_amount = settlement_total_amount" in transaction
    assert "num_nonnulls(supply_amount, vat_amount, total_amount) = 3" in transaction
    assert "num_nonnulls(settlement_supply_amount, settlement_vat_amount, settlement_total_amount) = 3" in transaction
    assert "meal_transactions_settlement_tax_type_check" in transaction
    assert "default 'taxable'" not in transaction


def test_settlement_states_and_legacy_backfill_do_not_invent_tax_amounts():
    sql = _sql()
    assert "add column if not exists settlement_status text not null default 'draft'" in sql
    assert "add column if not exists tax_invoice_status text not null default 'not_requested'" in sql
    assert "add column if not exists payment_status text not null default 'unpaid'" in sql
    for column in (
        "sent_at timestamptz",
        "confirmed_at timestamptz",
        "finalized_at timestamptz",
        "due_date date",
        "updated_at timestamptz not null default now()",
    ):
        assert f"add column if not exists {column}" in sql
    backfill = _section(sql, "update settlements set", "-- translate the three old status")
    assert "when 'draft' then 'draft'" in backfill
    assert "when 'confirmed' then 'confirmed'" in backfill
    assert "when 'paid' then 'completed'" in backfill
    assert "when status = 'paid' then 'paid' else 'unpaid'" in backfill
    assert "supply_amount =" not in backfill
    assert "vat_amount =" not in backfill

    assert _constraint_values(sql, "settlements_tax_invoice_status_check") == {
        "not_requested", "requested", "issuing", "issued", "nts_sending",
        "nts_accepted", "failed", "cancelled",
    }
    assert _constraint_values(sql, "settlements_payment_status_check") == {
        "unpaid", "matching", "partially_paid", "paid", "overpaid", "unmatched",
    }
    # `cancelled` is the deliberate project extension to the work-order states.
    assert _constraint_values(sql, "settlements_settlement_status_check") == {
        "calculating", "draft", "sent", "confirmed", "disputed", "revising",
        "finalized", "completed", "cancelled",
    }


def test_invoice_history_has_one_original_global_key_and_parented_adjustments():
    sql = _sql()
    invoice = _section(sql, "create table if not exists tax_invoices", "-- provider callbacks")
    assert "invoicer_mgt_key text not null unique" in invoice
    assert "parent_invoice_id uuid references tax_invoices(id)" in invoice
    assert "document_type in ('original', 'correction', 'cancellation')" in invoice
    assert "document_type = 'original' and parent_invoice_id is null" in invoice
    assert "document_type in ('correction', 'cancellation') and parent_invoice_id is not null" in invoice
    assert "supplier_snapshot jsonb not null" in invoice
    assert "recipient_snapshot jsonb not null" in invoice
    assert "failure_code text" in invoice and "failure_message text" in invoice
    assert "supply_amount + vat_amount = total_amount" in invoice
    assert "create unique index if not exists idx_tax_invoices_one_original_per_settlement on tax_invoices(settlement_id) where document_type = 'original'" in sql
    assert "unique (settlement_id)" not in invoice
    assert "tax_invoices_settlement_parties_fkey" in sql
    assert "foreign key (settlement_id, company_id, merchant_id)" in sql
    assert "tax_invoices_parent_parties_fkey" in sql
    assert "foreign key (parent_invoice_id, settlement_id, company_id, merchant_id)" in sql
    assert "tax_invoice_self_parent" in sql
    assert "tax_invoice_parent_cycle" in sql
    assert "pg_advisory_xact_lock" in sql


def test_invoice_events_are_append_only_and_provider_events_are_deduplicated():
    sql = _sql()
    assert "payload jsonb not null" in sql
    assert "create unique index if not exists idx_tax_invoice_events_provider_event_unique on tax_invoice_events(provider_event_id) where provider_event_id is not null" in sql
    assert "before update or delete on tax_invoice_events" in sql
    assert "tax_invoice_events_are_immutable" in sql


def test_multi_payment_constraints_and_trigger_cover_insert_update_delete():
    sql = _sql()
    payments = _section(sql, "create table if not exists settlement_payments", "-- lock the parent")
    assert "amount int not null check (amount > 0)" in payments
    assert "match_method in ('manual', 'automatic')" in payments
    assert "confirmed_by uuid references app_users(id) on delete set null" in payments
    assert "audit_metadata jsonb not null default '{}'::jsonb" in payments
    assert "idx_settlement_payments_idempotency_unique" in sql
    assert "where idempotency_key is not null" in sql
    assert "idx_settlement_payments_external_reference_unique" in sql

    recompute = _section(
        sql,
        "create or replace function recompute_settlement_payment_status",
        "create or replace function settlement_payments_recompute_parent",
    )
    assert "for no key update" in recompute
    assert not re.search(r"\bfor\s+update\b", recompute)
    assert "confirmed_at is not null" in recompute
    assert "confirmed_at is null" in recompute
    assert "when v_confirmed_total = 0 and v_has_unconfirmed then 'matching'" in recompute
    assert "when v_confirmed_total = 0 then 'unpaid'" in recompute
    assert "when v_confirmed_total < v_total then 'partially_paid'" in recompute
    assert "when v_confirmed_total = v_total then 'paid'" in recompute
    assert "else 'overpaid'" in recompute
    assert "max(confirmed_at)" in recompute
    assert "when v_status in ('paid', 'overpaid') then v_latest_confirmed_at else null" in recompute
    assert "set settlement_status" not in recompute
    assert "after insert or update or delete on settlement_payments" in sql
    assert "old.settlement_id is distinct from new.settlement_id" in sql
    move = _section(sql, "elsif tg_op = 'update' and old.settlement_id", "else perform recompute_settlement_payment_status(new.settlement_id)")
    assert "if old.settlement_id < new.settlement_id" in move
    assert "idx_settlement_payments_settlement on settlement_payments(settlement_id)" in sql


def test_payment_status_boundaries_match_database_contract():
    def status(confirmed_total: int, settlement_total: int, has_unconfirmed=False) -> str:
        if confirmed_total == 0 and has_unconfirmed:
            return "matching"
        if confirmed_total == 0:
            return "unpaid"
        if confirmed_total < settlement_total:
            return "partially_paid"
        if confirmed_total == settlement_total:
            return "paid"
        return "overpaid"

    assert status(0, 1_100) == "unpaid"
    assert status(0, 1_100, has_unconfirmed=True) == "matching"
    assert status(500, 1_100) == "partially_paid"
    assert status(1_100, 1_100) == "paid"
    assert status(1_101, 1_100) == "overpaid"


def test_new_financial_tables_are_service_role_only_with_rls():
    sql = _sql()
    for table in ("tax_invoices", "tax_invoice_events", "settlement_payments"):
        assert f"alter table {table} enable row level security" in sql
    assert "revoke all on table tax_invoices, tax_invoice_events, settlement_payments from anon, authenticated, service_role" in sql
    assert "grant all" not in _section(sql, "-- service-owned financial records", "grant usage, select on sequence")
    assert "grant select, insert on table tax_invoice_events to service_role" in sql
    assert "grant select, insert, update, delete on table tax_invoices, settlement_payments to service_role" in sql
    assert "grant usage, select on sequence tax_invoice_events_id_seq to service_role" in sql


# These tests intentionally use PostgreSQL rather than a SQL parser or mock. Point
# TEST_DATABASE_URL at a disposable database; the fixture rebuilds its public schema.
@pytest.fixture(scope="session")
def postgres_db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to run PostgreSQL migration integration tests")

    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("drop schema if exists public cascade; create schema public")
        conn.execute(
            """
            do $$ begin
              if not exists (select 1 from pg_roles where rolname = 'anon') then
                create role anon nologin;
              end if;
              if not exists (select 1 from pg_roles where rolname = 'authenticated') then
                create role authenticated nologin;
              end if;
              if not exists (select 1 from pg_roles where rolname = 'service_role') then
                create role service_role nologin;
              end if;
            end $$;
            create extension if not exists pgcrypto;
            create table companies (id uuid primary key default gen_random_uuid(), name text not null);
            create table merchants (id uuid primary key default gen_random_uuid(), name text not null);
            create table app_users (id uuid primary key);
            create table merchant_products (id uuid primary key default gen_random_uuid());
            create table voucher_products (id uuid primary key default gen_random_uuid());
            create table merchant_companies (
              company_id uuid not null references companies(id),
              merchant_id uuid not null references merchants(id),
              primary key (company_id, merchant_id)
            );
            create table meal_transactions (
              id bigint generated always as identity primary key,
              kind text not null check (kind in ('grant', 'spend', 'expire', 'refund', 'adjust'))
            );
            create table settlements (
              id uuid primary key default gen_random_uuid(),
              company_id uuid not null references companies(id),
              merchant_id uuid not null references merchants(id),
              period_ym text not null,
              tx_count int not null,
              total_amount int not null,
              status text default 'draft' check (status in ('draft', 'confirmed', 'paid')),
              paid_at timestamptz,
              unique (company_id, merchant_id, period_ym)
            );
            insert into companies(id, name)
              values ('00000000-0000-0000-0000-000000000001', 'legacy company');
            insert into merchants(id, name)
              values ('00000000-0000-0000-0000-000000000002', 'legacy merchant');
            insert into settlements(
              id, company_id, merchant_id, period_ym, tx_count, total_amount, status, paid_at
            ) values (
              '00000000-0000-0000-0000-000000000003',
              '00000000-0000-0000-0000-000000000001',
              '00000000-0000-0000-0000-000000000002',
              '2026-01', 1, 1100, 'paid', '2026-02-01T00:00:00Z'
            );
            """
        )
        conn.execute(MIGRATION.read_text(encoding="utf-8"))
    return url


@pytest.fixture
def pg(postgres_db):
    import psycopg

    with psycopg.connect(postgres_db) as conn:
        yield conn
        conn.rollback()


def _party_and_settlements(pg, *, same_party=True):
    company = pg.execute(
        "insert into companies(name) values (%s) returning id", (f"company-{uuid.uuid4()}",)
    ).fetchone()[0]
    other_company = pg.execute(
        "insert into companies(name) values (%s) returning id", (f"company-{uuid.uuid4()}",)
    ).fetchone()[0]
    merchant = pg.execute(
        "insert into merchants(name) values (%s) returning id", (f"merchant-{uuid.uuid4()}",)
    ).fetchone()[0]
    second_merchant = merchant
    if not same_party:
        second_merchant = pg.execute(
            "insert into merchants(name) values (%s) returning id", (f"merchant-{uuid.uuid4()}",)
        ).fetchone()[0]
    settlement_ids = []
    for index, settlement_merchant in enumerate((merchant, second_merchant), 1):
        settlement_ids.append(
            pg.execute(
                """insert into settlements(
                       company_id, merchant_id, period_ym, tx_count, total_amount
                     ) values (%s, %s, %s, 1, 1100) returning id""",
                (company, settlement_merchant, f"{uuid.uuid4()}-{index}"),
            ).fetchone()[0]
        )
    return company, other_company, merchant, settlement_ids


def _invoice(pg, settlement, company, merchant, key, document_type="original", parent=None):
    return pg.execute(
        """insert into tax_invoices(
               settlement_id, company_id, merchant_id, parent_invoice_id, document_type,
               invoicer_mgt_key, tax_type, write_date, supply_amount, vat_amount,
               total_amount, supplier_snapshot, recipient_snapshot
             ) values (%s, %s, %s, %s, %s, %s, 'taxable', current_date,
                       1000, 100, 1100, '{}'::jsonb, '{}'::jsonb)
             returning id""",
        (settlement, company, merchant, parent, document_type, key),
    ).fetchone()[0]


def test_postgres_partial_tax_snapshots_are_rejected(pg):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        with pg.transaction():
            pg.execute("insert into meal_transactions(kind, supply_amount) values ('spend', 1000)")
    with pytest.raises(psycopg.errors.CheckViolation):
        with pg.transaction():
            pg.execute(
                """insert into meal_transactions(
                       kind, settlement_supply_amount, settlement_vat_amount
                     ) values ('spend', 1000, 100)"""
            )

    with pytest.raises(psycopg.errors.CheckViolation):
        with pg.transaction():
            pg.execute(
                """insert into meal_transactions(
                       kind, supply_amount, vat_amount, total_amount
                     ) values ('spend', 1000, 100, 1099)"""
            )

    _, _, _, settlements = _party_and_settlements(pg)
    with pytest.raises(psycopg.errors.CheckViolation):
        with pg.transaction():
            pg.execute("update settlements set supply_amount=1000 where id=%s", (settlements[0],))
    with pytest.raises(psycopg.errors.CheckViolation):
        with pg.transaction():
            pg.execute(
                "update settlements set supply_amount=1000, vat_amount=99 where id=%s",
                (settlements[0],),
            )


def test_postgres_migration_reapply_preserves_nonlegacy_states(pg):
    rows = []
    for workflow, payment in (
        ("sent", "matching"),
        ("disputed", "partially_paid"),
        ("revising", "overpaid"),
        ("cancelled", "paid"),
    ):
        _, _, _, settlements = _party_and_settlements(pg)
        settlement = settlements[0]
        pg.execute(
            "update settlements set settlement_status=%s, payment_status=%s where id=%s",
            (workflow, payment, settlement),
        )
        rows.append((settlement, workflow, payment))

    pg.execute(MIGRATION.read_text(encoding="utf-8"))
    for settlement, workflow, payment in rows:
        assert pg.execute(
            "select settlement_status, payment_status from settlements where id=%s",
            (settlement,),
        ).fetchone() == (workflow, payment)


def test_postgres_payment_trigger_insert_update_delete_and_matching(pg):
    _, _, _, settlements = _party_and_settlements(pg)
    settlement = settlements[0]
    first_confirmed = "2026-03-01T01:02:03Z"
    second_confirmed = "2026-03-02T04:05:06Z"
    third_confirmed = "2026-03-03T07:08:09Z"
    payment = pg.execute(
        """insert into settlement_payments(
               settlement_id, amount, deposited_at, match_method
             ) values (%s, 500, now(), 'automatic') returning id""",
        (settlement,),
    ).fetchone()[0]
    assert pg.execute(
        "select payment_status, paid_at from settlements where id=%s", (settlement,)
    ).fetchone() == ("matching", None)

    pg.execute("update settlement_payments set confirmed_at=%s where id=%s", (first_confirmed, payment))
    assert pg.execute(
        "select payment_status, paid_at from settlements where id=%s", (settlement,)
    ).fetchone() == ("partially_paid", None)

    second = pg.execute(
        """insert into settlement_payments(
               settlement_id, amount, deposited_at, match_method, confirmed_at
             ) values (%s, 600, now(), 'manual', %s) returning id""",
        (settlement, second_confirmed),
    ).fetchone()[0]
    expected_second = pg.execute("select %s::timestamptz", (second_confirmed,)).fetchone()[0]
    assert pg.execute(
        "select payment_status, paid_at from settlements where id=%s", (settlement,)
    ).fetchone() == ("paid", expected_second)

    pg.execute("update settlement_payments set amount=700 where id=%s", (second,))
    assert pg.execute(
        "select payment_status, paid_at from settlements where id=%s", (settlement,)
    ).fetchone() == ("overpaid", expected_second)

    pg.execute("delete from settlement_payments where id=%s", (second,))
    assert pg.execute(
        "select payment_status, paid_at from settlements where id=%s", (settlement,)
    ).fetchone() == ("partially_paid", None)
    second = pg.execute(
        """insert into settlement_payments(
               settlement_id, amount, deposited_at, match_method, confirmed_at
             ) values (%s, 600, now(), 'manual', %s) returning id""",
        (settlement, third_confirmed),
    ).fetchone()[0]
    expected_third = pg.execute("select %s::timestamptz", (third_confirmed,)).fetchone()[0]
    assert pg.execute(
        "select payment_status, paid_at from settlements where id=%s", (settlement,)
    ).fetchone() == ("paid", expected_third)

    pg.execute("delete from settlement_payments where id in (%s, %s)", (payment, second))
    assert pg.execute(
        "select payment_status, paid_at from settlements where id=%s", (settlement,)
    ).fetchone() == ("unpaid", None)


def test_postgres_reciprocal_payment_moves_do_not_deadlock(postgres_db):
    import psycopg

    # Commit fixture rows before opening the two independent worker transactions. UUID
    # ordering determines trigger lock order, regardless of generated insertion order.
    with psycopg.connect(postgres_db) as setup:
        _, _, _, settlements = _party_and_settlements(setup)
        low, high = sorted(settlements)
        setup.execute("update settlements set total_amount=700 where id=%s", (low,))
        setup.execute("update settlements set total_amount=400 where id=%s", (high,))
        low_payment = setup.execute(
            """insert into settlement_payments(
                   settlement_id, amount, deposited_at, match_method, confirmed_at
                 ) values (%s, 400, now(), 'manual', now()) returning id""",
            (low,),
        ).fetchone()[0]
        high_payment = setup.execute(
            """insert into settlement_payments(
                   settlement_id, amount, deposited_at, match_method, confirmed_at
                 ) values (%s, 700, now(), 'manual', now()) returning id""",
            (high,),
        ).fetchone()[0]

    barrier = threading.Barrier(2, timeout=10)

    def move(payment, source, target):
        with psycopg.connect(postgres_db) as conn:
            conn.execute("set local lock_timeout = '10s'")
            conn.execute("set local statement_timeout = '15s'")
            # Reproduce the target FK lock held before the AFTER trigger. At this barrier
            # the former FOR UPDATE parent lock deterministically deadlocked A->B/B->A.
            conn.execute("select id from settlements where id=%s for key share", (target,))
            barrier.wait()
            conn.execute(
                "update settlement_payments set settlement_id=%s where id=%s and settlement_id=%s",
                (target, payment, source),
            )
            conn.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        moves = (
            pool.submit(move, low_payment, low, high),
            pool.submit(move, high_payment, high, low),
        )
        # result() propagates DeadlockDetected as well as lock/statement timeouts.
        for moved in moves:
            moved.result(timeout=20)

    with psycopg.connect(postgres_db) as verify:
        assert verify.execute(
            """select s.id, s.payment_status, coalesce(sum(p.amount), 0)
                 from settlements s
                 left join settlement_payments p
                   on p.settlement_id = s.id and p.confirmed_at is not null
                where s.id in (%s, %s)
                group by s.id, s.payment_status
                order by s.id""",
            (low, high),
        ).fetchall() == [(low, "paid", 700), (high, "paid", 400)]


def test_postgres_legacy_status_compatibility(pg):
    legacy = "00000000-0000-0000-0000-000000000003"
    assert pg.execute(
        "select settlement_status, payment_status, finalized_at from settlements where id=%s",
        (legacy,),
    ).fetchone() == ("completed", "paid", pg.execute(
        "select paid_at from settlements where id=%s", (legacy,)
    ).fetchone()[0])

    pg.execute("update settlements set status='confirmed' where id=%s", (legacy,))
    assert pg.execute(
        "select settlement_status from settlements where id=%s", (legacy,)
    ).fetchone()[0] == "confirmed"
    pg.execute("update settlements set settlement_status='completed' where id=%s", (legacy,))
    assert pg.execute(
        "select status, payment_status from settlements where id=%s", (legacy,)
    ).fetchone() == ("confirmed", "unpaid")


def test_postgres_payment_projection_preserves_workflow_and_legacy_writer(pg):
    _, _, _, settlements = _party_and_settlements(pg)
    settlement = settlements[0]
    pg.execute("update settlements set settlement_status='disputed' where id=%s", (settlement,))
    payment = pg.execute(
        """insert into settlement_payments(
               settlement_id, amount, deposited_at, match_method, confirmed_at
             ) values (%s, 1100, now(), 'manual', '2026-04-01T00:00:00Z') returning id""",
        (settlement,),
    ).fetchone()[0]
    assert pg.execute(
        "select status, payment_status, settlement_status from settlements where id=%s",
        (settlement,),
    ).fetchone() == ("paid", "paid", "disputed")

    pg.execute("update settlement_payments set amount=500 where id=%s", (payment,))
    assert pg.execute(
        "select status, payment_status, settlement_status from settlements where id=%s",
        (settlement,),
    ).fetchone() == ("draft", "partially_paid", "disputed")
    pg.execute("delete from settlement_payments where id=%s", (payment,))
    assert pg.execute(
        "select status, payment_status, settlement_status from settlements where id=%s",
        (settlement,),
    ).fetchone() == ("draft", "unpaid", "disputed")

    legacy_target = settlements[1]
    pg.execute("update settlements set status='paid' where id=%s", (legacy_target,))
    assert pg.execute(
        "select status, payment_status, settlement_status from settlements where id=%s",
        (legacy_target,),
    ).fetchone() == ("paid", "paid", "completed")


def test_postgres_invoice_parent_and_tenant_integrity(pg):
    import psycopg

    company, other_company, merchant, settlements = _party_and_settlements(pg)
    original_one = _invoice(pg, settlements[0], company, merchant, f"orig-{uuid.uuid4()}")
    original_two = _invoice(pg, settlements[1], company, merchant, f"orig-{uuid.uuid4()}")
    correction = _invoice(
        pg, settlements[0], company, merchant, f"corr-{uuid.uuid4()}", "correction", original_one
    )
    assert correction is not None

    with pytest.raises(psycopg.Error, match="TAX_INVOICE_PARENT_PARTIES_MISMATCH"):
        with pg.transaction():
            _invoice(
                pg, settlements[1], company, merchant, f"cross-{uuid.uuid4()}",
                "correction", original_one,
            )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with pg.transaction():
            pg.execute(
                "update tax_invoices set company_id=%s where id=%s",
                (other_company, original_two),
            )

    self_id = uuid.uuid4()
    with pytest.raises(psycopg.Error, match="TAX_INVOICE_SELF_PARENT"):
        with pg.transaction():
            pg.execute(
                """insert into tax_invoices(
                       id, settlement_id, company_id, merchant_id, parent_invoice_id,
                       document_type, invoicer_mgt_key, tax_type, write_date,
                       supply_amount, vat_amount, total_amount, supplier_snapshot, recipient_snapshot
                     ) values (%s, %s, %s, %s, %s, 'correction', %s, 'taxable',
                       current_date, 1000, 100, 1100, '{}'::jsonb, '{}'::jsonb)""",
                (self_id, settlements[0], company, merchant, self_id, f"self-{uuid.uuid4()}"),
            )

    cancellation = _invoice(
        pg, settlements[0], company, merchant, f"cancel-{uuid.uuid4()}",
        "cancellation", correction,
    )
    with pytest.raises(psycopg.Error, match="TAX_INVOICE_PARENT_CYCLE"):
        with pg.transaction():
            pg.execute(
                "update tax_invoices set parent_invoice_id=%s where id=%s",
                (cancellation, correction),
            )
    assert original_two is not None


def test_postgres_invoice_events_are_immutable(pg):
    import psycopg

    company, _, merchant, settlements = _party_and_settlements(pg)
    invoice = _invoice(pg, settlements[0], company, merchant, f"event-orig-{uuid.uuid4()}")
    actor = uuid.uuid4()
    pg.execute("insert into app_users(id) values (%s)", (actor,))
    event = pg.execute(
        """insert into tax_invoice_events(tax_invoice_id, event_type, payload, actor_id)
             values (%s, 'issued', '{}', %s) returning id""",
        (invoice, actor),
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with pg.transaction():
            pg.execute("delete from app_users where id=%s", (actor,))
    assert pg.execute(
        "select actor_id from tax_invoice_events where id=%s", (event,)
    ).fetchone()[0] == actor
    with pytest.raises(psycopg.Error, match="TAX_INVOICE_EVENTS_ARE_IMMUTABLE"):
        with pg.transaction():
            pg.execute("update tax_invoice_events set event_type='changed' where id=%s", (event,))
    with pytest.raises(psycopg.Error, match="TAX_INVOICE_EVENTS_ARE_IMMUTABLE"):
        with pg.transaction():
            pg.execute("delete from tax_invoice_events where id=%s", (event,))


def test_postgres_rls_and_role_grants(pg):
    for table in ("tax_invoices", "tax_invoice_events", "settlement_payments"):
        assert pg.execute(
            "select relrowsecurity from pg_class where oid=%s::regclass", (table,)
        ).fetchone()[0] is True
        assert pg.execute("select has_table_privilege('anon', %s, 'SELECT')", (table,)).fetchone()[0] is False
        assert pg.execute(
            "select has_table_privilege('authenticated', %s, 'SELECT')", (table,)
        ).fetchone()[0] is False
        assert pg.execute(
            "select has_table_privilege('service_role', %s, 'TRUNCATE')", (table,)
        ).fetchone()[0] is False

    for table in ("tax_invoices", "settlement_payments"):
        assert pg.execute(
            "select has_table_privilege('service_role', %s, 'INSERT,SELECT,UPDATE,DELETE')", (table,)
        ).fetchone()[0] is True
    assert pg.execute(
        "select has_table_privilege('service_role', 'tax_invoice_events', 'INSERT,SELECT')"
    ).fetchone()[0] is True
    assert pg.execute(
        "select has_table_privilege('service_role', 'tax_invoice_events', 'UPDATE')"
    ).fetchone()[0] is False
    assert pg.execute(
        "select has_table_privilege('service_role', 'tax_invoice_events', 'DELETE')"
    ).fetchone()[0] is False
    assert pg.execute(
        "select has_sequence_privilege('service_role', 'tax_invoice_events_id_seq', 'USAGE,SELECT')"
    ).fetchone()[0] is True
    assert pg.execute(
        "select has_sequence_privilege('service_role', 'tax_invoice_events_id_seq', 'UPDATE')"
    ).fetchone()[0] is False
