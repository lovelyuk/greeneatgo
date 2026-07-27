import os
import base64
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
    assert pg.execute("select payment_status from settlements where id=%s", (sid,)).fetchone()[0] == "paid"
    assert pg.execute("select count(*) from settlement_payments where settlement_id=%s", (sid,)).fetchone()[0] == 2


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


def test_compact_key_write_date_and_frozen_direct_snapshot(pg):
    company, _, merchant, _, _, _, actor, _ = parties(pg)
    sid = settlement(pg, company, merchant)
    period_to = pg.execute("select period_to from settlements where id=%s", (sid,)).fetchone()[0]
    claim = pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, sid)).fetchone()[0]
    invoice = claim["tax_invoice"]
    assert claim["action"] == "issue"
    assert invoice["invoicer_mgt_key"] == "GE" + base64.urlsafe_b64encode(sid.bytes).decode().rstrip("=")
    assert len(invoice["invoicer_mgt_key"]) == 24
    assert invoice["write_date"] == period_to.isoformat()
    assert invoice["requested_at"] is None and invoice["issue_requested_by"] is None
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
    company, _, merchant, _, _, _, actor, _ = parties(pg)
    sid = settlement(pg, company, merchant)
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
    assert pg.execute("select popbill_status,nts_status from tax_invoices where settlement_id=%s", (sid,)).fetchone() == ("issued",None)
    pg.execute("select merchant_apply_tax_invoice_status(%s,%s,%s,303,null,null,'2026-07-27T01:00:00Z','2026-07-27T01:01:00Z',null)", (actor,merchant,sid))
    assert pg.execute("select tax_invoice_status,nts_status from settlements join tax_invoices on tax_invoices.settlement_id=settlements.id where settlements.id=%s", (sid,)).fetchone() == ("nts_sending","sending")
    pg.execute("select merchant_apply_tax_invoice_status(%s,%s,%s,304,'SUC001','CONFIRM-1',null,null,'2026-07-27T01:02:00Z')", (actor,merchant,sid))
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
    claim = pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, direct)).fetchone()[0]
    pg.execute("select merchant_finalize_tax_invoice_issue(%s,%s,%s,%s,'rejected',null,null)",
               (actor, merchant, direct, claim["attempt_token"]))
    assert pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, direct)).fetchone()[0]["action"] == "issue"

    requested = settlement(pg, company, merchant)
    pg.execute("select company_confirm_and_request_tax_invoice(%s,%s,%s)", (company_actor, company, requested))
    claim = pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, requested)).fetchone()[0]
    pg.execute("select merchant_finalize_tax_invoice_issue(%s,%s,%s,%s,'rejected',null,null)",
               (actor, merchant, requested, claim["attempt_token"]))
    assert pg.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor, merchant, requested)).fetchone()[0]["action"] == "issue"


def test_claim_fails_closed_on_legal_mismatch_and_rpc_scrubs_raw_provider_fields(pg):
    import psycopg
    company, _, merchant, _, _, _, actor, _ = parties(pg)
    sid = settlement(pg, company, merchant)
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
    company, _, merchant, _, _, _, actor, _ = parties(pg)
    sid = settlement(pg, company, merchant)
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
        company, _, merchant, _, _, _, actor, _ = parties(setup)
        sid = settlement(setup, company, merchant)
        setup.commit()

    def claim():
        with psycopg.connect(settlement_db) as conn:
            value = conn.execute("select merchant_claim_tax_invoice_issue(%s,%s,%s)", (actor,merchant,sid)).fetchone()[0]
            conn.commit()
            return value["action"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        actions = sorted(f.result(timeout=10) for f in (pool.submit(claim),pool.submit(claim)))
    assert actions == ["issue","reconcile"]
