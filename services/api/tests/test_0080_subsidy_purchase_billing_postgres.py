"""Migration 0080 on PostgreSQL 16: a company subsidy is billed when the voucher is bought."""
import uuid

import pytest

from tests.test_0073_exposure_generator_postgres import db0073, pg  # noqa: F401  (fixtures)
from tests.test_settlement_postgres import parties, settlement_db  # noqa: F401  (fixture)

PRICE, EMPLOYEE, SUBSIDY = 8000, 7000, 1000


def _scene(pg, subsidy=True):
    company, _, merchant, _, company_actor, _, actor, _ = parties(pg)
    pg.execute("update companies set status='active' where id=%s", (company,))
    pg.execute("""insert into merchant_companies(merchant_id,company_id,status,created_by,subsidy_enabled,
                                                 unit_price,company_subsidy_amount,restaurant_subsidy_amount)
                  values(%s,%s,'active',%s,%s,%s,%s,0)""", (merchant, company, actor, subsidy, PRICE, SUBSIDY if subsidy else 0))
    employee = pg.execute(
        """insert into app_users(id,company_id,display_name,role,status,monthly_limit)
           values(gen_random_uuid(),%s,'직원','employee','active',200000) returning id""", (company,)).fetchone()[0]
    return dict(company=company, merchant=merchant, actor=actor, company_actor=company_actor, employee=employee)


def _buy(pg, s, when="2031-03-10 03:00:00+00", count=1, bonus=0, subsidy=SUBSIDY, restaurant=0):
    """A paid subsidized order, fulfilled by the real fulfill_subsidized_order RPC (which issues the vouchers)."""
    suffix = uuid.uuid4().hex[:12]
    product = pg.execute(
        """insert into voucher_products(merchant_id,name,voucher_count,bonus_count,unit_price,tax_type)
           values (%s,'p',%s,%s,%s,'taxable') returning id""", (s["merchant"], count, bonus, PRICE)).fetchone()[0]
    order = pg.execute(
        """insert into payment_orders(
             order_id,checkout_token,user_id,merchant_id,merchant_name,product_name,amount,status,pay_type,
             company_id,voucher_product_id,voucher_count,voucher_purchase_price,paid_voucher_count,bonus_voucher_count,
             gross_amount,requested_point_amount,checkout_started_at,
             company_subsidy_amount,restaurant_subsidy_amount,total_employee_burden
           ) values (%s,%s,%s,%s,'m','p',%s,'ready','subsidized',%s,%s,%s,%s,%s,%s,%s,0,now(),%s,%s,%s)
           returning id""",
        (f"o-{suffix}", f"t-{suffix}", s["employee"], s["merchant"], EMPLOYEE * count, s["company"], product,
         count + bonus, EMPLOYEE, count, bonus, EMPLOYEE * count, subsidy, restaurant, EMPLOYEE * count)).fetchone()[0]
    pg.execute("select public.fulfill_subsidized_order(%s,%s,'CARD','{}'::jsonb,%s)", (order, f"trx-{suffix}", when))
    ids = [r[0] for r in pg.execute("select id from vouchers where order_id=%s order by issue_index", (order,)).fetchall()]
    assert len(ids) == count + bonus
    return order, ids


def _use(pg, s, key=None):
    return pg.execute("select public.consume_subsidized_voucher(%s,%s,%s,%s)",
                      (s["employee"], s["company"], s["merchant"], key or str(uuid.uuid4()))).fetchone()[0]


def _settlement(pg, s, month="2031-03"):
    return pg.execute("""select settlement_status,tx_count,supply_amount,vat_amount,total_amount from settlements
                         where merchant_id=%s and company_id=%s and period_ym=%s and not is_demo""",
                      (s["merchant"], s["company"], month)).fetchone()


def _rows(pg, voucher):
    return pg.execute("""select kind,pay_type,company_id,amount,settlement_total_amount,created_at,
                                coalesce(flags,'{}'::jsonb) ? 'subsidy_charge'
                         from meal_transactions where voucher_id=%s order by id""", (voucher,)).fetchall()


def test_buying_a_subsidized_voucher_bills_the_company_that_month(pg):
    s = _scene(pg)
    _, (voucher,) = _buy(pg, s)
    rows = _rows(pg, voucher)
    assert len(rows) == 1
    kind, pay_type, company, amount, settled, created, is_charge = rows[0]
    assert (kind, pay_type, company, amount, settled, is_charge) == ("spend", "subsidized", s["company"], -SUBSIDY, SUBSIDY, True)
    assert created.isoformat().startswith("2031-03-10")          # dated at the purchase, not now
    assert _settlement(pg, s) == ("draft", 1, 909, 91, 1000)     # one voucher x 1,000 subsidy
    assert pg.execute("select count(*) from subsidy_charge_issues").fetchone()[0] == 0


