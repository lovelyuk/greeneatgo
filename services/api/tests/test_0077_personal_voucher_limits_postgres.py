"""Migration 0077: meals paid with a personal voucher stay outside company limits (PostgreSQL 16)."""

import uuid

import pytest

from tests.test_0073_exposure_generator_postgres import db0073  # noqa: F401  (fixture)
from tests.test_0075_meal_pay_limits_postgres import _pay, _setup
from tests.test_settlement_postgres import settlement_db  # noqa: F401  (fixture)


def _personal_voucher_meal(conn, employee, merchant, amount=8000):
    """The employee buys one ordinary voucher with their own money and eats with it.

    Uses the real consume_voucher RPC, so this also proves an employee account
    can hold and spend an ordinary (non-company) voucher."""
    suffix = uuid.uuid4().hex[:12]
    product = conn.execute(
        """insert into voucher_products(merchant_id,name,voucher_count,bonus_count,unit_price,tax_type)
           values (%s,'p',1,0,%s,'taxable') returning id""", (merchant, amount)).fetchone()[0]
    order = conn.execute(
        """insert into payment_orders(
             order_id,checkout_token,user_id,merchant_id,merchant_name,product_name,amount,status,pay_type,
             voucher_product_id,voucher_count,voucher_purchase_price,fulfilled_at,paid_voucher_count,
             bonus_voucher_count,provider_payment_key,payment_method,gross_amount,requested_point_amount
           ) values (%s,%s,%s,%s,'m','p',%s,'done','voucher',%s,1,%s,now(),1,0,%s,'CARD',%s,0) returning id""",
        (f"o-{suffix}", f"t-{suffix}", employee, merchant, amount, product, amount, f"trx-{suffix}", amount)).fetchone()[0]
    conn.execute(
        """insert into vouchers(user_id,merchant_id,product_id,order_id,issue_index,purchase_price,
                                purchase_price_won,status,pg_transaction_id,tax_type)
           values (%s,%s,%s,%s,1,%s,%s,'unused',%s,'taxable')""",
        (employee, merchant, product, order, amount, amount, f"trx-{suffix}"))
    used = conn.execute("select public.consume_voucher(%s,%s,%s)", (employee, merchant, str(uuid.uuid4()))).fetchone()[0]
    assert used["duplicate"] is False and used["remaining"] == 0
    row = conn.execute("select company_id,pay_type,amount from meal_transactions where id=%s", (used["id"],)).fetchone()
    assert row == (None, "voucher", -amount)


def test_personal_voucher_meals_do_not_use_up_the_company_limits(db0073):
    import psycopg
    with psycopg.connect(db0073) as conn:
        # Monthly limit 10,000: one 8,000 company meal fits, a second does not.
        company, merchant, employee = _setup(conn, monthly=10000)
        _personal_voucher_meal(conn, employee, merchant)
        _personal_voucher_meal(conn, employee, merchant)
        assert _pay(conn, employee, company, merchant)["duplicate"] is False
        conn.execute("savepoint s")
        with pytest.raises(psycopg.errors.RaiseException, match="MONTHLY_LIMIT"):
            _pay(conn, employee, company, merchant)
        conn.execute("rollback to savepoint s")

        # Daily limit 10,000 behaves the same way.
        company2, merchant2, employee2 = _setup(conn, monthly=100000, daily=10000)
        _personal_voucher_meal(conn, employee2, merchant2)
        assert _pay(conn, employee2, company2, merchant2)["duplicate"] is False
        conn.execute("savepoint s")
        with pytest.raises(psycopg.errors.RaiseException, match="DAILY_LIMIT"):
            _pay(conn, employee2, company2, merchant2)
        conn.execute("rollback to savepoint s")
        conn.rollback()
