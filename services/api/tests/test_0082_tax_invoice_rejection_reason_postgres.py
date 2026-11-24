"""Migration 0082 on PostgreSQL 16: Popbill's rejection reason stays on the invoice and its event."""
from pathlib import Path

from tests.test_0073_exposure_generator_postgres import db0073, pg  # noqa: F401  (fixtures)
from tests.test_settlement_postgres import parties, settlement, settlement_db  # noqa: F401  (fixture)

M0082 = Path(__file__).resolve().parents[3] / "supabase" / "migrations" / "0082_tax_invoice_rejection_reason.sql"


def test_0082_contract():
    sql = M0082.read_text(encoding="utf-8")
    assert "create or replace function public.merchant_finalize_tax_invoice_issue(" in sql
    assert "'failure_message',inv.failure_message" in sql
    assert "to service_role" in sql


def test_rejection_reason_is_stored_on_invoice_and_event(pg):
    company, _, merchant, _, company_actor, _, actor, _ = parties(pg)
    sid = settlement(pg, company, merchant)
    pg.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (company_actor, company, sid))
    claim = pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, sid)).fetchone()[0]
    reason = "팝빌 거절 [-11000005] 작성일자가 발행기한을 초과했습니다." + "가" * 400
    result = pg.execute(
        "select merchant_finalize_tax_invoice_issue(%s,%s,%s,%s,'rejected','POPBILL_ISSUE_REJECTED',%s)",
        (actor, merchant, sid, claim["attempt_token"], reason),
    ).fetchone()[0]
    assert result["settlement"]["tax_invoice_status"] == "failed"
    invoice_id = claim["tax_invoice"]["id"]
    stored = pg.execute(
        "select popbill_status,failure_code,failure_message from tax_invoices where id=%s", (invoice_id,)
    ).fetchone()
    assert stored[0:2] == ("failed", "POPBILL_ISSUE_REJECTED")
    assert stored[2] == reason[:300]
    payload = pg.execute(
        """select payload from tax_invoice_events where tax_invoice_id=%s
           and event_type='tax_invoice_issue_rejected' order by occurred_at desc limit 1""",
        (invoice_id,),
    ).fetchone()[0]
    assert payload["failure_code"] == "POPBILL_ISSUE_REJECTED"
    assert payload["failure_message"] == reason[:300]
    assert payload["attempt_token"] == str(claim["attempt_token"])

    # Without a reason the old defaults still apply.
    claim = pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, sid)).fetchone()[0]
    pg.execute(
        "select merchant_finalize_tax_invoice_issue(%s,%s,%s,%s,'rejected',null,null)",
        (actor, merchant, sid, claim["attempt_token"]),
    )
    assert pg.execute("select failure_message from tax_invoices where id=%s", (invoice_id,)).fetchone()[0] == (
        "Popbill rejected the request"
    )