def test_using_the_voucher_later_does_not_bill_the_company_again(pg):
    s = _scene(pg)
    _, (voucher,) = _buy(pg, s)
    key = str(uuid.uuid4())
    used = _use(pg, s, key)
    assert (used["duplicate"], used["amount"], used["remaining"]) == (False, PRICE, 0)
    assert (used["employee_paid_amount"], used["company_subsidy_amount"], used["settlement_total_amount"]) == (EMPLOYEE, SUBSIDY, 0)
    # The meal row looks exactly like before, except that it bills nothing.
    meal = pg.execute("""select kind,pay_type,company_id,amount,employee_paid_amount,company_subsidy_amount,total_amount,
                                settlement_supply_amount,settlement_vat_amount,settlement_total_amount,
                                flags->>'charged_at_purchase'
                         from meal_transactions where id=%s""", (used["id"],)).fetchone()
    assert meal == ("spend", "subsidized", s["company"], -PRICE, EMPLOYEE, SUBSIDY, PRICE, 0, 0, 0, "true")
    assert _settlement(pg, s) == ("draft", 1, 909, 91, 1000)     # the meal is in another month: nothing added
    assert pg.execute("select status from vouchers where id=%s", (voucher,)).fetchone()[0] == "used"
    # The same request again is a replay, not a second meal.
    again = _use(pg, s, key)
    assert (again["duplicate"], again["id"], again["amount"], again["company_subsidy_amount"]) == (True, used["id"], PRICE, SUBSIDY)
    # A voucher can still be eaten only once.
    with pytest.raises(Exception, match="NO_VOUCHER"):
        _use(pg, s)


def test_a_meal_in_the_same_month_as_the_purchase_adds_nothing(pg):
    s = _scene(pg)
    month = pg.execute("select to_char(now() at time zone 'Asia/Seoul','YYYY-MM')").fetchone()[0]
    _buy(pg, s, when=pg.execute("select now()").fetchone()[0], count=2)
    assert _settlement(pg, s, month)[4] == 2000
    _use(pg, s)
    _use(pg, s)
    assert _settlement(pg, s, month)[2:] == (1818, 182, 2000)    # still two purchases x 1,000
    summary = pg.execute("select public.merchant_ledger_summary(%s,%s,(now() at time zone 'Asia/Seoul')::date,(now() at time zone 'Asia/Seoul')::date)",
                         (s["merchant"], s["company"])).fetchone()[0]
    assert summary["total_amount"] == 2000                       # not 4,000


def test_a_voucher_left_unused_stays_on_the_company_bill(pg):
    s = _scene(pg)
    _buy(pg, s, count=3)
    _use(pg, s)
    assert _settlement(pg, s)[2:] == (2727, 273, 3000)           # 3 bought, 1 eaten: 3 billed


def test_refunding_an_unused_voucher_takes_it_off_the_bill(pg):
    s = _scene(pg)
    _, vouchers = _buy(pg, s, count=2)
    assert _settlement(pg, s)[4] == 2000
    pg.execute("update vouchers set status='refunded' where id=%s", (vouchers[1],))
    rows = _rows(pg, vouchers[1])
    assert [(r[0], r[3], r[4]) for r in rows] == [("spend", -SUBSIDY, SUBSIDY), ("refund", SUBSIDY, SUBSIDY)]
    assert rows[0][5] == rows[1][5]                              # reversal sits in the purchase's period
    assert _settlement(pg, s)[4] == 1000
    flags = pg.execute("select flags from meal_transactions where voucher_id=%s and kind='refund'", (vouchers[1],)).fetchone()[0]
    assert flags["after_settlement_closed"] is False and flags["voucher_status"] == "refunded"
    # Refunding the last one too leaves nothing to bill.
    pg.execute("update vouchers set status='refunded' where id=%s", (vouchers[0],))
    left = _settlement(pg, s)
    assert left is None or left[4] == 0
    assert pg.execute("select count(*) from subsidy_charge_issues").fetchone()[0] == 0


def test_a_refund_after_the_settlement_was_sent_comes_off_the_current_month(pg):
    s = _scene(pg)
    month = pg.execute("select to_char(now() at time zone 'Asia/Seoul','YYYY-MM')").fetchone()[0]
    _, vouchers = _buy(pg, s, count=2)
    sid = pg.execute("select id from settlements where merchant_id=%s and company_id=%s and period_ym='2031-03'",
                     (s["merchant"], s["company"])).fetchone()[0]
    pg.execute("select merchant_send_settlement(%s,%s,%s)", (s["actor"], s["merchant"], sid))
    _buy(pg, s, when=pg.execute("select now()").fetchone()[0], count=3)       # this month's purchases
    assert _settlement(pg, s, month)[4] == 3000
    pg.execute("update vouchers set status='refunded' where id=%s", (vouchers[0],))
    assert pg.execute("select status from vouchers where id=%s", (vouchers[0],)).fetchone()[0] == "refunded"
    assert _settlement(pg, s)[0] == "sent" and _settlement(pg, s)[4] == 2000  # the sent settlement is not rewritten
    assert _settlement(pg, s, month)[4] == 2000                               # 3,000 - the 1,000 refund
    flags = pg.execute("select flags from meal_transactions where voucher_id=%s and kind='refund'", (vouchers[0],)).fetchone()[0]
    assert (flags["after_settlement_closed"], flags["carried_to_current_period"]) == (True, True)
    assert pg.execute("select count(*) from subsidy_charge_issues").fetchone()[0] == 0


