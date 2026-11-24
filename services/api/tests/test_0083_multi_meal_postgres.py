"""Migration 0083 on PostgreSQL 16: daily meal-count limit and several meals in one scan."""
import uuid

import pytest

from tests.test_0073_exposure_generator_postgres import db0073, pg  # noqa: F401  (fixtures)
from tests.test_0075_meal_pay_limits_postgres import _setup
from tests.test_0080_subsidy_purchase_billing_postgres import _buy, _scene
from tests.test_settlement_postgres import parties, settlement_db  # noqa: F401  (fixture)


def _pay_many(pg, employee, company, merchant, quantity, key=None):
    return pg.execute(
        "select public.process_meal_pay_many(%s,%s,%s,8000,%s,'중식','{}'::jsonb,%s,%s)",
        (employee, company, merchant, uuid.uuid4().hex[:10], key or str(uuid.uuid4()), quantity)).fetchone()[0]


def _ledger_rows(pg, employee):
    return pg.execute("select count(*) from meal_transactions where user_id=%s and pay_type='ledger' and kind='spend'",
                      (employee,)).fetchone()[0]


def _refused(pg, match, call):
    pg.execute("savepoint s")
    with pytest.raises(Exception, match=match):
        call()
    pg.execute("rollback to savepoint s")


def test_three_ledger_meals_in_one_scan_are_three_rows_and_replay_adds_none(pg):
    company, merchant, employee = _setup(pg, monthly=100000)
    key = str(uuid.uuid4())
    out = _pay_many(pg, employee, company, merchant, 3, key)
    assert (out["quantity"], out["duplicate"], out["amount"], out["unit_amount"], len(out["items"])) == (3, False, 24000, 8000, 3)
    assert _ledger_rows(pg, employee) == 3
    keys = [r[0] for r in pg.execute("select idempotency_key from meal_transactions where user_id=%s order by id", (employee,)).fetchall()]
    assert keys == [key, f"{key}#2", f"{key}#3"]
    assert len({item["id"] for item in out["items"]}) == 3
    # The same QR read again: nothing new, flagged as a duplicate.
    again = _pay_many(pg, employee, company, merchant, 3, key)
    assert (again["duplicate"], again["quantity"]) == (True, 3) and _ledger_rows(pg, employee) == 3
    # The settlement sees three ordinary meals.
    assert pg.execute("select tx_count,total_amount from settlements where company_id=%s and merchant_id=%s and not is_demo",
                      (company, merchant)).fetchone() == (3, 24000)


def test_all_or_nothing_when_the_monthly_limit_stops_the_third_meal(pg):
    company, merchant, employee = _setup(pg, monthly=20000)          # two 8,000 meals fit, three do not
    _refused(pg, "MONTHLY_LIMIT", lambda: _pay_many(pg, employee, company, merchant, 3))
    assert _ledger_rows(pg, employee) == 0                           # the first two were undone
    assert _pay_many(pg, employee, company, merchant, 2)["quantity"] == 2


def test_daily_count_limit_counts_every_meal_and_frees_a_cancelled_one(pg):
    company, merchant, employee = _setup(pg, monthly=1000000)
    pg.execute("insert into meal_policies(company_id,daily_count_limit,weekend_allowed) values(%s,2,true)", (company,))
    _refused(pg, "DAILY_COUNT_LIMIT", lambda: _pay_many(pg, employee, company, merchant, 3))
    assert _ledger_rows(pg, employee) == 0
    key = str(uuid.uuid4())
    first = _pay_many(pg, employee, company, merchant, 1, key)
    assert _pay_many(pg, employee, company, merchant, 1)["quantity"] == 1
    _refused(pg, "DAILY_COUNT_LIMIT", lambda: _pay_many(pg, employee, company, merchant, 1))
    # A replay of an earlier scan is never refused by the limit.
    assert _pay_many(pg, employee, company, merchant, 1, key)["duplicate"] is True
    # The restaurant cancels one meal (reversal row, same timestamp): one turn is free again.
    pg.execute("""insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,tx_code,meal_window,
                    tax_type,supply_amount,vat_amount,total_amount,settlement_tax_type,settlement_supply_amount,
                    settlement_vat_amount,settlement_total_amount,created_at,original_transaction_id)
                  select user_id,company_id,merchant_id,abs(amount),'cancel','ledger','CX-'||id,meal_window,
                    tax_type,supply_amount,vat_amount,total_amount,settlement_tax_type,settlement_supply_amount,
                    settlement_vat_amount,settlement_total_amount,created_at,id from meal_transactions where id=%s""", (first["id"],))
    assert _pay_many(pg, employee, company, merchant, 1)["duplicate"] is False


def test_no_count_limit_means_no_count_check_and_bad_quantities_are_refused(pg):
    company, merchant, employee = _setup(pg, monthly=1000000)
    assert _pay_many(pg, employee, company, merchant, 5)["quantity"] == 5
    for quantity in (0, 11, None):
        _refused(pg, "INVALID_QUANTITY", lambda q=quantity: _pay_many(pg, employee, company, merchant, q))
    # Another company's limit does not apply to this employee.
    other, other_merchant, other_employee = _setup(pg, monthly=1000000)
    pg.execute("insert into meal_policies(company_id,daily_count_limit,weekend_allowed) values(%s,1,true)", (other,))
    assert _pay_many(pg, employee, company, merchant, 2)["quantity"] == 2


