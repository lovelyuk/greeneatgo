"""Migration 0073 on a disposable PostgreSQL 16 (TEST_DATABASE_URL, same as
test_settlement_postgres). Applies every infra migration, then supabase/migrations."""

import uuid
from pathlib import Path

import pytest

from tests.test_settlement_postgres import parties, settlement_db  # noqa: F401  (fixture)

SUPABASE = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
M0073 = SUPABASE / "0073_close_merchant_exposure_and_generator_scope.sql"


def test_0073_contract():
    sql = M0073.read_text(encoding="utf-8").lower()
    assert "drop policy if exists merchants_authenticated_read on public.merchants" in sql
    assert "revoke all on table public.merchants, public.company_merchants from anon, authenticated" in sql
    assert sql.count("generated_period_has_real_transactions") == 3


@pytest.fixture(scope="module")
def db0073(settlement_db):
    import psycopg
    with psycopg.connect(settlement_db, autocommit=True) as conn:
        for migration in sorted(SUPABASE.glob("*.sql")):
            conn.execute(migration.read_text(encoding="utf-8"))
    return settlement_db


@pytest.fixture
def pg(db0073):
    import psycopg
    with psycopg.connect(db0073) as conn:
        yield conn
        conn.rollback()


def test_client_roles_lose_merchant_and_legacy_surfaces(pg):
    q = lambda sql: pg.execute(sql).fetchone()[0]
    for role in ("anon", "authenticated"):
        assert q(f"select has_table_privilege('{role}','public.merchants','select')") is False
        assert q(f"select has_table_privilege('{role}','public.company_merchants','select')") is False
        assert q(f"select has_table_privilege('{role}','public.meal_balances','select')") is False
        assert q(f"select has_function_privilege('{role}','public.process_meal_pay(uuid,uuid,uuid,integer,text,text,jsonb,text)','execute')") is False
    assert q("select count(*) from pg_policies where tablename in ('merchants','company_merchants')") == 0


def _setup(pg):
    company, _, merchant, _, company_actor, _, merchant_actor, _ = parties(pg)
    pg.execute("""insert into merchant_companies(merchant_id,company_id,status,created_by,unit_price,tax_type)
                  values(%s,%s,'active',%s,8000,'taxable')""", (merchant, company, merchant_actor))
    employee = pg.execute("insert into app_users(id,company_id,display_name,role,status) values(gen_random_uuid(),%s,'employee','employee','active') returning id",
                          (company,)).fetchone()[0]
    return company, merchant, merchant_actor, employee


def _real_tx(pg, employee, company, merchant, at):
    return pg.execute("""insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,
      settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
      values(%s,%s,%s,-1100,'spend','ledger','taxable',1000,100,1100,%s) returning id""",
                      (employee, company, merchant, at)).fetchone()[0]


def test_generator_refuses_months_with_real_transactions(pg):
    import psycopg
    company, merchant, actor, employee = _setup(pg)
    _real_tx(pg, employee, company, merchant, "2026-03-10 03:00:00+00")
    pg.execute("savepoint s")
    with pytest.raises(psycopg.errors.RaiseException, match="GENERATED_PERIOD_HAS_REAL_TRANSACTIONS"):
        pg.execute("select public.generate_company_month_transactions(%s,%s,%s,'2026-03')", (actor, merchant, company))
    pg.execute("rollback to savepoint s")

    # A purely generated month still works end to end (create -> reset).
    pg.execute("select public.generate_company_month_transactions(%s,%s,%s,'2026-04')", (actor, merchant, company))
    run = pg.execute("select id,settlement_id from generated_transaction_runs where merchant_id=%s and period_ym='2026-04'", (merchant,)).fetchone()
    assert run[1] is not None

    # A real transaction appearing in that month blocks confirm and reset.
    real = _real_tx(pg, employee, company, merchant, "2026-04-15 03:00:00+00")
    for call in ("select public.generated_transactions_confirm(%s,%s,%s,'2026-04')",
                 "select public.reset_generated_company_month_state(%s,%s,%s,'2026-04','k-1')"):
        args = (actor, merchant, company)
        pg.execute("savepoint s")
        with pytest.raises(psycopg.errors.RaiseException, match="GENERATED_PERIOD_HAS_REAL_TRANSACTIONS"):
            pg.execute(call, args)
        pg.execute("rollback to savepoint s")

    pg.execute("delete from meal_transactions where id=%s", (real,))
    result = pg.execute("select public.reset_generated_company_month_state(%s,%s,%s,'2026-04',%s)",
                        (actor, merchant, company, str(uuid.uuid4()))).fetchone()[0]
    assert result["reset"] is True
    assert pg.execute("select count(*) from generated_transaction_runs where merchant_id=%s", (merchant,)).fetchone()[0] == 0