def test_a_late_refund_with_nothing_else_this_month_never_blocks_the_refund(pg):
    s = _scene(pg)
    _, vouchers = _buy(pg, s, count=1)
    sid = pg.execute("select id from settlements where merchant_id=%s and company_id=%s and period_ym='2031-03'",
                     (s["merchant"], s["company"])).fetchone()[0]
    pg.execute("select merchant_send_settlement(%s,%s,%s)", (s["actor"], s["merchant"], sid))
    pg.execute("update vouchers set status='refunded' where id=%s", (vouchers[0],))
    assert pg.execute("select status from vouchers where id=%s", (vouchers[0],)).fetchone()[0] == "refunded"
    # Nothing was bought this month, so the current period cannot go negative: the reversal is
    # recorded against the (frozen) purchase month and the case is logged for a manual correction.
    month = pg.execute("select to_char(now() at time zone 'Asia/Seoul','YYYY-MM')").fetchone()[0]
    assert _settlement(pg, s, month) is None and _settlement(pg, s)[4] == 1000
    rows = _rows(pg, vouchers[0])
    assert [r[0] for r in rows] == ["spend", "refund"] and rows[0][5] == rows[1][5]
    flags = pg.execute("select flags from meal_transactions where voucher_id=%s and kind='refund'", (vouchers[0],)).fetchone()[0]
    assert (flags["after_settlement_closed"], flags["carried_to_current_period"]) == (True, False)
    issues = pg.execute("select stage,detail from subsidy_charge_issues").fetchall()
    assert len(issues) == 1 and issues[0][0] == "reversal" and issues[0][1].startswith("not carried to the current period")


def test_vouchers_bought_before_the_change_are_still_billed_when_used(pg):
    s = _scene(pg)
    pg.execute("alter table vouchers disable trigger trg_voucher_subsidy_charge")
    _, (voucher,) = _buy(pg, s)
    pg.execute("alter table vouchers enable trigger trg_voucher_subsidy_charge")
    assert _rows(pg, voucher) == [] and _settlement(pg, s) is None
    used = _use(pg, s)
    meal = pg.execute("""select pay_type,company_id,amount,settlement_total_amount,coalesce(flags,'{}'::jsonb) ? 'charged_at_purchase'
                         from meal_transactions where id=%s""", (used["id"],)).fetchone()
    assert meal == ("subsidized", s["company"], -PRICE, SUBSIDY, False)
    assert _settlement(pg, s, pg.execute("select to_char(now() at time zone 'Asia/Seoul','YYYY-MM')").fetchone()[0])[4] == SUBSIDY
    # And refunding an old unused voucher writes nothing.
    pg.execute("alter table vouchers disable trigger trg_voucher_subsidy_charge")
    _, (old,) = _buy(pg, s)
    pg.execute("alter table vouchers enable trigger trg_voucher_subsidy_charge")
    pg.execute("update vouchers set status='refunded' where id=%s", (old,))
    assert _rows(pg, old) == []


def test_bonus_vouchers_and_restaurant_discounts_are_not_billed(pg):
    s = _scene(pg)
    _, vouchers = _buy(pg, s, count=2, bonus=1, restaurant=500)
    assert [len(_rows(pg, v)) for v in vouchers] == [1, 1, 0]    # the free bonus voucher bills nothing
    assert _settlement(pg, s)[4] == 2 * SUBSIDY                  # the restaurant's own 500 is not billed
    assert _use(pg, s)["company_subsidy_amount"] == SUBSIDY


def test_ledger_companies_are_billed_exactly_as_before(pg):
    s = _scene(pg, subsidy=False)
    for day in ("03", "15"):
        pg.execute(
            """insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,tx_code,meal_window,
                 tax_type,supply_amount,vat_amount,total_amount,
                 settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
               values(%s,%s,%s,-8800,'spend','ledger',%s,'중식','taxable',8000,800,8800,'taxable',8000,800,8800,%s)""",
            (s["employee"], s["company"], s["merchant"], uuid.uuid4().hex[:10], f"2031-03-{day} 03:00:00+00"))
    assert _settlement(pg, s) == ("draft", 2, 16000, 1600, 17600)
    assert pg.execute("select count(*) from meal_transactions where coalesce(flags,'{}'::jsonb) ? 'subsidy_charge'").fetchone()[0] == 0


def test_a_billing_failure_never_blocks_the_voucher(pg):
    s = _scene(pg)
    # Force the charge to fail.
    pg.execute("""create or replace function public.split_tax_inclusive(p_total integer, p_tax_type text)
                  returns table(supply_amount integer, vat_amount integer, total_amount integer)
                  language plpgsql as $$ begin raise exception 'BOOM'; end $$""")
    _, (voucher,) = _buy(pg, s)
    assert pg.execute("select status from vouchers where id=%s", (voucher,)).fetchone()[0] == "unused"
    assert _rows(pg, voucher) == []
    issue = pg.execute("select stage,detail from subsidy_charge_issues where voucher_id=%s", (voucher,)).fetchone()
    assert issue == ("charge", "BOOM")
