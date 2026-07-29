import base64
import datetime
import os
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).resolve().parents[3] / "infra" / "migrations"


@pytest.fixture(scope="module")
def settlement_db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL for PostgreSQL 16 settlement integration")
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(url, autocommit=True) as conn:
        assert 160000 <= int(conn.execute("show server_version_num").fetchone()[0]) < 170000
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
        """)
        if not conn.execute("select exists(select 1 from pg_publication where pubname='supabase_realtime')").fetchone()[0]:
            conn.execute("create publication supabase_realtime")
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(migration.read_text(encoding="utf-8"))
        # Both replay orders are required: the pair remains compatible, and 0037
        # alone must retain the resend behavior when it is the last replayed file.
        conn.execute((MIGRATIONS / "0037_atomic_settlement_workflows.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0038_atomic_kiwoom_notifications.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0037_atomic_settlement_workflows.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0039_popbill_tax_invoice_issuance.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0039_popbill_tax_invoice_issuance.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0042_settlement_demo.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0042_settlement_demo.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0044_settlement_demo_state_rpc.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0045_demo_transaction_isolation.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0045_demo_transaction_isolation.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0046_settlement_demo_usage_details.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0046_settlement_demo_usage_details.sql").read_text(encoding="utf-8"))
        # 0045 may be replayed by recovery tooling; additive display and generic
        # settlement integration restores must remain idempotent after it.
        conn.execute((MIGRATIONS / "0047_demo_transaction_integrated_reads.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0047_demo_transaction_integrated_reads.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0048_demo_generic_settlement_integration.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0048_demo_generic_settlement_integration.sql").read_text(encoding="utf-8"))
        # Recovery tooling may replay older workflow files. The newest workflow
        # migration must be replay-safe and remain the final authority afterward.
        conn.execute((MIGRATIONS / "0049_recommended_settlement_workflow.sql").read_text(encoding="utf-8"))
        conn.execute((MIGRATIONS / "0049_recommended_settlement_workflow.sql").read_text(encoding="utf-8"))
    return url


@pytest.fixture
def pg(settlement_db):
    import psycopg
    with psycopg.connect(settlement_db) as conn:
        yield conn
        conn.rollback()


def parties(pg):
    company = pg.execute("""insert into companies(name,biz_reg_no,representative_name,address,business_type,business_item,
                       tax_invoice_email,contact_name,contact_phone)
                       values ('Recipient','123-45-67890','Rep','Seoul','Services','Meals','tax@example.com','Contact','01012345678') returning id""").fetchone()[0]
    other_company = pg.execute("insert into companies(name) values ('Other') returning id").fetchone()[0]
    merchant = pg.execute("""insert into merchants(name,biz_reg_no,representative_name,address,business_type,business_item,tax_invoice_email,owner_phone,qr_token,view_token)
                        values ('Supplier','999-88-77777','Owner','Busan','Food','Restaurant','supplier@example.com','01099998888',%s,%s) returning id""",
                          (str(uuid.uuid4()), str(uuid.uuid4()))).fetchone()[0]
    other_merchant = pg.execute("insert into merchants(name,qr_token,view_token) values ('Other merchant',%s,%s) returning id",
                                (str(uuid.uuid4()), str(uuid.uuid4()))).fetchone()[0]
    company_actor = pg.execute("insert into app_users(id,company_id,display_name,role,status) values(gen_random_uuid(),%s,'company','company_admin','active') returning id", (company,)).fetchone()[0]
    other_company_actor = pg.execute("insert into app_users(id,company_id,display_name,role,status) values(gen_random_uuid(),%s,'other company','company_admin','active') returning id", (other_company,)).fetchone()[0]
    merchant_actor = pg.execute("insert into app_users(id,merchant_id,display_name,role,status) values(gen_random_uuid(),%s,'merchant','merchant_admin','active') returning id", (merchant,)).fetchone()[0]
    other_merchant_actor = pg.execute("insert into app_users(id,merchant_id,display_name,role,status) values(gen_random_uuid(),%s,'other merchant','merchant_admin','active') returning id", (other_merchant,)).fetchone()[0]
    return company, other_company, merchant, other_merchant, company_actor, other_company_actor, merchant_actor, other_merchant_actor


def settlement(pg, company, merchant, state="sent", invoice="not_requested", due=True):
    period_from = date(2020, 1, 1) + timedelta(days=uuid.uuid4().int % 100000)
    period_to = period_from + timedelta(days=30)
    return pg.execute("""insert into settlements(company_id,merchant_id,period_ym,tx_count,total_amount,supply_amount,vat_amount,
                      period_from,period_to,settlement_tax_type,settlement_status,tax_invoice_status,due_date,status)
                      values(%s,%s,%s,1,1100,1000,100,%s,%s,'taxable',%s,%s,%s,'draft') returning id""",
                      (company, merchant, str(uuid.uuid4()), period_from, period_to, state, invoice,
                       period_to + timedelta(days=30) if due else None)).fetchone()[0]


def test_cross_tenant_denial_and_rpc_permissions(pg):
    import psycopg
    company, _, merchant, _, _, other_company_actor, _, other_merchant_actor = parties(pg)
    sid = settlement(pg, company, merchant)
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_FORBIDDEN"):
        with pg.transaction():
            pg.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (other_company_actor, company, sid))
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_FORBIDDEN"):
        with pg.transaction():
            pg.execute("select merchant_send_settlement(%s,%s,%s)", (other_merchant_actor, merchant, sid))
    assert pg.execute("select has_function_privilege('authenticated','company_confirm_and_request_tax_invoice(uuid,uuid,uuid)','execute')").fetchone()[0] is False
    assert pg.execute("select has_function_privilege('service_role','company_confirm_and_request_tax_invoice(uuid,uuid,uuid)','execute')").fetchone()[0] is True


def test_legacy_create_uses_exact_snapshots_and_can_send_then_confirm(pg):
    company, _, merchant, _, company_actor, _, merchant_actor, _ = parties(pg)
    pg.execute("insert into merchant_companies(merchant_id,company_id,status,created_by) values(%s,%s,'active',%s)",
               (merchant, company, merchant_actor))
    user_id = pg.execute("insert into app_users(id,company_id,display_name,role,status) values(gen_random_uuid(),%s,'employee','employee','active') returning id", (company,)).fetchone()[0]
    pg.execute("""insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,
                 settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
                 values(%s,%s,%s,-1100,'spend','ledger','taxable',1000,100,1100,'2026-07-05 03:00:00+00'),
                       (%s,%s,%s,-500,'spend','ledger','taxable',455,45,500,'2026-07-06 03:00:00+00'),
                       (%s,%s,%s,220,'refund','ledger','taxable',200,20,220,'2026-07-07 03:00:00+00')""",
               (user_id,company,merchant,user_id,company,merchant,user_id,company,merchant))
    created = pg.execute("select create_merchant_settlement(%s,%s,'2026-07-01','2026-07-31')", (merchant,company)).fetchone()[0]
    assert (created["period_ym"],created["tx_count"],created["supply_amount"],created["vat_amount"],created["total_amount"]) == ("2026-07",3,1255,125,1380)
    assert created["settlement_status"] == "draft" and created["status"] == "draft" and created["due_date"] == "2026-08-30"
    duplicate = pg.execute("select create_merchant_settlement(%s,%s,'2026-07-01','2026-07-31')", (merchant,company)).fetchone()[0]
    assert duplicate["id"] == created["id"]
    sent = pg.execute("select merchant_send_settlement(%s,%s,%s)", (merchant_actor,merchant,created["id"])).fetchone()[0]
    assert sent["settlement"]["settlement_status"] == "sent"
    confirmed = pg.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (company_actor,company,created["id"])).fetchone()[0]
    assert confirmed["settlement"]["settlement_status"] == "confirmed"
    assert confirmed["tax_invoice"]["total_amount"] == 1380


def test_legacy_create_rejects_unclassified_and_sent_month_conflict(pg):
    import psycopg
    company, _, merchant, _, _, _, actor, _ = parties(pg)
    pg.execute("insert into merchant_companies(merchant_id,company_id,status,created_by) values(%s,%s,'active',%s)", (merchant,company,actor))
    user_id = pg.execute("insert into app_users(id,company_id,display_name,role,status) values(gen_random_uuid(),%s,'employee','employee','active') returning id", (company,)).fetchone()[0]
    pg.execute("insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,created_at) values(%s,%s,%s,-100,'spend','ledger','2026-08-02 00:00:00+00')", (user_id,company,merchant))
    with pytest.raises(psycopg.errors.RaiseException, match="TAX_TYPE_UNCLASSIFIED"):
        with pg.transaction():
            pg.execute("select create_merchant_settlement(%s,%s,'2026-08-01','2026-08-31')", (merchant,company))
    pg.execute("delete from meal_transactions where user_id=%s", (user_id,))
    pg.execute("""insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,
               settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
               values(%s,%s,%s,-100,'spend','ledger','tax_free',100,0,100,'2026-08-02 00:00:00+00')""",
               (user_id,company,merchant))
    row = pg.execute("select create_merchant_settlement(%s,%s,'2026-08-01','2026-08-31')", (merchant,company)).fetchone()[0]
    pg.execute("select merchant_send_settlement(%s,%s,%s)", (actor,merchant,row["id"]))
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_STATE_CONFLICT"):
        with pg.transaction():
            pg.execute("select create_merchant_settlement(%s,%s,'2026-08-01','2026-08-31')", (merchant,company))


def test_supplier_incomplete_is_atomic_and_complete_snapshot_is_immutable(pg):
    import psycopg
    company, _, merchant, _, actor, _, _, _ = parties(pg)
    sid = settlement(pg, company, merchant)
    pg.execute("update merchants set address='   ' where id=%s", (merchant,))
    with pytest.raises(psycopg.errors.RaiseException, match="SUPPLIER_PROFILE_INCOMPLETE"):
        with pg.transaction():
            pg.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (actor,company,sid))
    assert pg.execute("select settlement_status,tax_invoice_status from settlements where id=%s", (sid,)).fetchone() == ("sent","not_requested")
    assert pg.execute("select count(*) from tax_invoices where settlement_id=%s", (sid,)).fetchone()[0] == 0
    assert pg.execute("select count(*) from settlement_events where settlement_id=%s", (sid,)).fetchone()[0] == 0
    pg.execute("update merchants set address='Busan immutable' where id=%s", (merchant,))
    first = pg.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (actor,company,sid)).fetchone()[0]
    expected = {"registration_number":"999-88-77777","name":"Supplier","representative":"Owner",
                "address":"Busan immutable","business_type":"Food","business_item":"Restaurant",
                "tax_email":"supplier@example.com","contact_phone":"01099998888"}
    assert first["tax_invoice"]["supplier_snapshot"] == expected
    pg.execute("update merchants set name='Changed',address='Changed' where id=%s", (merchant,))
    duplicate = pg.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (actor,company,sid)).fetchone()[0]
    assert duplicate["idempotent"] is True
    assert duplicate["tax_invoice"]["supplier_snapshot"] == expected


def test_atomic_confirm_snapshots_and_duplicate_original(pg):
    company, _, merchant, _, company_actor, _, _, _ = parties(pg)
    sid = settlement(pg, company, merchant)
    first = pg.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (company_actor, company, sid)).fetchone()[0]
    second = pg.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (company_actor, company, sid)).fetchone()[0]
    assert first["idempotent"] is False and second["idempotent"] is True
    assert pg.execute("select settlement_status,tax_invoice_status from settlements where id=%s", (sid,)).fetchone() == ("confirmed", "requested")
    invoice = pg.execute("select invoicer_mgt_key,supply_amount,vat_amount,total_amount,recipient_snapshot from tax_invoices where settlement_id=%s", (sid,)).fetchone()
    expected_key = "GE" + base64.urlsafe_b64encode(sid.bytes).decode().rstrip("=")
    assert invoice[:4] == (expected_key, 1000, 100, 1100)
    assert invoice[4]["registration_number"] == "123-45-67890"
    assert pg.execute("select count(*) from tax_invoices where settlement_id=%s and document_type='original'", (sid,)).fetchone()[0] == 1
    assert pg.execute("select count(*) from settlement_events where settlement_id=%s and event_type='company_confirmed_and_tax_invoice_requested'", (sid,)).fetchone()[0] == 1


def test_dispute_idempotency_and_conflict(pg):
    import psycopg
    company, _, merchant, _, actor, _, _, _ = parties(pg)
    sid = settlement(pg, company, merchant)
    first = pg.execute("select company_dispute_settlement(%s,%s,%s,'amount wrong','key-one')", (actor, company, sid)).fetchone()[0]
    duplicate = pg.execute("select company_dispute_settlement(%s,%s,%s,'amount wrong','key-one')", (actor, company, sid)).fetchone()[0]
    assert first["idempotent"] is False and duplicate["idempotent"] is True
    with pytest.raises(psycopg.errors.RaiseException, match="IDEMPOTENCY_CONFLICT"):
        with pg.transaction():
            pg.execute("select company_dispute_settlement(%s,%s,%s,'different','key-one')", (actor, company, sid))
    assert pg.execute("select count(*) from settlement_events where settlement_id=%s and event_type='company_disputed'", (sid,)).fetchone()[0] == 1


def test_send_cycles_update_timestamp_and_duplicate_sent_is_idempotent(pg):
    import psycopg
    company, _, merchant, _, _, _, actor, _ = parties(pg)
    sid = settlement(pg, company, merchant, "draft")
    first = pg.execute("select merchant_send_settlement(%s,%s,%s)", (actor, merchant, sid)).fetchone()[0]
    assert first["idempotent"] is False
    first_sent_at = pg.execute("select sent_at from settlements where id=%s", (sid,)).fetchone()[0]
    assert pg.execute("select merchant_send_settlement(%s,%s,%s)", (actor, merchant, sid)).fetchone()[0]["idempotent"] is True
    assert pg.execute("select count(*) from settlement_events where settlement_id=%s and event_type='merchant_sent'", (sid,)).fetchone()[0] == 1
    pg.execute("update settlements set settlement_status='disputed' where id=%s", (sid,))
    pg.execute("update settlements set settlement_status='revising' where id=%s", (sid,))
    resent = pg.execute("select merchant_send_settlement(%s,%s,%s)", (actor, merchant, sid)).fetchone()[0]
    second_sent_at = pg.execute("select sent_at from settlements where id=%s", (sid,)).fetchone()[0]
    assert resent["idempotent"] is False and second_sent_at > first_sent_at
    assert pg.execute("select array_agg(idempotency_key order by id) from settlement_events where settlement_id=%s and event_type='merchant_sent'", (sid,)).fetchone()[0] == ["send-cycle-1", "send-cycle-2"]
    assert pg.execute("select merchant_send_settlement(%s,%s,%s)", (actor, merchant, sid)).fetchone()[0]["idempotent"] is True
    finalized = settlement(pg, company, merchant, "finalized")
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_STATE_CONFLICT"):
        with pg.transaction():
            pg.execute("select merchant_send_settlement(%s,%s,%s)", (actor, merchant, finalized))


def test_mark_paid_duplicate_conflict_and_automatic_status(pg):
    import psycopg
    company, _, merchant, _, _, _, actor, _ = parties(pg)
    sid = settlement(pg, company, merchant, "confirmed", "issued")
    args = (actor, merchant, sid, 500, "Depositor", "2026-07-01T00:00:00Z", "memo", "pay-key")
    first = pg.execute("select merchant_mark_settlement_paid(%s,%s,%s,%s,%s,%s,%s,%s)", args).fetchone()[0]
    duplicate = pg.execute("select merchant_mark_settlement_paid(%s,%s,%s,%s,%s,%s,%s,%s)", args).fetchone()[0]
    assert first["idempotent"] is False and duplicate["idempotent"] is True
    assert pg.execute("select payment_status from settlements where id=%s", (sid,)).fetchone()[0] == "partially_paid"
    with pytest.raises(psycopg.errors.RaiseException, match="IDEMPOTENCY_CONFLICT"):
        with pg.transaction():
            changed = list(args); changed[3] = 501
            pg.execute("select merchant_mark_settlement_paid(%s,%s,%s,%s,%s,%s,%s,%s)", changed)
    pg.execute("select merchant_mark_settlement_paid(%s,%s,%s,600,'Depositor','2026-07-02T00:00:00Z',null,'pay-key-two')", (actor, merchant, sid))
    assert pg.execute("select payment_status,settlement_status from settlements where id=%s", (sid,)).fetchone() == ("paid", "completed")
    assert pg.execute("select count(*) from settlement_payments where settlement_id=%s", (sid,)).fetchone()[0] == 2

    # Reconciliation is reversible: if confirmed money falls below the total,
    # completion evidence is cleared while the legacy axis remains confirmed.
    pg.execute("delete from settlement_payments where settlement_id=%s and amount=600", (sid,))
    assert pg.execute("select payment_status,settlement_status,finalized_at,status from settlements where id=%s", (sid,)).fetchone() == (
        "partially_paid", "confirmed", None, "confirmed",
    )


def test_dispute_revision_resend_and_company_summary_visibility(pg):
    company, _, merchant, other_merchant, company_actor, _, merchant_actor, _ = parties(pg)
    hidden_draft = settlement(pg, company, other_merchant, "draft")
    sent = settlement(pg, company, merchant, "sent")
    pg.execute("update settlements set period_ym='2026-11' where id in (%s,%s)", (hidden_draft, sent))

    initial = pg.execute(
        "select company_settlement_month_summary(%s,%s,'2026-11')",
        (company_actor, company),
    ).fetchone()[0]
    assert initial["settlement_count"] == 1
    disputed = pg.execute(
        "select company_dispute_settlement(%s,%s,%s,'금액 확인 필요','dispute-1')",
        (company_actor, company, sent),
    ).fetchone()[0]
    assert disputed["settlement"]["settlement_status"] == "disputed"
    revising = pg.execute(
        "select merchant_begin_settlement_revision(%s,%s,%s)",
        (merchant_actor, merchant, sent),
    ).fetchone()[0]
    assert revising["settlement"]["settlement_status"] == "revising"
    assert pg.execute(
        "select company_settlement_month_summary(%s,%s,'2026-11')",
        (company_actor, company),
    ).fetchone()[0]["settlement_count"] == 0
    resent = pg.execute(
        "select merchant_send_settlement(%s,%s,%s)", (merchant_actor, merchant, sent),
    ).fetchone()[0]
    assert resent["settlement"]["settlement_status"] == "sent"
    assert pg.execute(
        "select company_settlement_month_summary(%s,%s,'2026-11')",
        (company_actor, company),
    ).fetchone()[0]["settlement_count"] == 1
    assert pg.execute("select array_agg(event_type order by id) from settlement_events where settlement_id=%s", (sent,)).fetchone()[0] == [
        "company_disputed", "merchant_revision_started", "merchant_sent",
    ]
    assert pg.execute("select has_function_privilege('authenticated','merchant_begin_settlement_revision(uuid,uuid,uuid)','execute')").fetchone()[0] is False
    assert pg.execute("select has_function_privilege('service_role','merchant_begin_settlement_revision(uuid,uuid,uuid)','execute')").fetchone()[0] is True


def test_payment_and_issue_require_company_confirmation(pg):
    import psycopg
    company, _, merchant, _, _, _, merchant_actor, _ = parties(pg)
    sent = settlement(pg, company, merchant, "sent", "not_requested")
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_STATE_CONFLICT"):
        with pg.transaction():
            pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (merchant_actor, merchant, sent))
    pg.execute("update settlements set tax_invoice_status='issued' where id=%s", (sent,))
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_STATE_CONFLICT"):
        with pg.transaction():
            pg.execute("select merchant_mark_settlement_paid(%s,%s,%s,1100,'입금자',now(),null,'blocked-payment')", (merchant_actor, merchant, sent))


def test_send_and_dispute_require_not_requested_invoice_state(pg):
    import psycopg
    company, _, merchant, _, company_actor, _, merchant_actor, _ = parties(pg)
    sent_failed = settlement(pg, company, merchant, "sent", "failed")
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_STATE_CONFLICT"):
        with pg.transaction():
            pg.execute(
                "select company_dispute_settlement(%s,%s,%s,'잘못된 상태','invalid-dispute')",
                (company_actor, company, sent_failed),
            )

    for workflow_state in ("draft", "revising"):
        invalid_send = settlement(pg, company, merchant, workflow_state, "failed")
        with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_STATE_CONFLICT"):
            with pg.transaction():
                pg.execute(
                    "select merchant_send_settlement(%s,%s,%s)",
                    (merchant_actor, merchant, invalid_send),
                )


def test_legacy_confirm_payment_records_remaining_and_duplicate(pg):
    company, _, merchant, _, _, _, actor, _ = parties(pg)
    sid = settlement(pg, company, merchant, "confirmed", "issued")
    pg.execute("""insert into settlement_payments(settlement_id,amount,depositor_name,deposited_at,
               match_method,confirmed_by,confirmed_at,idempotency_key,created_by,updated_by)
               values(%s,400,'prior',now(),'manual',%s,now(),'prior-key',%s,%s)""",
               (sid,actor,actor,actor))
    first = pg.execute("select merchant_confirm_settlement_payment_legacy(%s,%s,%s,%s)",
                       (actor,merchant,company,sid)).fetchone()[0]
    second = pg.execute("select merchant_confirm_settlement_payment_legacy(%s,%s,%s,%s)",
                        (actor,merchant,company,sid)).fetchone()[0]
    assert first["idempotent"] is False and second["idempotent"] is True
    assert first["payment"]["amount"] == 700
    assert first["payment"]["depositor_name"] == "관리자 수동 확인"
    assert first["payment"]["memo"] == "legacy confirm-payment compatibility wrapper"
    assert pg.execute("select payment_status,status from settlements where id=%s", (sid,)).fetchone() == ("paid","paid")
    assert pg.execute("select count(*) from settlement_payments where settlement_id=%s", (sid,)).fetchone()[0] == 2
    assert pg.execute("select count(*) from settlement_events where settlement_id=%s and event_type='merchant_payment_recorded'", (sid,)).fetchone()[0] == 1


def test_concurrent_confirm_creates_one_original(settlement_db):
    import psycopg
    with psycopg.connect(settlement_db) as setup:
        company, _, merchant, _, actor, _, _, _ = parties(setup)
        sid = settlement(setup, company, merchant)
        setup.commit()

    def confirm():
        with psycopg.connect(settlement_db) as conn:
            result = conn.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (actor, company, sid)).fetchone()[0]
            conn.commit()
            return result["idempotent"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted([future.result(timeout=10) for future in (pool.submit(confirm), pool.submit(confirm))])
    assert results == [False, True]
    with psycopg.connect(settlement_db) as verify:
        assert verify.execute("select count(*) from tax_invoices where settlement_id=%s", (sid,)).fetchone()[0] == 1


def test_compact_key_write_date_and_frozen_requested_snapshot(pg):
    company, _, merchant, _, company_actor, _, actor, _ = parties(pg)
    sid = settlement(pg, company, merchant)
    period_to = pg.execute("select period_to from settlements where id=%s", (sid,)).fetchone()[0]
    pg.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (company_actor, company, sid))
    claim = pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, sid)).fetchone()[0]
    invoice = claim["tax_invoice"]
    assert claim["action"] == "issue"
    assert invoice["invoicer_mgt_key"] == "GE" + base64.urlsafe_b64encode(sid.bytes).decode().rstrip("=")
    assert len(invoice["invoicer_mgt_key"]) == 24
    assert invoice["write_date"] == period_to.isoformat()
    assert invoice["requested_at"] is not None
    assert invoice["issue_requested_by"] == str(company_actor)
    frozen = invoice["supplier_snapshot"]
    pg.execute("update merchants set name='later edit' where id=%s", (merchant,))
    assert pg.execute("select supplier_snapshot from tax_invoices where settlement_id=%s", (sid,)).fetchone()[0] == frozen


def test_mixed_tax_types_rejected_without_settlement_write(pg):
    import psycopg
    company, _, merchant, _, _, _, actor, _ = parties(pg)
    pg.execute("insert into merchant_companies(merchant_id,company_id,status,created_by) values(%s,%s,'active',%s)", (merchant,company,actor))
    user_id = pg.execute("insert into app_users(id,company_id,display_name,role,status) values(gen_random_uuid(),%s,'employee','employee','active') returning id", (company,)).fetchone()[0]
    pg.execute("""insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,
      settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
      values(%s,%s,%s,-1100,'spend','ledger','taxable',1000,100,1100,'2026-09-02T00:00:00Z'),
            (%s,%s,%s,-500,'spend','ledger','tax_free',500,0,500,'2026-09-03T00:00:00Z')""",
      (user_id,company,merchant,user_id,company,merchant))
    with pytest.raises(psycopg.errors.RaiseException, match="MIXED_TAX_TYPES_NOT_SUPPORTED"):
        with pg.transaction():
            pg.execute("select create_merchant_settlement(%s,%s,'2026-09-01','2026-09-30')", (merchant,company))
    assert pg.execute("select count(*) from settlements where company_id=%s and merchant_id=%s", (company,merchant)).fetchone()[0] == 0


def test_claim_token_ambiguous_success_and_legal_nts_transitions(pg):
    import psycopg
    company, _, merchant, _, company_actor, _, actor, _ = parties(pg)
    sid = settlement(pg, company, merchant)
    pg.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (company_actor, company, sid))
    claim = pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor,merchant,sid)).fetchone()[0]
    token = claim["attempt_token"]
    with pytest.raises(psycopg.errors.RaiseException, match="ISSUE_ATTEMPT_TOKEN_MISMATCH"):
        with pg.transaction():
            pg.execute("select merchant_finalize_tax_invoice_issue(%s,%s,%s,%s,'success',null,null)", (actor,merchant,sid,uuid.uuid4()))
    pg.execute("select merchant_finalize_tax_invoice_issue(%s,%s,%s,%s,'reconciliation_required',null,null)", (actor,merchant,sid,token))
    assert pg.execute("select tax_invoice_status from settlements where id=%s", (sid,)).fetchone()[0] == "issuing"
    assert pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor,merchant,sid)).fetchone()[0]["action"] == "reconcile"
    pg.execute("select merchant_finalize_tax_invoice_issue(%s,%s,%s,%s,'success',null,null)", (actor,merchant,sid,token))
    assert pg.execute("select tax_invoice_status from settlements where id=%s", (sid,)).fetchone()[0] == "issued"
    assert pg.execute("select popbill_status,nts_status,issued_at is not null from tax_invoices where settlement_id=%s", (sid,)).fetchone() == ("issued",None,True)
    issued_at = pg.execute("select issued_at from tax_invoices where settlement_id=%s", (sid,)).fetchone()[0]
    pg.execute("select merchant_apply_tax_invoice_status(%s,%s,%s,303,null,null,%s,%s,null)",
               (actor,merchant,sid,issued_at,issued_at + datetime.timedelta(minutes=1)))
    assert pg.execute("select tax_invoice_status,nts_status from settlements join tax_invoices on tax_invoices.settlement_id=settlements.id where settlements.id=%s", (sid,)).fetchone() == ("nts_sending","sending")
    pg.execute("select merchant_apply_tax_invoice_status(%s,%s,%s,304,'SUC001','CONFIRM-1',null,null,%s)",
               (actor,merchant,sid,issued_at + datetime.timedelta(minutes=2)))
    accepted_facts = pg.execute("select nts_status_code,nts_confirm_num,nts_sent_at,nts_accepted_at from tax_invoices where settlement_id=%s", (sid,)).fetchone()
    pg.execute("select merchant_apply_tax_invoice_status(%s,%s,%s,305,'ERR',null,null,null,null)", (actor,merchant,sid))
    assert pg.execute("select tax_invoice_status,nts_status from settlements join tax_invoices on tax_invoices.settlement_id=settlements.id where settlements.id=%s", (sid,)).fetchone() == ("nts_accepted","accepted")
    assert pg.execute("select nts_status_code,nts_confirm_num,nts_sent_at,nts_accepted_at from tax_invoices where settlement_id=%s", (sid,)).fetchone() == accepted_facts
    pg.execute("select merchant_apply_tax_invoice_status(%s,%s,%s,304,'SUC001',null,null,null,null)", (actor,merchant,sid))
    assert pg.execute("select nts_status_code,nts_confirm_num,nts_sent_at,nts_accepted_at from tax_invoices where settlement_id=%s", (sid,)).fetchone() == accepted_facts


def test_claim_requires_exact_settlement_invoice_state_pairs(pg):
    import psycopg
    company, _, merchant, _, company_actor, _, actor, _ = parties(pg)
    for settlement_state, invoice_state in (("sent", "requested"), ("confirmed", "not_requested")):
        sid = settlement(pg, company, merchant, settlement_state, invoice_state)
        with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_STATE_CONFLICT"):
            with pg.transaction():
                pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, sid))

    direct = settlement(pg, company, merchant)
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_STATE_CONFLICT"):
        with pg.transaction():
            pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, direct))

    requested = settlement(pg, company, merchant)
    pg.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (company_actor, company, requested))
    claim = pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, requested)).fetchone()[0]
    pg.execute("select merchant_finalize_tax_invoice_issue(%s,%s,%s,%s,'rejected',null,null)",
               (actor, merchant, requested, claim["attempt_token"]))
    assert pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, requested)).fetchone()[0]["action"] == "issue"


def test_claim_fails_closed_on_legal_mismatch_and_rpc_scrubs_raw_provider_fields(pg):
    import psycopg
    company, _, merchant, _, company_actor, _, actor, _ = parties(pg)
    sid = settlement(pg, company, merchant)
    pg.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (company_actor, company, sid))
    first = pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, sid)).fetchone()[0]
    invoice_id = first["tax_invoice"]["id"]
    pg.execute("""update tax_invoices set provider_response='{"secret":"raw-pii"}'::jsonb,
               popbill_status_message='raw provider PII' where id=%s""", (invoice_id,))
    reconciled = pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, sid)).fetchone()[0]
    assert "provider_response" not in reconciled["tax_invoice"]
    assert "popbill_status_message" not in reconciled["tax_invoice"]

    pg.execute("set local greeneatgo.tax_invoice_migration_bypass='on'")
    pg.execute("update tax_invoices set vat_amount=0,total_amount=supply_amount where id=%s", (invoice_id,))
    with pytest.raises(psycopg.errors.RaiseException, match="TAX_INVOICE_LEGAL_FIELDS_MISMATCH"):
        with pg.transaction():
            pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, sid))


def test_apply_rejects_invalid_state_without_consuming_token_or_fabricating_time(pg):
    import psycopg
    company, _, merchant, _, company_actor, _, actor, _ = parties(pg)
    sid = settlement(pg, company, merchant)
    pg.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (company_actor, company, sid))
    claim = pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, sid)).fetchone()[0]
    token = uuid.UUID(claim["attempt_token"])
    for state in (None, 299, 306):
        with pytest.raises(psycopg.errors.RaiseException, match="POPBILL_INVALID_PROVIDER_STATE"):
            with pg.transaction():
                pg.execute("select merchant_apply_tax_invoice_status(%s,%s,%s,%s,null,null,null,null,null)",
                           (actor, merchant, sid, state))
        assert pg.execute("select issue_attempt_token from tax_invoices where settlement_id=%s", (sid,)).fetchone()[0] == token

    with pytest.raises(psycopg.errors.RaiseException, match="POPBILL_INVALID_PROVIDER_TIMESTAMP"):
        with pg.transaction():
            pg.execute("select merchant_apply_tax_invoice_status(%s,%s,%s,300,null,null,null,null,null)",
                       (actor, merchant, sid))
    assert pg.execute("select issued_at from tax_invoices where settlement_id=%s", (sid,)).fetchone()[0] is None


def test_concurrent_claim_has_one_issue_winner(settlement_db):
    import psycopg
    with psycopg.connect(settlement_db) as setup:
        company, _, merchant, _, company_actor, _, actor, _ = parties(setup)
        sid = settlement(setup, company, merchant)
        setup.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (company_actor, company, sid))
        setup.commit()

    def claim():
        with psycopg.connect(settlement_db) as conn:
            value = conn.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor,merchant,sid)).fetchone()[0]
            conn.commit()
            return value["action"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        actions = sorted(f.result(timeout=10) for f in (pool.submit(claim),pool.submit(claim)))
    assert actions == ["issue","reconcile"]


def test_company_monthly_usage_aggregates_seoul_month_employees_and_payments(pg):
    company, other_company, merchant, _, company_actor, _, merchant_actor, _ = parties(pg)
    employee_one = pg.execute(
        """insert into app_users(id,company_id,display_name,employee_no,department,role,status)
           values(gen_random_uuid(),%s,'Alice','E-1','Sales','employee','active') returning id""",
        (company,),
    ).fetchone()[0]
    employee_two = pg.execute(
        """insert into app_users(id,company_id,display_name,employee_no,department,role,status)
           values(gen_random_uuid(),%s,'Bob','E-2','Ops','employee','paused') returning id""",
        (company,),
    ).fetchone()[0]
    outsider = pg.execute(
        """insert into app_users(id,company_id,display_name,role,status)
           values(gen_random_uuid(),%s,'Other employee','employee','active') returning id""",
        (other_company,),
    ).fetchone()[0]

    # UTC timestamps straddle Seoul civil-month boundaries. Monetary snapshots are
    # authoritative; the refund reverses each burden independently.
    pg.execute(
        """insert into meal_transactions(
             user_id,company_id,merchant_id,amount,kind,pay_type,
             employee_paid_amount,company_subsidy_amount,restaurant_subsidy_amount,
             tax_type,supply_amount,vat_amount,total_amount,
             settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
           values
             (%s,%s,%s,-1000,'spend','ledger',300,600,100,'taxable',909,91,1000,'taxable',545,55,600,'2026-06-30 15:00:00+00'),
             (%s,%s,%s, 200,'refund','ledger',60,120,20,'taxable',182,18,200,'taxable',109,11,120,'2026-07-01 15:00:00+00'),
             (%s,%s,%s,-500,'spend','ledger',0,500,0,'tax_free',500,0,500,'tax_free',500,0,500,'2026-07-15 03:00:00+00'),
             (%s,%s,%s,-999,'spend','ledger',0,999,0,'tax_free',999,0,999,'tax_free',999,0,999,'2026-07-31 15:00:00+00'),
             (%s,%s,%s,-777,'spend','ledger',0,777,0,'tax_free',777,0,777,'tax_free',777,0,777,'2026-07-10 00:00:00+00')""",
        (
            employee_one, company, merchant,
            employee_one, company, merchant,
            employee_two, company, merchant,
            employee_two, company, merchant,
            outsider, other_company, merchant,
        ),
    )

    sid = settlement(pg, company, merchant, "sent", "not_requested")
    pg.execute("update settlements set period_ym='2026-07' where id=%s", (sid,))
    pg.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (company_actor, company, sid))
    pg.execute(
        """insert into settlement_payments(
             settlement_id,amount,deposited_at,match_method,confirmed_by,confirmed_at,created_by)
           values(%s,400,now(),'manual',%s,now(),%s),
                 (%s,900,now(),'manual',null,null,%s)""",
        (sid, merchant_actor, merchant_actor, sid, merchant_actor),
    )

    value = pg.execute(
        "select company_monthly_usage(%s,%s,'2026-07')", (company_actor, company)
    ).fetchone()[0]
    assert "company_id" not in value
    assert value["period"] == {
        "ym": "2026-07",
        "timezone": "Asia/Seoul",
        "start_at": "2026-06-30T15:00:00+00:00",
        "end_at": "2026-07-31T15:00:00+00:00",
    }
    assert value["summary"] == {
        "gross_spend_amount": 1300,
        "company_charge_amount": 980,
        "employee_paid_amount": 240,
        "transaction_count": 3,
        "spend_count": 2,
        "reversal_count": 1,
        "unique_users": 2,
        "used_employee_count": 2,
        "total_employee_count": 2,
        "active_employee_count": 1,
        "outstanding_settlement_amount": 700,
        "confirmed_payment_amount": 400,
    }
    assert [row["date"] for row in value["daily"]] == ["2026-07-01", "2026-07-02", "2026-07-15"]
    assert [row["display_name"] for row in value["employees"]] == ["Alice", "Bob"]
    alice = next(row for row in value["employees"] if row["display_name"] == "Alice")
    assert (alice["gross_spend_amount"], alice["company_charge_amount"], alice["employee_paid_amount"]) == (800, 480, 240)
    assert alice["transaction_count"] == 2 and alice["usage_days"] == 2
    settlements = value["settlements"]
    assert (settlements["count"], settlements["total_amount"], settlements["confirmed_payment_amount"], settlements["outstanding_amount"]) == (1, 1100, 400, 700)
    assert "latest_invoice" not in settlements


def test_company_monthly_usage_empty_month_is_stable_and_service_role_only(pg):
    company, _, _, _, company_actor, _, _, _ = parties(pg)
    value = pg.execute(
        "select company_monthly_usage(%s,%s,'2025-02')", (company_actor, company)
    ).fetchone()[0]
    assert value["daily"] == []
    assert value["employees"] == []
    assert value["summary"]["gross_spend_amount"] == 0
    assert pg.execute(
        "select has_function_privilege('authenticated','company_monthly_usage(uuid,uuid,text)','execute')"
    ).fetchone()[0] is False
    assert pg.execute(
        "select has_function_privilege('service_role','company_monthly_usage(uuid,uuid,text)','execute')"
    ).fetchone()[0] is True


def test_company_monthly_usage_rejects_invalid_month_and_unknown_company(pg):
    import psycopg

    company, _, _, _, company_actor, _, _, _ = parties(pg)
    with pytest.raises(psycopg.errors.RaiseException, match="COMPANY_USAGE_MONTH_INVALID"):
        with pg.transaction():
            pg.execute("select company_monthly_usage(%s,%s,'2026-13')", (company_actor, company))
    with pytest.raises(psycopg.errors.RaiseException, match="COMPANY_USAGE_ACTOR_FORBIDDEN"):
        with pg.transaction():
            pg.execute("select company_monthly_usage(%s,%s,'2026-07')", (company_actor, uuid.uuid4()))


def test_company_monthly_usage_rejects_cross_tenant_and_inactive_actors(pg):
    import psycopg

    company, _, _, _, actor, other_actor, _, _ = parties(pg)
    with pytest.raises(psycopg.errors.RaiseException, match="COMPANY_USAGE_ACTOR_FORBIDDEN"):
        with pg.transaction():
            pg.execute("select company_monthly_usage(%s,%s,'2026-07')", (other_actor, company))
    pg.execute("update app_users set status='paused' where id=%s", (actor,))
    with pytest.raises(psycopg.errors.RaiseException, match="COMPANY_USAGE_ACTOR_FORBIDDEN"):
        with pg.transaction():
            pg.execute("select company_monthly_usage(%s,%s,'2026-07')", (actor, company))


def test_company_monthly_usage_spend_users_invites_privacy_and_reconciliation(pg):
    company, other_company, merchant, _, actor, _, _, _ = parties(pg)
    no_usage = pg.execute(
        "insert into app_users(id,company_id,display_name,role,status) values(gen_random_uuid(),%s,'No usage','employee','active') returning id",
        (company,),
    ).fetchone()[0]
    paused = pg.execute(
        "insert into app_users(id,company_id,display_name,role,status) values(gen_random_uuid(),%s,'Paused','employee','paused') returning id",
        (company,),
    ).fetchone()[0]
    refund_only = pg.execute(
        "insert into app_users(id,company_id,display_name,role,status) values(gen_random_uuid(),%s,'Refund','employee',null) returning id",
        (company,),
    ).fetchone()[0]
    moved = pg.execute(
        "insert into app_users(id,company_id,display_name,employee_no,department,role,status) values(gen_random_uuid(),%s,'Moved','OLD','Old dept','employee','active') returning id",
        (company,),
    ).fetchone()[0]
    outsider = pg.execute(
        "insert into app_users(id,company_id,display_name,role,status) values(gen_random_uuid(),%s,'Outsider','employee','active') returning id",
        (other_company,),
    ).fetchone()[0]
    pg.execute(
        "insert into employee_bulk_invites(company_id,display_name,employee_no,phone) values(%s,'Invited','INV','01011112222')",
        (company,),
    )
    pg.execute(
        """insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,
             tax_type,supply_amount,vat_amount,total_amount,
             settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,
             employee_paid_amount,created_at)
           values(%s,%s,%s,-1000,'spend','ledger','tax_free',1000,0,1000,'tax_free',700,0,700,300,'2026-07-02 01:00+00'),
                 (%s,%s,%s,200,'refund','ledger','tax_free',200,0,200,'tax_free',140,0,140,60,'2026-07-03 01:00+00'),
                 (%s,%s,%s,-500,'spend','ledger','tax_free',500,0,500,'tax_free',500,0,500,0,'2026-07-04 01:00+00'),
                 (%s,%s,%s,-999,'spend','ledger','tax_free',999,0,999,'tax_free',999,0,999,0,'2026-07-05 01:00+00')""",
        (paused, company, merchant, refund_only, company, merchant, moved, company, merchant,
         outsider, other_company, merchant),
    )
    pg.execute(
        "update app_users set company_id=%s,employee_no='NEW',department='Secret' where id=%s",
        (other_company, moved),
    )

    value = pg.execute("select company_monthly_usage(%s,%s,'2026-07')", (actor, company)).fetchone()[0]
    summary, employees = value["summary"], value["employees"]
    assert (summary["unique_users"], summary["used_employee_count"]) == (2, 2)
    assert (summary["total_employee_count"], summary["active_employee_count"]) == (4, 1)
    ids = {uuid.UUID(row["user_id"]) for row in employees}
    assert no_usage not in ids and outsider not in ids and len(employees) == 3
    refund = next(row for row in employees if row["user_id"] == str(refund_only))
    assert refund["status"] == "unknown" and refund["gross_spend_amount"] == -200
    assert next(row for row in value["daily"] if row["date"] == "2026-07-03")["unique_users"] == 0
    moved_row = next(row for row in employees if row["user_id"] == str(moved))
    assert moved_row["status"] == "former"
    assert moved_row["employee_no"] is None and moved_row["department"] is None
    for field in ("gross_spend_amount", "company_charge_amount", "employee_paid_amount", "transaction_count"):
        assert sum(row[field] for row in employees) == summary[field]


def test_company_monthly_usage_cancellation_and_confirmed_overpayment(pg):
    company, _, merchant, other_merchant, actor, _, payment_actor, _ = parties(pg)
    employee = pg.execute(
        "insert into app_users(id,company_id,display_name,role,status) values(gen_random_uuid(),%s,'Employee','employee','active') returning id",
        (company,),
    ).fetchone()[0]
    pg.execute(
        """insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,
             tax_type,supply_amount,vat_amount,total_amount,
             settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,
             employee_paid_amount,created_at)
           values(%s,%s,%s,300,'cancel','ledger','tax_free',300,0,300,'tax_free',200,0,200,100,'2026-07-08 01:00+00')""",
        (employee, company, merchant),
    )
    cancelled = settlement(pg, company, other_merchant, "cancelled")
    live = settlement(pg, company, merchant, "sent")
    pg.execute("update settlements set period_ym='2026-07' where id in (%s,%s)", (cancelled, live))
    pg.execute(
        """insert into settlement_payments(settlement_id,amount,deposited_at,match_method,confirmed_by,confirmed_at,created_by)
           values(%s,1500,now(),'manual',%s,now(),%s)""",
        (live, payment_actor, payment_actor),
    )
    value = pg.execute("select company_monthly_usage(%s,%s,'2026-07')", (actor, company)).fetchone()[0]
    assert value["summary"]["gross_spend_amount"] == -300
    assert value["summary"]["unique_users"] == 0
    assert value["settlements"] == {"count": 1, "total_amount": 1100,
        "confirmed_payment_amount": 1500, "outstanding_amount": 0}


def legacy_test_settlement_demo_full_db_lifecycle_and_issued_reset_preservation(pg):
    import psycopg

    merchant = pg.execute("""insert into merchants(name,biz_reg_no,representative_name,address,business_type,
      business_item,tax_invoice_email,owner_phone,qr_token,view_token)
      values('Demo supplier','9998877777','Owner','Busan','Food','Meals','supplier@example.com',
      '01099998888',%s,%s) returning id""", (str(uuid.uuid4()), str(uuid.uuid4()))).fetchone()[0]
    actor = pg.execute("""insert into app_users(id,merchant_id,display_name,role,status)
      values(gen_random_uuid(),%s,'Demo merchant','merchant_admin','active') returning id""", (merchant,)).fetchone()[0]
    outsider_merchant = pg.execute("insert into merchants(name,qr_token,view_token) values('Other',%s,%s) returning id",
                                  (str(uuid.uuid4()), str(uuid.uuid4()))).fetchone()[0]
    outsider = pg.execute("""insert into app_users(id,merchant_id,display_name,role,status)
      values(gen_random_uuid(),%s,'Other','merchant_admin','active') returning id""", (outsider_merchant,)).fetchone()[0]

    seeded = pg.execute("select settlement_demo_seed(%s,%s)", (actor, merchant)).fetchone()[0]
    assert pg.execute("select has_function_privilege('authenticated','settlement_demo_seed(uuid,uuid)','execute')").fetchone()[0] is False
    assert pg.execute("select has_function_privilege('service_role','settlement_demo_seed(uuid,uuid)','execute')").fetchone()[0] is True
    assert seeded["stage"] == "seeded" and seeded["transaction_count"] == 4
    assert seeded["synthetic_transaction_user"] == "merchant-scoped demo company_admin app_users.id"
    assert pg.execute("select settlement_demo_seed(%s,%s)", (actor, merchant)).fetchone()[0]["run_id"] == seeded["run_id"]
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_DEMO_FORBIDDEN"):
        with pg.transaction():
            pg.execute("select settlement_demo_state(%s,%s)", (outsider, merchant))

    created = pg.execute("select settlement_demo_create(%s,%s)", (actor, merchant)).fetchone()[0]
    assert created["stage"] == "draft"
    assert (created["settlement"]["tx_count"], created["settlement"]["supply_amount"],
            created["settlement"]["vat_amount"], created["settlement"]["total_amount"]) == (4, 40000, 4000, 44000)
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_DEMO_STATE_CONFLICT"):
        with pg.transaction():
            pg.execute("select settlement_demo_create(%s,%s)", (actor, merchant))

    confirmed = pg.execute("select settlement_demo_confirm(%s,%s)", (actor, merchant)).fetchone()[0]
    assert confirmed["stage"] == "confirmed"
    sid = uuid.UUID(confirmed["settlement_id"])
    claim = pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, sid)).fetchone()[0]
    pg.execute("select merchant_finalize_tax_invoice_issue(%s,%s,%s,%s,'success',null,null)",
               (actor, merchant, sid, claim["attempt_token"]))
    issued = pg.execute("select settlement_demo_state(%s,%s)", (actor, merchant)).fetchone()[0]
    assert issued["stage"] == "issued"
    assert issued["settlement"]["tax_invoice_status"] == "issued"
    # Successful registration does not fabricate a provider timestamp; the stable
    # evidence shape keeps the field explicit until status refresh supplies one.
    assert issued["settlement"]["issued_at"] is None
    assert issued["settlement"]["nts_status"] is None
    assert "nts_confirm_num" not in issued["settlement"]
    assert issued["settlement"]["can_view_tax_invoice"] is True
    assert issued["settlement"]["can_download_tax_invoice_pdf"] is True
    assert not ({"invoicer_mgt_key", "popbill_status_code", "popbill_status_message", "provider_response"}
                & issued["settlement"].keys())
    pg.execute("""select merchant_apply_tax_invoice_status(%s,%s,%s,304,'SUC001','NTS-CONFIRM-1',
               '2026-07-28T01:02:00Z','2026-07-28T01:03:00Z','2026-07-28T01:04:00Z')""", (actor, merchant, sid))
    accepted = pg.execute("select settlement_demo_state(%s,%s)", (actor, merchant)).fetchone()[0]
    assert accepted["settlement"]["issued_at"] == "2026-07-28T01:02:00+00:00"
    assert accepted["settlement"]["tax_invoice_status"] == "nts_accepted"
    assert accepted["settlement"]["nts_status"] == "accepted"
    assert accepted["settlement"]["nts_confirm_num"] == "NTS-CONFIRM-1"
    paid = pg.execute("select settlement_demo_mark_paid(%s,%s)", (actor, merchant)).fetchone()[0]
    assert paid["stage"] == "paid" and paid["settlement"]["status"] == "paid"

    old_invoice = pg.execute("select id,invoicer_mgt_key from tax_invoices where settlement_id=%s", (sid,)).fetchone()
    fresh = pg.execute("select settlement_demo_reset(%s,%s)", (actor, merchant)).fetchone()[0]
    assert fresh["stage"] == "seeded" and fresh["period_ym"] != seeded["period_ym"]
    assert pg.execute("select id,invoicer_mgt_key from tax_invoices where settlement_id=%s", (sid,)).fetchone() == old_invoice
    assert pg.execute("select count(*) from settlements where id=%s", (sid,)).fetchone()[0] == 1


def legacy_test_settlement_demo_draft_reset_removes_only_demo_mutable_rows(pg):
    merchant = pg.execute("insert into merchants(name,qr_token,view_token) values('Draft demo',%s,%s) returning id",
                          (str(uuid.uuid4()), str(uuid.uuid4()))).fetchone()[0]
    actor = pg.execute("""insert into app_users(id,merchant_id,display_name,role,status)
      values(gen_random_uuid(),%s,'Draft actor','merchant_admin','active') returning id""", (merchant,)).fetchone()[0]
    first = pg.execute("select settlement_demo_seed(%s,%s)", (actor, merchant)).fetchone()[0]
    draft = pg.execute("select settlement_demo_create(%s,%s)", (actor, merchant)).fetchone()[0]
    old_sid = draft["settlement_id"]
    fresh = pg.execute("select settlement_demo_reset(%s,%s)", (actor, merchant)).fetchone()[0]
    assert fresh["stage"] == "seeded"
    assert pg.execute("select count(*) from settlements where id=%s", (old_sid,)).fetchone()[0] == 0
    assert pg.execute("select count(*) from settlement_demo_runs where id=%s", (first["run_id"],)).fetchone()[0] == 0


def legacy_test_settlement_demo_seed_skips_preexisting_qualifying_transaction_month(pg):
    merchant = pg.execute("insert into merchants(name,qr_token,view_token) values('Seed pollution demo',%s,%s) returning id",
                          (str(uuid.uuid4()), str(uuid.uuid4()))).fetchone()[0]
    demo_company = pg.execute(
        "select md5('settlement-demo-company:'||%s::uuid::text)::uuid", (merchant,)
    ).fetchone()[0]
    actor = pg.execute("""insert into app_users(id,merchant_id,display_name,role,status)
      values(gen_random_uuid(),%s,'Seed pollution actor','merchant_admin','active') returning id""", (merchant,)).fetchone()[0]
    pg.execute("""insert into companies(id,name,biz_reg_no,status)
      values(%s,'Preexisting demo company','1234567890','active') on conflict(id) do nothing""", (demo_company,))
    polluted_month = pg.execute("select (date_trunc('month',current_date)-interval '1 month')::date").fetchone()[0]
    polluted_tx = pg.execute("""insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,
      settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
      values(%s,%s,%s,-1100,'spend','ledger','taxable',1000,100,1100,
      (%s::date+interval '10 days')::timestamp at time zone 'Asia/Seoul') returning id""",
      (actor, demo_company, merchant, polluted_month)).fetchone()[0]

    seeded = pg.execute("select settlement_demo_seed(%s,%s)", (actor, merchant)).fetchone()[0]

    assert seeded["period_ym"] != polluted_month.strftime("%Y-%m")
    assert pg.execute("""select count(*) from settlement_demo_transactions dt
      join meal_transactions t on t.id=dt.transaction_id
      where t.merchant_id=%s and t.company_id=%s
        and t.created_at >= (%s::date::timestamp at time zone 'Asia/Seoul')
        and t.created_at < ((%s::date+interval '1 month')::timestamp at time zone 'Asia/Seoul')""",
      (merchant, demo_company, polluted_month, polluted_month)).fetchone()[0] == 0
    assert pg.execute("""select count(*) from meal_transactions
      where merchant_id=%s and company_id=%s
        and created_at >= (%s::date::timestamp at time zone 'Asia/Seoul')
        and created_at < ((%s::date+interval '1 month')::timestamp at time zone 'Asia/Seoul')""",
      (merchant, demo_company, polluted_month, polluted_month)).fetchone()[0] == 1
    assert pg.execute("select count(*) from meal_transactions where id=%s", (polluted_tx,)).fetchone()[0] == 1


def legacy_test_settlement_demo_rejects_polluted_period_without_creating_settlement(pg):
    import psycopg

    merchant = pg.execute("insert into merchants(name,qr_token,view_token) values('Polluted demo',%s,%s) returning id",
                          (str(uuid.uuid4()), str(uuid.uuid4()))).fetchone()[0]
    actor = pg.execute("""insert into app_users(id,merchant_id,display_name,role,status)
      values(gen_random_uuid(),%s,'Polluted actor','merchant_admin','active') returning id""", (merchant,)).fetchone()[0]
    seeded = pg.execute("select settlement_demo_seed(%s,%s)", (actor, merchant)).fetchone()[0]
    run = pg.execute("select company_id,period_from from settlement_demo_runs where id=%s", (seeded["run_id"],)).fetchone()
    pg.execute("""insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,
      settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
      values(%s,%s,%s,-1100,'spend','ledger','taxable',1000,100,1100,
      %s::timestamp at time zone 'Asia/Seoul')""", (actor, run[0], merchant, run[1] + timedelta(days=10)))

    with pytest.raises(psycopg.errors.RaiseException, match="DEMO_PERIOD_TRANSACTION_CONFLICT"):
        with pg.transaction():
            pg.execute("select settlement_demo_create(%s,%s)", (actor, merchant))

    assert pg.execute("select count(*) from settlements where merchant_id=%s and company_id=%s",
                      (merchant, run[0])).fetchone()[0] == 0


def legacy_test_settlement_demo_two_merchants_have_isolated_synthetic_identities(pg):
    rows = []
    for suffix in ("A", "B"):
        merchant = pg.execute(
            "insert into merchants(name,qr_token,view_token) values(%s,%s,%s) returning id",
            (f"Isolation {suffix}", str(uuid.uuid4()), str(uuid.uuid4())),
        ).fetchone()[0]
        actor = pg.execute("""insert into app_users(id,merchant_id,display_name,role,status)
          values(gen_random_uuid(),%s,%s,'merchant_admin','active') returning id""",
          (merchant, f"Actor {suffix}")).fetchone()[0]
        state = pg.execute("select settlement_demo_seed(%s,%s)", (actor, merchant)).fetchone()[0]
        row = pg.execute("""select r.merchant_id,r.company_id,r.company_actor_id,r.transaction_user_id,
          c.name,c.biz_reg_no,u.company_id,
          (select count(*) from settlement_demo_transactions dt join meal_transactions t
             on t.id=dt.transaction_id where dt.run_id=r.id and t.user_id=r.transaction_user_id
             and t.company_id=r.company_id and t.merchant_id=r.merchant_id)
          from settlement_demo_runs r join companies c on c.id=r.company_id
          join app_users u on u.id=r.company_actor_id where r.id=%s""", (state["run_id"],)).fetchone()
        rows.append(row)

    assert rows[0][1:4] != rows[1][1:4]
    assert rows[0][5] != rows[1][5]
    for merchant_id, company_id, company_actor_id, transaction_user_id, name, biz_no, user_company, tx_count in rows:
        assert company_actor_id == transaction_user_id
        assert user_company == company_id
        assert "DEMO" in name and "데모" in name
        assert len(biz_no) == 10 and biz_no.isdigit()
        digits = [int(value) for value in biz_no]
        weighted = sum(value * weight for value, weight in zip(digits[:9], [1, 3, 7, 1, 3, 7, 1, 3, 5]))
        weighted += (digits[8] * 5) // 10
        assert (weighted + digits[9]) % 10 == 0
        assert tx_count == 4


def legacy_test_settlement_demo_deferred_integrity_guards_reject_cross_ownership(pg):
    import psycopg

    merchant = pg.execute("insert into merchants(name,qr_token,view_token) values('Guard demo',%s,%s) returning id",
                          (str(uuid.uuid4()), str(uuid.uuid4()))).fetchone()[0]
    actor = pg.execute("""insert into app_users(id,merchant_id,display_name,role,status)
      values(gen_random_uuid(),%s,'Guard actor','merchant_admin','active') returning id""", (merchant,)).fetchone()[0]
    state = pg.execute("select settlement_demo_seed(%s,%s)", (actor, merchant)).fetchone()[0]
    run_id = state["run_id"]
    tx_id = pg.execute("select transaction_id from settlement_demo_transactions where run_id=%s limit 1", (run_id,)).fetchone()[0]

    for statement, params in (
        ("update settlement_demo_runs set transaction_user_id=%s where id=%s", (actor, run_id)),
        ("update meal_transactions set flags=flags-'run_id' where id=%s", (tx_id,)),
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_DEMO_MEMBERSHIP_INVALID"):
            with pg.transaction():
                pg.execute(statement, params)
                pg.execute("set constraints all immediate")

    other_company = pg.execute("insert into companies(name) values('Not demo owner') returning id").fetchone()[0]
    wrong_settlement = pg.execute("""insert into settlements(company_id,merchant_id,period_ym,period_from,period_to,
      tx_count,supply_amount,vat_amount,total_amount,status) values(%s,%s,%s,current_date,current_date,
      0,0,0,0,'draft') returning id""", (other_company, merchant, str(uuid.uuid4()))).fetchone()[0]
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_DEMO_MEMBERSHIP_INVALID"):
        with pg.transaction():
            pg.execute("update settlement_demo_runs set settlement_id=%s where id=%s", (wrong_settlement, run_id))
            pg.execute("set constraints all immediate")


def legacy_test_settlement_demo_reset_validates_membership_and_is_retry_safe(pg):
    import psycopg

    merchant = pg.execute("insert into merchants(name,qr_token,view_token) values('Retry demo',%s,%s) returning id",
                          (str(uuid.uuid4()), str(uuid.uuid4()))).fetchone()[0]
    actor = pg.execute("""insert into app_users(id,merchant_id,display_name,role,status)
      values(gen_random_uuid(),%s,'Retry actor','merchant_admin','active') returning id""", (merchant,)).fetchone()[0]
    seeded = pg.execute("select settlement_demo_seed(%s,%s)", (actor, merchant)).fetchone()[0]
    tx_id = pg.execute("select transaction_id from settlement_demo_transactions where run_id=%s limit 1",
                       (seeded["run_id"],)).fetchone()[0]
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_DEMO_MEMBERSHIP_INVALID"):
        with pg.transaction():
            pg.execute("update meal_transactions set flags=flags-'run_id' where id=%s", (tx_id,))
            pg.execute("select settlement_demo_reset(%s,%s,%s)", (actor, merchant, "invalid-membership"))
    assert pg.execute("select count(*) from meal_transactions where id=%s", (tx_id,)).fetchone()[0] == 1

    first = pg.execute("select settlement_demo_reset(%s,%s,%s)", (actor, merchant, "retry-key-1")).fetchone()[0]
    duplicate = pg.execute("select settlement_demo_reset(%s,%s,%s)", (actor, merchant, "retry-key-1")).fetchone()[0]
    assert duplicate["run_id"] == first["run_id"]
    assert pg.execute("select count(*) from settlement_demo_reset_requests where merchant_id=%s",
                      (merchant,)).fetchone()[0] == 1


def legacy_test_settlement_demo_create_rolls_back_on_tampered_creator_result(pg):
    import psycopg

    merchant = pg.execute("insert into merchants(name,qr_token,view_token) values('TOCTOU demo',%s,%s) returning id",
                          (str(uuid.uuid4()), str(uuid.uuid4()))).fetchone()[0]
    actor = pg.execute("""insert into app_users(id,merchant_id,display_name,role,status)
      values(gen_random_uuid(),%s,'TOCTOU actor','merchant_admin','active') returning id""", (merchant,)).fetchone()[0]
    seeded = pg.execute("select settlement_demo_seed(%s,%s)", (actor, merchant)).fetchone()[0]
    company_id = seeded["company_id"]
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_DEMO_CREATE_RESULT_MISMATCH"):
        with pg.transaction():
            pg.execute("alter function settlement_demo_create_merchant_settlement(uuid,uuid,date,date) rename to demo_test_real_create")
            pg.execute("""create function settlement_demo_create_merchant_settlement(uuid,uuid,date,date) returns jsonb
              language plpgsql security definer set search_path=pg_catalog,public as $$
              declare result jsonb;
              begin
                result:=public.demo_test_real_create($1,$2,$3,$4);
                return jsonb_set(result,'{tx_count}',to_jsonb((result->>'tx_count')::int+1));
              end $$""")
            pg.execute("select settlement_demo_create(%s,%s)", (actor, merchant))
    assert pg.execute("select count(*) from settlements where merchant_id=%s and company_id=%s",
                      (merchant, company_id)).fetchone()[0] == 0


def demo_actual_parties(pg, suffix=""):
    company = pg.execute("""insert into companies(name,biz_reg_no,representative_name,address,business_type,business_item,
      tax_invoice_email,contact_name,contact_phone,status) values(%s,'1234567890','Recipient','Seoul','Services','Meals',
      'recipient@example.com','Billing','01012345678','active') returning id""", (f"Actual company {suffix}",)).fetchone()[0]
    merchant = pg.execute("""insert into merchants(name,biz_reg_no,representative_name,address,business_type,business_item,
      tax_invoice_email,owner_phone,qr_token,view_token) values(%s,'9998877777','Supplier','Busan','Food','Meals',
      'supplier@example.com','01099998888',%s,%s) returning id""",
      (f"Actual merchant {suffix}", str(uuid.uuid4()), str(uuid.uuid4()))).fetchone()[0]
    actor = pg.execute("insert into app_users(id,merchant_id,display_name,role,status) values(gen_random_uuid(),%s,'merchant','merchant_admin','active') returning id", (merchant,)).fetchone()[0]
    admin = pg.execute("insert into app_users(id,company_id,display_name,role,status) values(gen_random_uuid(),%s,'admin','company_admin','active') returning id", (company,)).fetchone()[0]
    employees = [pg.execute("insert into app_users(id,company_id,display_name,role,status) values(gen_random_uuid(),%s,%s,%s,'active') returning id",
      (company, f"person-{i}", "employee" if i == 0 else "customer")).fetchone()[0] for i in range(2)]
    pg.execute("insert into merchant_companies(merchant_id,company_id,status,created_by) values(%s,%s,'active',%s)", (merchant, company, actor))
    ym = pg.execute("select to_char(date_trunc('month',current_date)-interval '1 month','YYYY-MM')").fetchone()[0]
    return company, merchant, actor, admin, employees, ym


def test_settlement_demo_actual_options_seed_privacy_distribution_and_no_balance_change(pg):
    company, merchant, actor, admin, employees, ym = demo_actual_parties(pg, "privacy")
    state = pg.execute("select settlement_demo_state(%s,%s)", (actor, merchant)).fetchone()[0]
    option = state["options"][0]
    assert option == {"company_id": str(company), "company_name": "Actual company privacy",
      "active_employee_customer_count": 2, "active_company_admin_available": True,
      "invoice_legal_profile_complete": True, "eligible": True, "reason": None}
    assert all(str(user) not in str(state) for user in [admin, *employees])
    before = {user: pg.execute("select coalesce(sum(amount),0) from meal_transactions where user_id=%s", (user,)).fetchone()[0] for user in employees}
    seeded = pg.execute("select settlement_demo_seed(%s,%s,%s,%s)", (actor, merchant, company, ym)).fetchone()[0]
    assert 6 <= seeded["transaction_count"] <= 12
    rows = pg.execute("""select distinct t.user_id,t.amount,t.product_price,t.settlement_supply_amount,
      t.settlement_vat_amount,t.settlement_total_amount,extract(isodow from t.created_at at time zone 'Asia/Seoul')
      from settlement_demo_transactions d join meal_transactions t on t.id=d.transaction_id where d.run_id=%s""", (seeded["run_id"],)).fetchall()
    assert {row[0] for row in rows} == set(employees)
    assert all(row[1] == 0 and row[2] in range(8000, 15001, 1000) and row[3] + row[4] == row[5]
               and row[3] == round(row[5] / 1.1) and 1 <= row[6] <= 5 for row in rows)
    after = {user: pg.execute("select coalesce(sum(amount),0) from meal_transactions where user_id=%s", (user,)).fetchone()[0] for user in employees}
    assert before == after and all(str(user) not in str(seeded) for user in employees)
    duplicate = pg.execute("select settlement_demo_seed(%s,%s,%s,%s)", (actor, merchant, company, ym)).fetchone()[0]
    assert duplicate["run_id"] == seeded["run_id"] and duplicate["aggregate"] == seeded["aggregate"]


def test_settlement_demo_eligibility_and_tenant_fail_closed(pg):
    import psycopg
    company, merchant, actor, admin, employees, ym = demo_actual_parties(pg, "eligibility")
    pg.execute("update companies set address=' ' where id=%s", (company,))
    option = pg.execute("select settlement_demo_state(%s,%s)", (actor, merchant)).fetchone()[0]["options"][0]
    assert option["eligible"] is False and option["reason"] == "BUSINESS_PROFILE_INCOMPLETE"
    with pytest.raises(psycopg.errors.RaiseException, match="BUSINESS_PROFILE_INCOMPLETE"):
      with pg.transaction(): pg.execute("select settlement_demo_seed(%s,%s,%s,%s)", (actor, merchant, company, ym))
    pg.execute("update companies set address='Seoul' where id=%s", (company,)); pg.execute("update app_users set status='paused' where id=%s", (admin,))
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_DEMO_COMPANY_ADMIN_REQUIRED"):
      with pg.transaction(): pg.execute("select settlement_demo_seed(%s,%s,%s,%s)", (actor, merchant, company, ym))
    pg.execute("update app_users set status='active' where id=%s", (admin,)); pg.execute("update app_users set status='paused' where id=any(%s)", (employees,))
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_DEMO_EMPLOYEE_REQUIRED"):
      with pg.transaction(): pg.execute("select settlement_demo_seed(%s,%s,%s,%s)", (actor, merchant, company, ym))
    other = pg.execute("insert into merchants(name,qr_token,view_token) values('other',%s,%s) returning id", (str(uuid.uuid4()), str(uuid.uuid4()))).fetchone()[0]
    other_actor = pg.execute("insert into app_users(id,merchant_id,display_name,role,status) values(gen_random_uuid(),%s,'other','merchant_admin','active') returning id", (other,)).fetchone()[0]
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_DEMO_COMPANY_INELIGIBLE"):
      with pg.transaction(): pg.execute("select settlement_demo_seed(%s,%s,%s,%s)", (other_actor, other, company, ym))


def test_settlement_demo_pollution_validation_membership_and_reset_lifecycle(pg):
    import psycopg
    company, merchant, actor, admin, employees, ym = demo_actual_parties(pg, "lifecycle")
    current = pg.execute("select to_char(current_date,'YYYY-MM')").fetchone()[0]
    for invalid in ("2026-13", current, "2020-01"):
      with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_INPUT_INVALID"):
        with pg.transaction(): pg.execute("select settlement_demo_seed(%s,%s,%s,%s)", (actor, merchant, company, invalid))
    start = date.fromisoformat(ym + "-01")
    pg.execute("""insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,
      settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
      values(%s,%s,%s,-1100,'spend','ledger','taxable',1000,100,1100,%s::timestamp at time zone 'Asia/Seoul')""",
      (employees[0], company, merchant, start + timedelta(days=2)))
    with pytest.raises(psycopg.errors.RaiseException, match="DEMO_PERIOD_TRANSACTION_CONFLICT"):
      with pg.transaction(): pg.execute("select settlement_demo_seed(%s,%s,%s,%s)", (actor, merchant, company, ym))
    pg.execute("delete from meal_transactions where merchant_id=%s and company_id=%s", (merchant, company))
    seeded = pg.execute("select settlement_demo_seed(%s,%s,%s,%s)", (actor, merchant, company, ym)).fetchone()[0]
    tx = pg.execute("select transaction_id from settlement_demo_transactions where run_id=%s limit 1", (seeded["run_id"],)).fetchone()[0]
    with pytest.raises(psycopg.errors.RaiseException, match="SETTLEMENT_DEMO_MEMBERSHIP_INVALID"):
      with pg.transaction():
        pg.execute("update meal_transactions set user_id=%s where id=%s", (actor, tx)); pg.execute("set constraints all immediate")
    created = pg.execute("select settlement_demo_create(%s,%s)", (actor, merchant)).fetchone()[0]
    confirmed = pg.execute("select settlement_demo_confirm(%s,%s)", (actor, merchant)).fetchone()[0]
    assert created["settlement"]["tx_count"] == seeded["transaction_count"]
    sid = confirmed["settlement_id"]
    empty = pg.execute("select settlement_demo_reset(%s,%s,%s)", (actor, merchant, "confirmed-reset")).fetchone()[0]
    assert empty["stage"] == "empty" and pg.execute("select count(*) from settlements where id=%s", (sid,)).fetchone()[0] == 1
    assert pg.execute("select count(*) from tax_invoices where settlement_id=%s", (sid,)).fetchone()[0] == 1
    assert pg.execute("select settlement_demo_reset(%s,%s,%s)", (actor, merchant, "confirmed-reset")).fetchone()[0]["stage"] == "empty"
    older = pg.execute("select to_char(date_trunc('month',current_date)-interval '2 months','YYYY-MM')").fetchone()[0]
    draft = pg.execute("select settlement_demo_seed(%s,%s,%s,%s)", (actor, merchant, company, older)).fetchone()[0]
    pg.execute("select settlement_demo_create(%s,%s)", (actor, merchant))
    assert pg.execute("select settlement_demo_reset(%s,%s,%s)", (actor, merchant, "draft-reset")).fetchone()[0]["stage"] == "empty"
    assert pg.execute("select count(*) from settlement_demo_runs where id=%s", (draft["run_id"],)).fetchone()[0] == 0
    assert pg.execute("select count(*) from companies where id=%s", (company,)).fetchone()[0] == 1


def test_settlement_demo_deferred_full_set_contract_and_trigger_metadata(pg):
    import psycopg
    company, merchant, actor, _, employees, ym = demo_actual_parties(pg, "full-set")
    seeded = pg.execute("select settlement_demo_seed(%s,%s,%s,%s)", (actor, merchant, company, ym)).fetchone()[0]
    run_id = seeded["run_id"]
    tx = pg.execute("select transaction_id from settlement_demo_transactions where run_id=%s order by transaction_id limit 1", (run_id,)).fetchone()[0]

    for statement, params, marker in (
        ("update meal_transactions set created_at=created_at+interval '1 month' where id=%s", (tx,), "DEMO_PERIOD_TRANSACTION_CONFLICT"),
        ("delete from settlement_demo_transactions where run_id=%s and transaction_id=%s", (run_id, tx), "DEMO_PERIOD_TRANSACTION_CONFLICT"),
        ("update companies set status='suspended' where id=%s", (company,), "SETTLEMENT_DEMO_MEMBERSHIP_INVALID"),
        ("update merchant_companies set status='paused' where merchant_id=%s and company_id=%s", (merchant, company), "SETTLEMENT_DEMO_MEMBERSHIP_INVALID"),
    ):
        with pytest.raises(psycopg.errors.RaiseException, match=marker):
            with pg.transaction():
                pg.execute(statement, params)
                pg.execute("set constraints all immediate")

    triggers = dict(pg.execute("""select tgname, tgdeferrable and tginitdeferred from pg_trigger
      where tgname like 'settlement_demo_%_integrity' or tgname in
        ('settlement_demo_companies_integrity','settlement_demo_contracts_integrity')""").fetchall())
    assert all(triggers[name] for name in (
        "settlement_demo_runs_integrity", "settlement_demo_transactions_integrity",
        "settlement_demo_users_integrity", "settlement_demo_settlements_integrity",
        "settlement_demo_meal_transactions_integrity", "settlement_demo_companies_integrity",
        "settlement_demo_contracts_integrity",
    ))
    for signature in (
        "settlement_demo_validate_run(uuid)", "settlement_demo_state(uuid,uuid)",
        "settlement_demo_seed(uuid,uuid,uuid,text)", "settlement_demo_create(uuid,uuid)",
    ):
        assert pg.execute("select has_function_privilege('authenticated',%s,'execute')", (signature,)).fetchone()[0] is False
    assert pg.execute("""select bool_and(proconfig @> array['search_path=pg_catalog, public']::text[]
      or proconfig @> array['search_path=pg_catalog,public']::text[])
      from pg_proc where proname like 'settlement_demo_%' and prosecdef""").fetchone()[0] is True


def test_settlement_demo_two_connection_pollution_commit_after_create_is_rejected(settlement_db):
    import psycopg
    with psycopg.connect(settlement_db) as setup:
        company, merchant, actor, _, employees, ym = demo_actual_parties(setup, "concurrent-full-set")
        seeded = setup.execute("select settlement_demo_seed(%s,%s,%s,%s)", (actor, merchant, company, ym)).fetchone()[0]
        period_from = date.fromisoformat(seeded["period_from"])
        setup.commit()

    with psycopg.connect(settlement_db) as creator, psycopg.connect(settlement_db) as polluter:
        created = creator.execute("select settlement_demo_create(%s,%s)", (actor, merchant)).fetchone()[0]
        polluter.execute("""insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,
          settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
          values(%s,%s,%s,0,'spend','ledger','taxable',1000,100,1100,
          %s::timestamp at time zone 'Asia/Seoul')""", (employees[0], company, merchant, period_from + timedelta(days=3)))
        with pytest.raises(psycopg.errors.RaiseException, match="DEMO_PERIOD_TRANSACTION_CONFLICT"):
            polluter.commit()
        creator.commit()
        sid = created["settlement_id"]
    with psycopg.connect(settlement_db) as verify:
        assert verify.execute("select count(*) from settlements where id=%s", (sid,)).fetchone()[0] == 1
        assert verify.execute("""select count(*) from meal_transactions where merchant_id=%s and company_id=%s
          and flags->>'settlement_demo' is distinct from 'true' and created_at >= (%s::date::timestamp at time zone 'Asia/Seoul')
          and created_at < ((%s::date+interval '1 month')::timestamp at time zone 'Asia/Seoul')""",
          (merchant, company, period_from, period_from)).fetchone()[0] == 0


def test_settlement_demo_seed_and_reset_preserve_wallet_and_unrelated_ledgers(pg):
    company, merchant, actor, _, employees, ym = demo_actual_parties(pg, "wallet")
    pg.execute("update app_users set point_balance=5000,point_reserved=1200 where id=%s", (employees[0],))
    def snapshot():
        return (
            pg.execute("select array_agg(row(id,point_balance,point_reserved) order by id) from app_users where id=any(%s)", (employees,)).fetchone()[0],
            pg.execute("select count(*) from point_transactions where user_id=any(%s)", (employees,)).fetchone()[0],
            pg.execute("select count(*) from payment_orders where user_id=any(%s)", (employees,)).fetchone()[0],
            pg.execute("select count(*) from settlement_payments sp join settlements s on s.id=sp.settlement_id where s.company_id=%s", (company,)).fetchone()[0],
        )
    before = snapshot()
    seeded = pg.execute("select settlement_demo_seed(%s,%s,%s,%s)", (actor, merchant, company, ym)).fetchone()[0]
    rows = pg.execute("""select t.kind,t.settlement_tax_type,t.settlement_supply_amount,
      t.settlement_vat_amount,t.settlement_total_amount from settlement_demo_transactions d
      join meal_transactions t on t.id=d.transaction_id where d.run_id=%s""", (seeded["run_id"],)).fetchall()
    assert rows and all(kind == 'spend' and tax_type == 'taxable' and supply + vat == total for kind,tax_type,supply,vat,total in rows)
    aggregate = seeded["aggregate"]
    assert (sum(row[2] for row in rows), sum(row[3] for row in rows), sum(row[4] for row in rows)) == (
        aggregate["supply_amount"], aggregate["vat_amount"], aggregate["total_amount"])
    pg.execute("select settlement_demo_reset(%s,%s,%s)", (actor, merchant, "wallet-reset"))
    assert snapshot() == before


def test_settlement_demo_migration_avoids_extension_schema_random_bytes():
    """Supabase installs pgcrypto helpers outside this function search path."""
    migration = (MIGRATIONS / "0042_settlement_demo.sql").read_text()
    assert "gen_random_bytes" not in migration
    assert "pg_catalog.random()" in migration


def test_settlement_demo_state_is_volatile_for_postgrest(pg):
    volatility = pg.execute(
        "select provolatile from pg_proc where oid='public.settlement_demo_state(uuid,uuid)'::regprocedure"
    ).fetchone()[0]
    assert volatility == "v"


def test_demo_usage_details_are_sanitized_exact_and_survive_settlement_archive_semantics(pg):
    company, merchant, actor, admin, employees, ym = demo_actual_parties(pg, "usage-details")
    empty = pg.execute("select settlement_demo_state(%s,%s)", (actor, merchant)).fetchone()[0]
    assert empty["stage"] == "empty" and empty["transactions"] == []

    period_from = date.fromisoformat(ym + "-01")
    period_to = pg.execute("select (%s::date+interval '1 month - 1 day')::date", (period_from,)).fetchone()[0]
    run_id = pg.execute("""insert into settlement_demo_runs
      (merchant_id,company_id,company_actor_id,period_from,period_to,period_ym,created_by)
      values(%s,%s,%s,%s,%s,%s,%s) returning id""",
      (merchant, company, admin, period_from, period_to, ym, actor)).fetchone()[0]
    amounts = [11000, 11000, 11000, 12000, 13000, 13000]
    tx_ids = []
    for index, total in enumerate(amounts, start=1):
        supply = round(total / 1.1)
        tx_id = pg.execute("""insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,tx_code,
          meal_window,flags,idempotency_key,product_name,product_price,pay_type,tax_type,supply_amount,vat_amount,
          total_amount,settlement_tax_type,settlement_supply_amount,settlement_vat_amount,
          settlement_total_amount,created_at) values(%s,%s,%s,0,'spend',%s,'중식',
          jsonb_build_object('settlement_demo',true,'run_id',%s::text),%s,'정산 데모 식사',%s,
          'ledger','taxable',%s,%s,%s,'taxable',%s,%s,%s,%s::date::timestamp at time zone 'Asia/Seoul') returning id""",
          (employees[(index-1) % len(employees)], company, merchant, f"DETAIL{index:02d}",
           str(run_id), f"detail-demo:{run_id}:{index}", total,
           supply, total-supply, total, supply, total-supply, total, period_from + timedelta(days=index+10))).fetchone()[0]
        tx_ids.append(tx_id)
        pg.execute("insert into settlement_demo_transactions(run_id,transaction_id) values(%s,%s)", (run_id, tx_id))

    state = pg.execute("select settlement_demo_state(%s,%s)", (actor, merchant)).fetchone()[0]
    details = state["transactions"]
    assert len(details) == 6
    assert [item["display_sequence"] for item in details] == list(range(1, 7))
    labels = [item["user_label"] for item in details]
    assert set(labels) == {"시연 사용자 1", "시연 사용자 2"}
    assert labels[0] == labels[2] == labels[4] and labels[1] == labels[3] == labels[5]
    assert labels[0] != labels[1]
    assert all(item["description"] == "시연 식대" and item["kind"] == "spend" for item in details)
    assert sum(item["supply_amount"] for item in details) == 64545
    assert sum(item["vat_amount"] for item in details) == 6455
    assert sum(item["total_amount"] for item in details) == 71000
    assert state["aggregate"]["total_amount"] == 71000

    allowed = {"display_sequence", "user_label", "used_at", "description", "kind",
               "supply_amount", "vat_amount", "total_amount"}
    assert all(set(item) == allowed for item in details)
    serialized = str(details)
    forbidden_keys = {"id", "transaction_id", "user_id", "name", "email", "phone", "flags",
                      "is_demo", "provider", "tx_code", "idempotency_key", "pay_type"}
    assert all(key not in allowed for key in forbidden_keys)
    assert all(str(value) not in serialized for value in [admin, *employees])
    assert all(value not in serialized for value in ["person-0", "person-1", "recipient@example.com", "01012345678"])

    created = pg.execute("select settlement_demo_create(%s,%s)", (actor, merchant)).fetchone()[0]
    assert created["settlement"]["total_amount"] == 71000
    assert sum(item["total_amount"] for item in created["transactions"]) == 71000
    confirmed = pg.execute("select settlement_demo_confirm(%s,%s)", (actor, merchant)).fetchone()[0]
    assert confirmed["stage"] == "confirmed" and len(confirmed["transactions"]) == 6
    archived = pg.execute("select settlement_demo_reset(%s,%s,%s)", (actor, merchant, "usage-archive")).fetchone()[0]
    assert archived["stage"] == "empty" and archived["transactions"] == []
    assert pg.execute("select is_current from settlement_demo_runs where id=%s", (run_id,)).fetchone()[0] is False
    replay = pg.execute("select settlement_demo_reset(%s,%s,%s)", (actor, merchant, "usage-archive")).fetchone()[0]
    assert replay["stage"] == "empty" and replay["transactions"] == []


def test_demo_usage_detail_migration_replay_preserves_volatility_and_grants(pg):
    migration = (MIGRATIONS / "0046_settlement_demo_usage_details.sql").read_text(encoding="utf-8")
    pg.execute(migration)
    pg.execute(migration)
    rows = pg.execute("""select proname,provolatile from pg_proc where oid in
      ('public.settlement_demo_state(uuid,uuid)'::regprocedure,
       'public.settlement_demo_state_base(uuid,uuid)'::regprocedure) order by proname""").fetchall()
    assert rows == [("settlement_demo_state", "v"), ("settlement_demo_state_base", "v")]
    assert pg.execute("select has_function_privilege('service_role','settlement_demo_state(uuid,uuid)','execute')").fetchone()[0] is True
    assert pg.execute("select has_function_privilege('service_role','settlement_demo_state_base(uuid,uuid)','execute')").fetchone()[0] is False
    assert pg.execute("select has_function_privilege('authenticated','settlement_demo_state(uuid,uuid)','execute')").fetchone()[0] is False


def test_demo_visible_reads_integrate_with_generic_settlement_but_not_limits(pg):
    import psycopg

    company, merchant, actor, company_actor, _, ym = demo_actual_parties(pg, "isolation")
    seeded = pg.execute(
        "select settlement_demo_seed(%s,%s,%s,%s)", (actor, merchant, company, ym)
    ).fetchone()[0]
    run_id = seeded["run_id"]
    demo_count = seeded["transaction_count"]

    assert pg.execute("""select count(*) from meal_transactions t
      join settlement_demo_transactions d on d.transaction_id=t.id
      where d.run_id=%s and t.is_demo""", (run_id,)).fetchone()[0] == demo_count
    assert pg.execute("""select count(*) from normal_meal_transactions t
      join settlement_demo_transactions d on d.transaction_id=t.id where d.run_id=%s""",
      (run_id,)).fetchone()[0] == 0
    signed_total = pg.execute("""select coalesce(sum(case when t.kind='spend' then t.settlement_total_amount
      else -t.settlement_total_amount end),0) from meal_transactions t
      join settlement_demo_transactions d on d.transaction_id=t.id where d.run_id=%s""",
      (run_id,)).fetchone()[0]
    assert pg.execute("select merchant_transaction_count(%s)", (merchant,)).fetchone()[0] == demo_count
    assert pg.execute("select merchant_payment_feed_count(%s)", (merchant,)).fetchone()[0] == demo_count
    summary = pg.execute(
        "select merchant_ledger_summary(%s,%s,%s::date,(%s::date+interval '1 month - 1 day')::date)",
        (merchant, company, seeded["period_from"], seeded["period_from"]),
    ).fetchone()[0]
    assert summary["total_count"] == demo_count and summary["total_amount"] == signed_total
    usage = pg.execute(
        "select company_monthly_usage(%s,%s,%s)", (company_actor, company, ym)
    ).fetchone()[0]
    assert usage["summary"]["transaction_count"] == demo_count
    assert usage["summary"]["gross_spend_amount"] == signed_total
    # Demo usage remains inert for customer limits, but is intentionally eligible
    # for the ordinary merchant settlement workflow during development.
    assert pg.execute("""select coalesce(sum(abs(amount)),0) from normal_meal_transactions
      where company_id=%s and created_at >= %s::date""", (company, seeded["period_from"])).fetchone()[0] == 0
    normal = pg.execute("select create_merchant_settlement(%s,%s,%s,%s)",
      (merchant, company, seeded["period_from"], seeded["period_to"])).fetchone()[0]
    assert normal["is_demo"] is False
    assert normal["tx_count"] == demo_count and normal["total_amount"] == signed_total

    created = pg.execute("select settlement_demo_create(%s,%s)", (actor, merchant)).fetchone()[0]
    sid = created["settlement_id"]
    demo_tx_id = pg.execute(
        "select transaction_id from settlement_demo_transactions where run_id=%s limit 1", (run_id,)
    ).fetchone()[0]
    assert pg.execute("select is_demo from settlements where id=%s", (sid,)).fetchone()[0] is True
    assert pg.execute("select count(*) from normal_settlements where id=%s", (sid,)).fetchone()[0] == 0
    for statement, value, marker in (
        ("update meal_transactions set is_demo=false where id=%s", demo_tx_id, "DEMO_TRANSACTION_MARKER_IMMUTABLE"),
        ("update settlements set is_demo=false where id=%s", sid, "DEMO_SETTLEMENT_MARKER_IMMUTABLE"),
    ):
        with pytest.raises(psycopg.errors.RaiseException, match=marker):
            with pg.transaction():
                pg.execute(statement, (value,))
    month = pg.execute(
        "select company_settlement_month_summary(%s,%s)", (company, ym)
    ).fetchone()[0]
    assert month["settlement_count"] == 1
    assert pg.execute("select count(*) from normal_settlements where id=%s", (normal["id"],)).fetchone()[0] == 1

    pg.execute("select settlement_demo_confirm(%s,%s)", (actor, merchant))
    invoice_id = pg.execute(
        "select id from tax_invoices where settlement_id=%s and document_type='original'", (sid,)
    ).fetchone()[0]
    reset = pg.execute(
        "select settlement_demo_reset(%s,%s,%s)", (actor, merchant, "isolation-audit-reset")
    ).fetchone()[0]
    assert reset["stage"] == "empty"
    assert pg.execute("select is_current from settlement_demo_runs where id=%s", (run_id,)).fetchone()[0] is False
    assert pg.execute("select count(*) from settlements where id=%s and is_demo", (sid,)).fetchone()[0] == 1
    assert pg.execute("select count(*) from tax_invoices where id=%s", (invoice_id,)).fetchone()[0] == 1
    assert pg.execute("""select count(*) from meal_transactions t
      join settlement_demo_transactions d on d.transaction_id=t.id where d.run_id=%s and t.is_demo""",
      (run_id,)).fetchone()[0] == demo_count
    assert pg.execute("select count(*) from normal_settlements where id=%s", (sid,)).fetchone()[0] == 0


def test_archived_demo_does_not_reserve_normal_settlement_period(pg):
    company, merchant, actor, _, employees, ym = demo_actual_parties(pg, "normal-after-archive")
    seeded = pg.execute("select settlement_demo_seed(%s,%s,%s,%s)", (actor, merchant, company, ym)).fetchone()[0]
    demo = pg.execute("select settlement_demo_create(%s,%s)", (actor, merchant)).fetchone()[0]
    pg.execute("select settlement_demo_confirm(%s,%s)", (actor, merchant))
    pg.execute("select settlement_demo_reset(%s,%s,%s)", (actor, merchant, "archive-for-normal"))
    pg.execute("""insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,
      settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
      values(%s,%s,%s,-1100,'spend','ledger','taxable',1000,100,1100,
      (%s::date+interval '12 hours') at time zone 'Asia/Seoul')""",
      (employees[0], company, merchant, seeded["period_from"]))

    normal = pg.execute("select create_merchant_settlement(%s,%s,%s,%s)",
      (merchant, company, seeded["period_from"], seeded["period_to"])).fetchone()[0]

    assert normal["id"] != demo["settlement_id"]
    assert normal["is_demo"] is False
    assert normal["tx_count"] == seeded["transaction_count"] + 1
    assert normal["total_amount"] == seeded["aggregate"]["total_amount"] + 1100
    assert pg.execute("select count(*) from settlements where merchant_id=%s and company_id=%s and period_ym=%s",
      (merchant, company, ym)).fetchone()[0] == 2


def test_link_trigger_marks_transaction_and_normal_reviews_exclude_demo(pg):
    company, merchant, actor, admin, employees, ym = demo_actual_parties(pg, "link-marker")
    period_from = date.fromisoformat(ym + "-01")
    period_to = (period_from.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    tx = pg.execute("""insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,pay_type,
      settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,created_at)
      values(%s,%s,%s,-1100,'spend','ledger','taxable',1000,100,1100,now()) returning id""",
      (employees[0], company, merchant)).fetchone()[0]
    review = pg.execute("""insert into reviews(merchant_id,account_id,transaction_id,rating,status)
      values(%s,%s,%s,5,'visible') returning id""", (merchant, employees[0], tx)).fetchone()[0]
    assert pg.execute("select count(*) from normal_reviews where id=%s", (review,)).fetchone()[0] == 1

    with pytest.raises(RuntimeError, match="rollback marker fixture"):
        with pg.transaction():
            run = pg.execute("""insert into settlement_demo_runs(merchant_id,company_id,company_actor_id,
              period_from,period_to,period_ym,created_by) values(%s,%s,%s,%s,%s,%s,%s) returning id""",
              (merchant, company, admin, period_from, period_to, ym, actor)).fetchone()[0]
            pg.execute("insert into settlement_demo_transactions(run_id,transaction_id) values(%s,%s)", (run, tx))
            assert pg.execute("select is_demo from meal_transactions where id=%s", (tx,)).fetchone()[0] is True
            assert pg.execute("select count(*) from normal_reviews where id=%s", (review,)).fetchone()[0] == 0
            raise RuntimeError("rollback marker fixture")


def test_authenticated_rls_shows_demo_to_tenant_admins_but_not_customer(pg):
    company, merchant, actor, company_actor, _, ym = demo_actual_parties(pg, "rls")
    seeded = pg.execute("select settlement_demo_seed(%s,%s,%s,%s)", (actor, merchant, company, ym)).fetchone()[0]
    demo_user = pg.execute("""select t.user_id from settlement_demo_transactions d
      join meal_transactions t on t.id=d.transaction_id where d.run_id=%s limit 1""",
      (seeded["run_id"],)).fetchone()[0]
    pg.execute("grant usage on schema public,auth to authenticated")
    pg.execute("grant select on meal_transactions,app_users,merchant_admins to authenticated")
    pg.execute("""create or replace function auth.uid() returns uuid language sql stable as $$
      select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$""")

    with pg.transaction():
        pg.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(demo_user),))
        pg.execute("set local role authenticated")
        assert pg.execute("select count(*) from meal_transactions where user_id=%s", (demo_user,)).fetchone()[0] == 0
    for admin_id in (actor, company_actor):
        with pg.transaction():
            pg.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(admin_id),))
            pg.execute("set local role authenticated")
            assert pg.execute("select count(*) from meal_transactions where is_demo").fetchone()[0] == seeded["transaction_count"]
