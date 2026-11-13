"""Migration 0075: meal pay limits re-checked under the per-user lock (PostgreSQL 16)."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from tests.test_0073_exposure_generator_postgres import db0073  # noqa: F401  (fixture)
from tests.test_settlement_postgres import parties, settlement_db  # noqa: F401  (fixture)


def _setup(conn, monthly=10000, daily=None):
    company, _, merchant, _, _, _, merchant_actor, _ = parties(conn)
    conn.execute("update companies set status='active' where id=%s", (company,))
    conn.execute("""insert into merchant_companies(merchant_id,company_id,status,created_by,unit_price,tax_type)
                    values(%s,%s,'active',%s,8000,'taxable')""", (merchant, company, merchant_actor))
    if daily is not None:
        conn.execute("insert into meal_policies(company_id,daily_limit) values(%s,%s)", (company, daily))
    employee = conn.execute("""insert into app_users(id,company_id,display_name,role,status,monthly_limit)
                               values(gen_random_uuid(),%s,'e','employee','active',%s) returning id""",
                            (company, monthly)).fetchone()[0]
    return company, merchant, employee


def _pay(conn, employee, company, merchant):
    return conn.execute("""select public.process_meal_pay(p_user_id=>%s,p_company_id=>%s,p_merchant_id=>%s,p_amount=>8000,
                                p_tx_code=>%s,p_meal_window=>'중식',p_flags=>'{}'::jsonb,p_idempotency_key=>%s,
                                p_product_id=>null,p_product_name=>null,p_product_price=>null)""",
                        (employee, company, merchant, uuid.uuid4().hex[:10], str(uuid.uuid4()))).fetchone()[0]


def test_monthly_daily_limit_and_membership_are_enforced_in_rpc(db0073):
    import psycopg
    with psycopg.connect(db0073) as conn:
        company, merchant, employee = _setup(conn, monthly=10000)
        assert _pay(conn, employee, company, merchant)["duplicate"] is False
        conn.execute("savepoint s")
        with pytest.raises(psycopg.errors.RaiseException, match="MONTHLY_LIMIT"):
            _pay(conn, employee, company, merchant)
        conn.execute("rollback to savepoint s")

        company2, merchant2, employee2 = _setup(conn, monthly=100000, daily=10000)
        _pay(conn, employee2, company2, merchant2)
        conn.execute("savepoint s")
        with pytest.raises(psycopg.errors.RaiseException, match="DAILY_LIMIT"):
            _pay(conn, employee2, company2, merchant2)
        conn.execute("rollback to savepoint s")

        conn.execute("savepoint s")
        with pytest.raises(psycopg.errors.RaiseException, match="NOT_COMPANY_MEMBER"):
            _pay(conn, employee2, company, merchant)  # employee of another company
        conn.execute("rollback to savepoint s")
        conn.rollback()


def test_concurrent_payments_cannot_exceed_monthly_limit(db0073):
    import psycopg
    with psycopg.connect(db0073, autocommit=True) as setup:
        company, merchant, employee = _setup(setup, monthly=10000)
    barrier = Barrier(4)

    def attempt(_):
        with psycopg.connect(db0073, autocommit=True) as conn:
            barrier.wait()
            try:
                _pay(conn, employee, company, merchant)
                return "ok"
            except psycopg.errors.RaiseException as exc:
                return "limit" if "MONTHLY_LIMIT" in str(exc) else str(exc)

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert sorted(results) == ["limit", "limit", "limit", "ok"]