def _voucher_order(pg, user, merchant, count, amount=8000):
    suffix = uuid.uuid4().hex[:12]
    product = pg.execute(
        """insert into voucher_products(merchant_id,name,voucher_count,bonus_count,unit_price,tax_type)
           values (%s,'p',%s,0,%s,'taxable') returning id""", (merchant, count, amount)).fetchone()[0]
    order = pg.execute(
        """insert into payment_orders(
             order_id,checkout_token,user_id,merchant_id,merchant_name,product_name,amount,status,pay_type,
             voucher_product_id,voucher_count,voucher_purchase_price,fulfilled_at,paid_voucher_count,
             bonus_voucher_count,provider_payment_key,payment_method,gross_amount,requested_point_amount
           ) values (%s,%s,%s,%s,'m','p',%s,'done','voucher',%s,%s,%s,now(),%s,0,%s,'CARD',%s,0) returning id""",
        (f"o-{suffix}", f"t-{suffix}", user, merchant, amount * count, product, count, amount, count,
         f"trx-{suffix}", amount * count)).fetchone()[0]
    for index in range(1, count + 1):
        pg.execute(
            """insert into vouchers(user_id,merchant_id,product_id,order_id,issue_index,purchase_price,
                                    purchase_price_won,status,pg_transaction_id,tax_type)
               values (%s,%s,%s,%s,%s,%s,%s,'unused',%s,'taxable')""",
            (user, merchant, product, order, index, amount, amount, f"trx-{suffix}"))


def test_three_vouchers_in_one_scan_and_never_a_partial_use(pg):
    _, merchant, employee = _setup(pg)
    _voucher_order(pg, employee, merchant, 4)
    key = str(uuid.uuid4())
    out = pg.execute("select public.consume_vouchers_many(%s,%s,%s,3)", (employee, merchant, key)).fetchone()[0]
    assert (out["quantity"], out["duplicate"], out["remaining"], out["total_amount"], len(out["items"])) == (3, False, 1, 24000, 3)
    assert pg.execute("select count(*) from vouchers where user_id=%s and status='used'", (employee,)).fetchone()[0] == 3
    again = pg.execute("select public.consume_vouchers_many(%s,%s,%s,3)", (employee, merchant, key)).fetchone()[0]
    assert (again["duplicate"], again["remaining"]) == (True, 1)
    # One voucher left, two asked for: nothing is used.
    _refused(pg, "NO_VOUCHER", lambda: pg.execute("select public.consume_vouchers_many(%s,%s,%s,2)",
                                                   (employee, merchant, str(uuid.uuid4()))))
    assert pg.execute("select count(*) from vouchers where user_id=%s and status='unused'", (employee,)).fetchone()[0] == 1
    assert pg.execute("select count(*) from meal_transactions where user_id=%s and pay_type='voucher'", (employee,)).fetchone()[0] == 3


def test_two_subsidized_vouchers_in_one_scan(pg):
    s = _scene(pg)
    _buy(pg, s, count=3)
    key = str(uuid.uuid4())
    out = pg.execute("select public.consume_subsidized_vouchers_many(%s,%s,%s,%s,2)",
                     (s["employee"], s["company"], s["merchant"], key)).fetchone()[0]
    assert (out["quantity"], out["duplicate"], out["remaining"], out["total_amount"]) == (2, False, 1, 16000)
    _refused(pg, "NO_VOUCHER", lambda: pg.execute(
        "select public.consume_subsidized_vouchers_many(%s,%s,%s,%s,2)",
        (s["employee"], s["company"], s["merchant"], str(uuid.uuid4()))))
    assert pg.execute("select count(*) from vouchers where user_id=%s and status='unused'", (s["employee"],)).fetchone()[0] == 1
    # Billing is unchanged by the quantity: three purchases billed, the meals bill nothing (0080).
    assert pg.execute("""select total_amount from settlements where company_id=%s and merchant_id=%s
                         and period_ym='2031-03' and not is_demo""", (s["company"], s["merchant"])).fetchone()[0] == 3000


def test_functions_are_service_role_only(pg):
    rows = pg.execute("""select p.proname, has_function_privilege('anon', p.oid, 'execute'),
                                has_function_privilege('authenticated', p.oid, 'execute'),
                                has_function_privilege('service_role', p.oid, 'execute')
                         from pg_proc p join pg_namespace n on n.oid=p.pronamespace
                         where n.nspname='public' and p.proname in
                           ('process_meal_pay_many','consume_vouchers_many','consume_subsidized_vouchers_many')
                         order by 1""").fetchall()
    assert rows == [("consume_subsidized_vouchers_many", False, False, True), ("consume_vouchers_many", False, False, True),
                    ("process_meal_pay_many", False, False, True)]
