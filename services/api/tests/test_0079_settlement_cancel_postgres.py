"""Migration 0079 on PostgreSQL 16: the restaurant cancels a meal in a disputed settlement."""
import uuid

import pytest

from tests.test_0073_exposure_generator_postgres import db0073, pg  # noqa: F401  (fixtures)
from tests.test_settlement_postgres import parties, settlement_db  # noqa: F401  (fixture)


def _scene(pg, month="2031-03"):
    """A company with a contract, one employee and three 8,800 ledger meals in one month."""
    company, other_company, merchant, other_merchant, company_actor, _, actor, other_actor = parties(pg)
    pg.execute("update companies set status='active' where id=%s", (company,))
    pg.execute("insert into merchant_companies(merchant_id,company_id,status,created_by) values(%s,%s,'active',%s)",
               (merchant, company, actor))
    employee = pg.execute(
        """insert into app_users(id,company_id,display_name,role,status,monthly_limit)
           values(gen_random_uuid(),%s,'직원','employee','active',20000) returning id""", (company,)).fetchone()[0]
    ids = []
    for day in ("03", "15", "28"):
        ids.append(pg.execute(
            """insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,tx_code,meal_window,
                 tax_type,supply_amount,vat_amount,total_amount,
                 settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
               values(%s,%s,%s,-8800,'spend','ledger',%s,'중식','taxable',8000,800,8800,'taxable',8000,800,8800,%s)
               returning id""",
            (employee, company, merchant, uuid.uuid4().hex[:10], f"{month}-{day} 03:00:00+00")).fetchone()[0])
    sid = pg.execute("select id from settlements where merchant_id=%s and company_id=%s and period_ym=%s and not is_demo",
                     (merchant, company, month)).fetchone()[0]
    return dict(company=company, merchant=merchant, other_merchant=other_merchant, company_actor=company_actor,
                actor=actor, other_actor=other_actor, employee=employee, tx=ids, sid=sid)


def _settlement(pg, sid):
    return pg.execute("select settlement_status,tx_count,supply_amount,vat_amount,total_amount from settlements where id=%s", (sid,)).fetchone()


def _cancel(pg, s, tx, reason="그날 식사하지 않음", actor=None, merchant=None, sid=None):
    return pg.execute("select public.merchant_cancel_settlement_transaction(%s,%s,%s,%s,%s)",
                      (actor or s["actor"], merchant or s["merchant"], sid or s["sid"], tx, reason)).fetchone()[0]


def _dispute_and_revise(pg, s):
    pg.execute("select merchant_send_settlement(%s,%s,%s)", (s["actor"], s["merchant"], s["sid"]))
    pg.execute("select company_dispute_settlement(%s,%s,%s,'15일은 식사하지 않았어요','d-1')",
               (s["company_actor"], s["company"], s["sid"]))
    pg.execute("select merchant_begin_settlement_revision(%s,%s,%s)", (s["actor"], s["merchant"], s["sid"]))


def test_cancelling_a_meal_in_revision_recalculates_the_settlement_and_keeps_the_record(pg):
    s = _scene(pg)
    assert _settlement(pg, s["sid"]) == ("draft", 3, 24000, 2400, 26400)
    _dispute_and_revise(pg, s)
    result = _cancel(pg, s, s["tx"][1])
    assert result["idempotent"] is False
    assert (result["settlement"]["total_amount"], result["settlement"]["supply_amount"], result["settlement"]["vat_amount"]) == (17600, 16000, 1600)
    assert _settlement(pg, s["sid"]) == ("revising", 4, 16000, 1600, 17600)
    # The original meal is untouched; a reversal row with the same timestamp points at it.
    original = pg.execute("select kind,amount,created_at from meal_transactions where id=%s", (s["tx"][1],)).fetchone()
    cancel = pg.execute("""select kind,amount,pay_type,company_id,user_id,created_at,settlement_total_amount,
                                  flags->>'cancel_reason',flags->>'cancelled_by',tx_code
                             from meal_transactions where original_transaction_id=%s""", (s["tx"][1],)).fetchone()
    assert original[:2] == ("spend", -8800)
    assert cancel == ("cancel", 8800, "ledger", s["company"], s["employee"], original[2], 8800,
                      "그날 식사하지 않음", str(s["actor"]), f"CX-{s['tx'][1]}")
    event = pg.execute("""select payload from settlement_events where settlement_id=%s
                           and event_type='merchant_transaction_cancelled'""", (s["sid"],)).fetchone()[0]
    assert (event["transaction_id"], event["reason"], event["amount"], event["total_amount"]) == (s["tx"][1], "그날 식사하지 않음", 8800, 17600)
    # Asking again changes nothing.
    again = _cancel(pg, s, s["tx"][1], reason="다른 사유")
    assert again["idempotent"] is True and again["cancel_transaction_id"] == result["cancel_transaction_id"]
    assert pg.execute("select count(*) from meal_transactions where original_transaction_id=%s", (s["tx"][1],)).fetchone()[0] == 1
    assert _settlement(pg, s["sid"])[4] == 17600
    # The corrected settlement goes back to the company.
    resent = pg.execute("select merchant_send_settlement(%s,%s,%s)", (s["actor"], s["merchant"], s["sid"])).fetchone()[0]
    assert (resent["settlement"]["settlement_status"], resent["settlement"]["total_amount"]) == ("sent", 17600)


