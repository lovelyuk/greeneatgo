"""Migration 0081 on PostgreSQL 16: dashboards count meals, not purchase charges."""
import uuid

from tests.test_0073_exposure_generator_postgres import db0073, pg  # noqa: F401  (fixtures)
from tests.test_0080_subsidy_purchase_billing_postgres import EMPLOYEE, PRICE, SUBSIDY, _buy, _scene, _use
from tests.test_settlement_postgres import parties, settlement_db  # noqa: F401  (fixture)


def _today(pg):
    return pg.execute("select (now() at time zone 'Asia/Seoul')::date, to_char(now() at time zone 'Asia/Seoul','YYYY-MM'), now()").fetchone()


def _dashboard(pg, s, today, company=None):
    return pg.execute("select public.admin_dashboard_summary(%s,%s,%s,%s,%s,23)",
                      (s["actor"], today, today, s["merchant"], company)).fetchone()[0]


def _usage(pg, s, month):
    return pg.execute("select public.company_monthly_usage(%s,%s,%s)", (s["company_actor"], s["company"], month)).fetchone()[0]


def test_restaurant_dashboard_counts_the_meals_and_keeps_the_subsidy_amount(pg):
    s = _scene(pg)
    today, _, now = _today(pg)
    _buy(pg, s, when=now, count=3)                       # 3 bought: 3,000 billed, nothing eaten yet
    bought = _dashboard(pg, s, today)
    assert (bought["total_amount"], bought["total_count"]) == (3 * SUBSIDY, 0)
    assert bought["top_companies_by_amount"][0]["amount"] == 3 * SUBSIDY
    assert bought["top_companies_by_count"][0]["count"] == 0
    assert [row["count"] for row in bought["by_meal_type"]] == [0, 0]
    _use(pg, s)
    _use(pg, s)                                          # 2 eaten
    data = _dashboard(pg, s, today)
    assert (data["total_amount"], data["total_count"]) == (3 * SUBSIDY, 2)
    assert data["top_companies_by_amount"] == [{"rank": 1, "name": data["top_companies_by_amount"][0]["name"], "amount": 3 * SUBSIDY}]
    assert data["top_companies_by_count"][0]["count"] == 2
    meals = data["by_meal_type"]                         # 중식 before 23:00 KST, 석식 after
    assert (sum(row["amount"] for row in meals), sum(row["count"] for row in meals)) == (3 * SUBSIDY, 2)
    assert sum(float(row["ratio"]) for row in meals) == 100.0   # shares are of meals eaten, purchases excluded
    assert [(row["amount"], row["count"]) for row in data["series"]] == [(3 * SUBSIDY, 2)]
    # The company-scoped view agrees.
    scoped = _dashboard(pg, s, today, company=s["company"])
    assert (scoped["total_amount"], scoped["total_count"]) == (3 * SUBSIDY, 2)


def test_a_refunded_voucher_changes_the_amount_and_never_the_count(pg):
    s = _scene(pg)
    today, _, now = _today(pg)
    _, vouchers = _buy(pg, s, when=now, count=2)
    _use(pg, s)
    pg.execute("update vouchers set status='refunded' where id=%s", (vouchers[1],))
    data = _dashboard(pg, s, today)
    assert (data["total_amount"], data["total_count"]) == (SUBSIDY, 1)
    assert pg.execute("select count(*) from subsidy_charge_issues").fetchone()[0] == 0


def test_company_usage_counts_meals_and_bills_purchases(pg):
    s = _scene(pg)
    _, month, now = _today(pg)
    _buy(pg, s, when=now, count=3)
    bought = _usage(pg, s, month)["summary"]
    assert (bought["company_charge_amount"], bought["gross_spend_amount"], bought["transaction_count"],
            bought["spend_count"], bought["unique_users"]) == (3 * SUBSIDY, 0, 0, 0, 0)
    _use(pg, s)
    _use(pg, s)
    data = _usage(pg, s, month)
    summary = data["summary"]
    assert summary["company_charge_amount"] == 3 * SUBSIDY           # what the company is billed: purchases
    assert summary["gross_spend_amount"] == 2 * PRICE                # the value of the meals eaten
    assert summary["employee_paid_amount"] == 2 * EMPLOYEE
    assert (summary["transaction_count"], summary["spend_count"], summary["reversal_count"], summary["unique_users"]) == (2, 2, 0, 1)
    assert [(day["company_charge_amount"], day["spend_count"], day["transaction_count"], day["unique_users"]) for day in data["daily"]] == [(3 * SUBSIDY, 2, 2, 1)]
    person = data["employees"][0]
    assert (person["company_charge_amount"], person["gross_spend_amount"], person["spend_count"], person["transaction_count"],
            person["usage_days"]) == (3 * SUBSIDY, 2 * PRICE, 2, 2, 1)
    assert data["settlements"]["total_amount"] == 3 * SUBSIDY


def test_ledger_companies_count_exactly_as_before(pg):
    s = _scene(pg, subsidy=False)
    today, month, now = _today(pg)
    ids = []
    for _ in range(3):
        ids.append(pg.execute(
            """insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,tx_code,meal_window,
                 tax_type,supply_amount,vat_amount,total_amount,
                 settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
               values(%s,%s,%s,-8800,'spend','ledger',%s,'중식','taxable',8000,800,8800,'taxable',8000,800,8800,%s) returning id""",
            (s["employee"], s["company"], s["merchant"], uuid.uuid4().hex[:10], now)).fetchone()[0])
    pg.execute(
        """insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,tx_code,meal_window,
             tax_type,supply_amount,vat_amount,total_amount,
             settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at,original_transaction_id)
           values(%s,%s,%s,8800,'cancel','ledger',%s,'중식','taxable',8000,800,8800,'taxable',8000,800,8800,%s,%s)""",
        (s["employee"], s["company"], s["merchant"], uuid.uuid4().hex[:10], now, ids[0]))
    data = _dashboard(pg, s, today)
    assert (data["total_amount"], data["total_count"]) == (17600, 2)                 # 3 meals - 1 cancelled
    assert data["top_companies_by_count"][0]["count"] == 2
    assert sum(float(row["ratio"]) for row in data["by_meal_type"]) == 100.0
    summary = _usage(pg, s, month)["summary"]
    assert (summary["company_charge_amount"], summary["gross_spend_amount"], summary["transaction_count"],
            summary["spend_count"], summary["reversal_count"], summary["unique_users"]) == (17600, 17600, 4, 3, 1, 1)