def test_a_draft_can_be_corrected_and_every_meal_can_be_cancelled(pg):
    s = _scene(pg, "2031-04")
    for tx in s["tx"]:
        assert _cancel(pg, s, tx)["idempotent"] is False
    assert _settlement(pg, s["sid"]) == ("draft", 6, 0, 0, 0)


def test_cancel_is_refused_outside_draft_or_revision_and_for_other_tenants(pg):
    import psycopg
    s = _scene(pg, "2031-05")

    def refused(match, **kwargs):
        pg.execute("savepoint r")
        with pytest.raises(psycopg.errors.RaiseException, match=match):
            _cancel(pg, s, kwargs.pop("tx", s["tx"][0]), **kwargs)
        pg.execute("rollback to savepoint r")

    refused("SETTLEMENT_FORBIDDEN", actor=s["company_actor"])
    refused("SETTLEMENT_FORBIDDEN", actor=s["other_actor"])
    refused("SETTLEMENT_NOT_FOUND", actor=s["other_actor"], merchant=s["other_merchant"])
    refused("SETTLEMENT_INPUT_INVALID", reason="   ")
    refused("SETTLEMENT_INPUT_INVALID", reason="가" * 301)
    refused("SETTLEMENT_TRANSACTION_NOT_FOUND", tx=987654321)
    # A meal of the same restaurant and company from another month is not part of this settlement.
    other_month = pg.execute(
        """insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,tx_code,
             settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
           values(%s,%s,%s,-8800,'spend','ledger',%s,'taxable',8000,800,8800,'2031-06-10 03:00:00+00') returning id""",
        (s["employee"], s["company"], s["merchant"], uuid.uuid4().hex[:10])).fetchone()[0]
    refused("SETTLEMENT_TRANSACTION_NOT_FOUND", tx=other_month)
    # Sent to the company (waiting for its answer) and disputed-but-not-yet-revising: locked.
    pg.execute("select merchant_send_settlement(%s,%s,%s)", (s["actor"], s["merchant"], s["sid"]))
    refused("SETTLEMENT_STATE_CONFLICT")
    pg.execute("select company_dispute_settlement(%s,%s,%s,'확인 필요','d-2')", (s["company_actor"], s["company"], s["sid"]))
    refused("SETTLEMENT_STATE_CONFLICT")
    pg.execute("select merchant_begin_settlement_revision(%s,%s,%s)", (s["actor"], s["merchant"], s["sid"]))
    cancel_id = _cancel(pg, s, s["tx"][0])["cancel_transaction_id"]
    # A reversal row itself cannot be cancelled.
    refused("SETTLEMENT_TRANSACTION_NOT_CANCELLABLE", tx=cancel_id)
    assert _settlement(pg, s["sid"])[4] == 17600
    for role in ("anon", "authenticated"):
        assert pg.execute(f"select has_function_privilege('{role}','public.merchant_cancel_settlement_transaction(uuid,uuid,uuid,bigint,text)','execute')").fetchone()[0] is False


def test_a_cancelled_meal_gives_the_employee_limit_back(pg):
    import psycopg
    company, _, merchant, _, _, _, actor, _ = parties(pg)
    pg.execute("update companies set status='active' where id=%s", (company,))
    pg.execute("""insert into merchant_companies(merchant_id,company_id,status,created_by,unit_price,tax_type)
                  values(%s,%s,'active',%s,8000,'taxable')""", (merchant, company, actor))
    employee = pg.execute("""insert into app_users(id,company_id,display_name,role,status,monthly_limit)
                             values(gen_random_uuid(),%s,'e','employee','active',10000) returning id""", (company,)).fetchone()[0]

    def pay():
        return pg.execute("""select public.process_meal_pay(p_user_id=>%s,p_company_id=>%s,p_merchant_id=>%s,p_amount=>8000,
                               p_tx_code=>%s,p_meal_window=>'중식',p_flags=>'{}'::jsonb,p_idempotency_key=>%s,
                               p_product_id=>null,p_product_name=>null,p_product_price=>null)""",
                          (employee, company, merchant, uuid.uuid4().hex[:10], str(uuid.uuid4()))).fetchone()[0]

    first = pay()
    pg.execute("savepoint s")
    with pytest.raises(psycopg.errors.RaiseException, match="MONTHLY_LIMIT"):
        pay()
    pg.execute("rollback to savepoint s")
    sid = pg.execute("select id from settlements where merchant_id=%s and company_id=%s and not is_demo", (merchant, company)).fetchone()[0]
    pg.execute("select public.merchant_cancel_settlement_transaction(%s,%s,%s,%s,'중복 결제')", (actor, merchant, sid, first["id"]))
    assert pay()["duplicate"] is False
    pg.execute("savepoint s")
    with pytest.raises(psycopg.errors.RaiseException, match="MONTHLY_LIMIT"):
        pay()
    pg.execute("rollback to savepoint s")
