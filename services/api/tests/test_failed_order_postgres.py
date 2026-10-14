"""Real local PostgreSQL, synthetic records only; never point at production."""
import hashlib
import json
import uuid
from pathlib import Path

import pytest
from test_kiwoom_notification_postgres import notification_db, parties, direct_order, complete

MIGRATION = Path(__file__).resolve().parents[3] / 'supabase/migrations/0064_failed_order_finalization.sql'


@pytest.fixture
def db(notification_db):
    import psycopg
    with psycopg.connect(notification_db) as conn:
        if MIGRATION.exists():
            conn.execute(MIGRATION.read_text())
        yield conn
        conn.rollback()


def review(db, actor, order, user, authority='no_issued_form', dry=False, **extra):
    from psycopg.types.json import Jsonb
    evidence = dict(order_id=str(order[0]), actor_id=str(actor), user_id=str(user), amount=1100,
        outcome='canceled', source_sha256='b'*64, source_reference='synthetic document reference',
        attempts=[], authority=authority, complete_attempt_coverage=False,
        irreversible_no_future_approval=False, provider_closure_reference=None)
    evidence.update(extra)
    canonical = json.dumps(evidence, sort_keys=True, separators=(',',':'),ensure_ascii=True)
    return db.execute('select review_failed_payment_order(%s,%s,%s,%s,%s,%s)',
        (actor,order[0],Jsonb(evidence),hashlib.sha256(canonical.encode()).hexdigest(),canonical,dry)).fetchone()[0]


def setup(db):
    user, merchant, _ = parties(db)
    actor = db.execute("insert into app_users(id,display_name,role,status) values(gen_random_uuid(),'operator','platform_admin','active') returning id").fetchone()[0]
    order, _ = direct_order(db,user,merchant,str(uuid.uuid4()))
    return actor, order, user


def test_no_issued_finalization_atomic_immutable_and_idempotent(db):
    actor, order, user = setup(db)
    dry = review(db,actor,order,user,dry=True)
    assert dry['eligible'] is True and dry['closed'] is False
    assert db.execute('select status from payment_orders where id=%s',(order[0],)).fetchone()[0]=='ready'
    result = review(db,actor,order,user)
    assert result['closed'] is True
    assert review(db,actor,order,user)['closure_id']==result['closure_id']
    assert db.execute('select status,checkout_revoked_at is not null from payment_orders where id=%s',(order[0],)).fetchone()==('canceled',True)
    assert db.execute('select count(*) from payment_order_closures where order_id=%s',(order[0],)).fetchone()[0]==1
    import psycopg
    with pytest.raises(psycopg.errors.RaiseException,match='IMMUTABLE'):
        with db.transaction():
            db.execute('delete from payment_order_reviews where order_id=%s',(order[0],))

def test_guard_is_one_shot_and_review_revokes_unresolved_issued_form(db):
    import psycopg
    actor, order, user = setup(db)
    db.execute('select admit_payment_checkout(%s)',(order[0],))
    with pytest.raises(psycopg.errors.RaiseException,match='CHECKOUT_NOT_ADMISSIBLE'):
        with db.transaction():
            db.execute('select admit_payment_checkout(%s)',(order[0],))
    result = review(db,actor,order,user,authority='attempt_only',attempts=[dict(transaction_id='fixture-failure',outcome='failed')])
    assert result['closed'] is False
    assert db.execute('select status,checkout_revoked_at is not null from payment_orders where id=%s',(order[0],)).fetchone()==('ready',True)
    assert review(db,actor,order,user)['closed'] is False
    trusted = review(db,actor,order,user,authority='trusted_provider_irreversible_closure',
        complete_attempt_coverage=True,irreversible_no_future_approval=True,
        provider_closure_reference='synthetic provider irreversible closure',attempts=[dict(transaction_id='fixture-failure',outcome='failed')])
    assert trusted['closed'] is True


def test_late_and_second_approvals_are_durable_without_duplicate_fulfillment(db):
    actor, order, user = setup(db)
    review(db,actor,order,user)
    result = complete(db,order,'late-fixture-trx')
    assert result['reconciliation_required'] is True
    assert review(db,actor,order,user)['closed'] is False
    assert db.execute('select status from payment_orders where id=%s',(order[0],)).fetchone()[0]=='canceled'
    assert db.execute('select count(*) from payment_callback_discrepancies where order_id=%s',(order[0],)).fetchone()[0]==1
    complete(db,order,'late-fixture-trx')
    assert db.execute('select count(*) from payment_callback_discrepancies where order_id=%s',(order[0],)).fetchone()[0]==1
    _, second, _ = setup(db)
    complete(db,second,'first-fixture-trx')
    result = complete(db,second,'second-fixture-trx')
    assert result['reconciliation_required'] is True
    assert db.execute('select provider_payment_key from payment_orders where id=%s',(second[0],)).fetchone()[0]=='first-fixture-trx'

def test_nonapproval_is_durable_and_does_not_finalize(db):
    from psycopg.types.json import Jsonb
    actor, order, user = setup(db)
    payload=dict(CPID='CPID',ORDERNO=order[1],DAOUTRX='fixture-failure',AMOUNT='1100',PAYMETHOD='CARD',RESULTCODE='1001')
    result=db.execute("select record_kiwoom_nonapproval_notification('CPID',%s,'fixture-failure',1100,'CARD',%s,'127.0.0.1')",(order[1],Jsonb(payload))).fetchone()[0]
    assert result['durable'] is True
    assert db.execute('select status from payment_orders where id=%s',(order[0],)).fetchone()[0]=='ready'
    assert db.execute('select count(*) from payment_callback_discrepancies where order_id=%s',(order[0],)).fetchone()[0]==1
    result=db.execute("select record_kiwoom_nonapproval_notification('CPID',null,'unknown-fixture',1100,'BANK_CANCEL',%s,'127.0.0.1')",(Jsonb(dict(PAYMETHOD='BANK_CANCEL',CANCELDATE='20261014090000')),)).fetchone()[0]
    assert result['durable'] is True and result['matched'] is False


def test_legacy_missing_marker_cannot_close_without_provider_attestation(db):
    actor, order, user=setup(db)
    db.execute('update payment_orders set checkout_guard_epoch=null where id=%s',(order[0],))
    assert review(db,actor,order,user)['closed'] is False


def test_concurrent_review_and_approval_never_double_process(db,notification_db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import psycopg
    actor, order, user=setup(db)
    db.commit()
    barrier=Barrier(2)
    def close():
        with psycopg.connect(notification_db) as c:
            barrier.wait()
            try:
                return review(c,actor,order,user)
            except psycopg.errors.RaiseException as exc:
                return str(exc)
    def approve():
        with psycopg.connect(notification_db) as c:
            barrier.wait()
            return complete(c,order,'race-'+str(uuid.uuid4()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(close); b=pool.submit(approve)
        outcomes=[a.result(),b.result()]
    status=db.execute('select status from payment_orders where id=%s',(order[0],)).fetchone()[0]
    closures=db.execute('select count(*) from payment_order_closures where order_id=%s',(order[0],)).fetchone()[0]
    inbox=db.execute('select count(*) from payment_notification_inbox where order_id=%s',(order[0],)).fetchone()[0]
    assert (status,closures,inbox) in [('canceled',1,0),('done',0,1)], outcomes

def test_reservation_release_is_exact_once_and_does_not_take_another_order(db):
    import psycopg
    user,merchant,company=parties(db)
    db.execute("update app_users set role='employee', company_id=%s,point_balance=1000,point_reserved=300 where id=%s",(company,user))
    actor=db.execute("insert into app_users(id,display_name,role,status) values(gen_random_uuid(),'operator','platform_admin','active') returning id").fetchone()[0]
    vp=db.execute("insert into voucher_products(merchant_id,name,voucher_count,unit_price,tax_type) values(%s,'fixture',1,1500,'taxable') returning id",(merchant,)).fetchone()[0]
    def reserved(suffix,points):
        return db.execute("""insert into payment_orders(order_id,checkout_token,user_id,merchant_id,merchant_name,product_name,
          amount,status,pay_type,voucher_count,paid_voucher_count,bonus_voucher_count,voucher_purchase_price,
          company_id,company_subsidy_amount,restaurant_subsidy_amount,total_employee_burden,point_amount,point_reserved,tax_type,
          gross_amount,requested_point_amount,voucher_product_id)
          values(%s,%s,%s,%s,'fixture','fixture',1100,'ready','subsidized',1,1,0,%s,%s,200,100,%s,%s,true,'taxable',%s,%s,%s)
          returning id,order_id""",('GE-'+suffix,'token-'+suffix,user,merchant,1100+points,company,1100+points,points,1100+points,points,vp)).fetchone()
    first=reserved(str(uuid.uuid4()),100)
    second=reserved(str(uuid.uuid4()),200)
    result=review(db,actor,first,user)
    assert result['closed'] is True
    assert review(db,actor,first,user)['closed'] is True
    assert db.execute('select point_balance,point_reserved from app_users where id=%s',(user,)).fetchone()==(1000,200)
    assert db.execute('select point_reserved from payment_orders where id=%s',(second[0],)).fetchone()[0] is True
    db.execute('update app_users set point_reserved=100 where id=%s',(user,))
    with pytest.raises(psycopg.errors.RaiseException,match='RESERVATION_OWNERSHIP_CONFLICT'):
        with db.transaction():
            review(db,actor,second,user)
    assert db.execute('select status from payment_orders where id=%s',(second[0],)).fetchone()[0]=='ready'


def test_database_enforces_actor_owner_hash_and_resource_history(db):
    import psycopg
    actor,order,user=setup(db)
    for kwargs,who,owner in [({},user,user),({},actor,actor)]:
        with pytest.raises(psycopg.errors.RaiseException):
            with db.transaction():
                review(db,who,order,owner,**kwargs)
    complete(db,order,'approved-fixture-'+str(uuid.uuid4()))
    with pytest.raises(psycopg.errors.RaiseException,match='ORDER_HAS_PAYMENT_OR_RESOURCE_HISTORY'):
        with db.transaction():
            review(db,actor,order,user)


def test_concurrent_finalization_and_entry_have_only_one_winner(db,notification_db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import psycopg
    actor,order,user=setup(db)
    db.commit()
    barrier=Barrier(2)
    def run(kind):
        with psycopg.connect(notification_db) as c:
            barrier.wait()
            try:
                return review(c,actor,order,user) if kind=='close' else c.execute('select admit_payment_checkout(%s)',(order[0],)).fetchone()[0]
            except psycopg.errors.RaiseException as exc:
                return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(run,'close');b=pool.submit(run,'entry'); a.result();b.result()
    state=db.execute('select status,checkout_started_at is not null from payment_orders where id=%s',(order[0],)).fetchone()
    assert state in [('canceled',False),('ready',True)]

def test_legacy_unknown_issuance_must_not_issue_another_hash(db):
    import psycopg
    actor,order,user=setup(db)
    db.execute('update payment_orders set checkout_guard_epoch=null where id=%s',(order[0],))
    with pytest.raises(psycopg.errors.RaiseException,match='CHECKOUT_NOT_ADMISSIBLE'):
        with db.transaction():
            db.execute('select admit_payment_checkout(%s)',(order[0],))

def test_known_attempt_prevents_no_issued_claim_and_requires_coverage(db):
    from psycopg.types.json import Jsonb
    actor,order,user=setup(db)
    payload=dict(RESULTCODE='1001',PAYMETHOD='CARD',DAOUTRX='observed-attempt')
    db.execute("select record_kiwoom_nonapproval_notification('CPID',%s,'observed-attempt',1100,'CARD',%s,'127.0.0.1')",(order[1],Jsonb(payload)))
    assert review(db,actor,order,user)['closed'] is False
    trusted=dict(complete_attempt_coverage=True,irreversible_no_future_approval=True,provider_closure_reference='synthetic irreversible provider closure')
    assert review(db,actor,order,user,authority='trusted_provider_irreversible_closure',**trusted)['closed'] is False
    assert review(db,actor,order,user,authority='trusted_provider_irreversible_closure',attempts=[dict(transaction_id='observed-attempt',outcome='failed')],**trusted)['closed'] is True


def test_no_client_rpc_or_mutation_grants(db):
    for table in ['payment_order_reviews','payment_order_closures','payment_callback_discrepancies']:
        for role in ['anon','authenticated']:
            assert not db.execute("select has_table_privilege(%s,%s,'SELECT')",(role,table)).fetchone()[0]
        assert not db.execute("select has_table_privilege('service_role',%s,'INSERT,UPDATE,DELETE')",(table,)).fetchone()[0]
    assert not db.execute("select has_function_privilege('authenticated','review_failed_payment_order(uuid,uuid,jsonb,text,text,boolean)','EXECUTE')").fetchone()[0]
    assert not db.execute("select has_function_privilege('service_role','complete_kiwoom_payment_notification_original(uuid,text,text,int,text,text,jsonb,inet)','EXECUTE')").fetchone()[0]

def test_posthash_barrier_checks_revocation_under_order_lock(db):
    import psycopg
    actor,order,user=setup(db)
    db.execute('select admit_payment_checkout(%s)',(order[0],))
    assert db.execute('select assert_payment_checkout_active(%s)',(order[0],)).fetchone()[0]['active'] is True
    review(db,actor,order,user,authority='attempt_only')
    with pytest.raises(psycopg.errors.RaiseException,match='CHECKOUT_NOT_ADMISSIBLE'):
        with db.transaction():
            db.execute('select assert_payment_checkout_active(%s)',(order[0],))

def test_existing_voucher_subsidized_approval_and_point_spend_preserved(db):
    from test_kiwoom_notification_postgres import test_voucher_and_subsidized_fulfillment_and_transaction_rollback as existing_approval_scenario
    existing_approval_scenario(db)


def test_review_rollback_disables_producer_without_destroying_history(db):
    actor,order,user=setup(db)
    closure=review(db,actor,order,user)
    rollback=MIGRATION.parents[1]/'operations/pause_failed_order_review.sql'
    db.execute(rollback.read_text())
    assert db.execute('select id from payment_order_closures where id=%s',(closure['closure_id'],)).fetchone() is not None
    assert not db.execute("select has_function_privilege('service_role','review_failed_payment_order(uuid,uuid,jsonb,text,text,boolean)','EXECUTE')").fetchone()[0]
    assert db.execute("select has_function_privilege('service_role','admit_payment_checkout(uuid)','EXECUTE')").fetchone()[0]
    assert db.execute("select has_function_privilege('service_role','complete_kiwoom_payment_notification(uuid,text,text,int,text,text,jsonb,inet)','EXECUTE')").fetchone()[0]


def test_http_producer_to_real_database_then_owned_recovery(db):
    from types import SimpleNamespace
    from unittest.mock import patch
    from psycopg import sql
    from psycopg.types.json import Jsonb
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import platform,payments
    actor,order,user=setup(db)
    class LocalClient:
        def rpc(self,name,args):
            assert name=='review_failed_payment_order'
            return db.execute('select review_failed_payment_order(%s,%s,%s,%s,%s,%s)',
                (args['p_actor_id'],args['p_order_id'],Jsonb(args['p_evidence']),args['p_evidence_sha256'],args['p_canonical_evidence'],args['p_dry_run'])).fetchone()[0]
        def rest_get(self,table,filters):
            assert table in ['payment_orders','payment_order_closures','payment_callback_discrepancies']
            columns=filters['select'].split(',')
            where=[]; values=[]
            for key,value in filters.items():
                if key in ['select','limit']: continue
                assert value.startswith('eq.')
                where.append(sql.SQL('{}=%s').format(sql.Identifier(key)))
                values.append(value[3:])
            result=db.execute(sql.SQL('select {} from {} where {} limit 1').format(
                sql.SQL(',').join(map(sql.Identifier,columns)),sql.Identifier(table),sql.SQL(' and ').join(where)),values)
            return [json.loads(json.dumps(dict(zip(columns,row)),default=lambda value:value.isoformat() if hasattr(value,'isoformat') else str(value))) for row in result.fetchall()]
    repo=SimpleNamespace(client=LocalClient(),auth_user_from_token=lambda token:SimpleNamespace(id=user,email=None),get_profile=lambda *a,**kw:SimpleNamespace(id=user,role='customer',status='active'))
    app=FastAPI();app.include_router(platform.router);app.include_router(payments.router)
    client=TestClient(app)
    payload=dict(user_id=str(user),amount=1100,outcome='failed',source_sha256='c'*64,source_reference='synthetic secured case',attempts=[],authority='no_issued_form',dry_run=False)
    with patch.object(platform,'JoinRepository',return_value=repo),patch.object(platform,'_platform_admin',return_value=SimpleNamespace(id=actor)),patch.object(payments,'JoinRepository',return_value=repo),patch.object(payments,'get_settings',return_value=SimpleNamespace()):
        applied=client.post(f'/admin/platform/payment-orders/{order[0]}/review',json=payload,headers={'Authorization':'Bearer fixture'})
        assert applied.status_code==200 and applied.json()['data']['closed'] is True
        recovered=client.get('/payments/recovery',params=dict(order_id=order[1],amount=1100),headers={'Authorization':'Bearer fixture'})
        assert recovered.status_code==200
        data=recovered.json()['data']
        assert data['recovery_action']=='closed' and data['status']=='failed'
        assert data['closure']['finality']=='verified' and data['closure']['scope']=='order'
        assert data['user_id']==str(user) and data['completion'] is None and data['checkout_url'] is None

def test_mismatched_attempt_on_known_order_cannot_be_hidden_by_no_issued_claim(db):
    from psycopg.types.json import Jsonb
    actor,order,user=setup(db)
    payload=dict(RESULTCODE='1001',PAYMETHOD='CARD',ORDERNO=order[1])
    db.execute("select record_kiwoom_nonapproval_notification('CPID',%s,'mismatch-fixture',100,'CARD',%s,'127.0.0.1')",(order[1],Jsonb(payload)))
    assert review(db,actor,order,user)['closed'] is False

def coupon_order(db):
    from psycopg.types.json import Jsonb
    actor,other,user=setup(db)
    merchant=db.execute('select merchant_id from payment_orders where id=%s',(other[0],)).fetchone()[0]
    catalog=db.execute("insert into merchant_coupons(merchant_id,name,discount_type,discount_value,is_active,created_by) values(%s,'fixture','fixed',100,true,%s) returning id",(merchant,actor)).fetchone()[0]
    snapshot=dict(id=str(catalog),merchant_id=str(merchant))
    coupon=db.execute('insert into user_coupons(user_id,merchant_id,coupon_id,coupon_snapshot) values(%s,%s,%s,%s) returning id',(user,merchant,catalog,Jsonb(snapshot))).fetchone()[0]
    vp=db.execute("insert into voucher_products(merchant_id,name,voucher_count,unit_price,tax_type) values(%s,'fixture',1,1200,'taxable') returning id",(merchant,)).fetchone()[0]
    tag=str(uuid.uuid4())
    order=db.execute("""insert into payment_orders(order_id,checkout_token,user_id,merchant_id,merchant_name,product_name,
        amount,status,pay_type,voucher_product_id,voucher_count,paid_voucher_count,bonus_voucher_count,voucher_purchase_price,
        gross_amount,requested_point_amount,coupon_id,coupon_discount_amount,coupon_snapshot,user_coupon_id)
        values(%s,%s,%s,%s,'fixture','fixture',1100,'ready','voucher',%s,1,1,0,1100,1200,0,%s,100,%s,%s)
        returning id,order_id""",('GE-'+tag,'token-'+tag,user,merchant,vp,catalog,Jsonb(snapshot),coupon)).fetchone()
    db.execute('select reserve_user_coupon(%s,%s,%s,%s)',(order[0],coupon,user,merchant))
    return actor,order,user,coupon,other


def test_coupon_reservation_is_released_exactly_once_including_legacy_terminal_state(db):
    actor,order,user,coupon,other=coupon_order(db)
    # Simulate historical cancellation whose reservation remained stranded.
    db.execute("update payment_orders set status='canceled' where id=%s",(order[0],))
    db.execute("update user_coupons set status='reserved',reserved_order_id=%s,reserved_at=now() where id=%s",(order[0],coupon))
    assert review(db,actor,order,user)['closed'] is True
    assert review(db,actor,order,user)['closed'] is True
    assert db.execute('select status,reserved_order_id,used_order_id from user_coupons where id=%s',(coupon,)).fetchone()==('available',None,None)


@pytest.mark.parametrize('state',['used','another_order'])
def test_coupon_spent_or_reserved_for_another_order_blocks_closure_without_mutation(db,state):
    import psycopg
    actor,order,user,coupon,other=coupon_order(db)
    if state=='used':
        db.execute("update user_coupons set status='used',reserved_order_id=null,reserved_at=null,used_order_id=%s,used_at=now() where id=%s",(other[0],coupon))
    else:
        db.execute('update user_coupons set reserved_order_id=%s where id=%s',(other[0],coupon))
    with pytest.raises(psycopg.errors.RaiseException,match='COUPON_RESERVATION_CONFLICT'):
        with db.transaction():
            review(db,actor,order,user)
    assert db.execute('select status from payment_orders where id=%s',(order[0],)).fetchone()[0]=='ready'

def pending_subsidy(db):
    user,merchant,company=parties(db)
    db.execute("update app_users set role='employee',company_id=%s,point_balance=1000,point_reserved=100 where id=%s",(company,user))
    vp=db.execute("insert into voucher_products(merchant_id,name,voucher_count,unit_price,tax_type) values(%s,'fixture',1,1200,'taxable') returning id",(merchant,)).fetchone()[0]
    tag=str(uuid.uuid4())
    order=db.execute("""insert into payment_orders(order_id,checkout_token,user_id,merchant_id,merchant_name,product_name,
        amount,status,pay_type,voucher_product_id,voucher_count,paid_voucher_count,bonus_voucher_count,voucher_purchase_price,
        company_id,company_subsidy_amount,restaurant_subsidy_amount,total_employee_burden,point_amount,point_reserved,gross_amount,created_at)
        values(%s,%s,%s,%s,'fixture','fixture',1100,'ready','subsidized',%s,1,1,0,1200,%s,0,0,1200,100,true,1200,now()-interval '1 hour')
        returning id,order_id""",('GE-'+tag,'token-'+tag,user,merchant,vp,company)).fetchone()
    return order,user


@pytest.mark.parametrize('reason',['legacy','revoked'])
def test_legacy_or_revoked_unknown_orders_cannot_expire_or_client_release(db,reason):
    import psycopg
    order,user=pending_subsidy(db)
    if reason=='legacy':
        db.execute('update payment_orders set checkout_guard_epoch=null where id=%s',(order[0],))
    else:
        db.execute('update payment_orders set checkout_revoked_at=now() where id=%s',(order[0],))
    result=db.execute('select expire_stale_subsidized_orders(%s)',(user,)).fetchone()[0]
    assert result['expired_count']==0
    with pytest.raises(psycopg.errors.RaiseException,match='CHECKOUT_RECONCILIATION_REQUIRED'):
        with db.transaction():
            db.execute('select release_subsidized_order_points(%s,%s)',(order[0],user))
    assert db.execute('select status,point_reserved from payment_orders where id=%s',(order[0],)).fetchone()==('ready',True)
    assert db.execute('select point_reserved from app_users where id=%s',(user,)).fetchone()[0]==100


def test_known_never_issued_subsidized_expiry_preserves_native_behavior(db):
    order,user=pending_subsidy(db)
    result=db.execute('select expire_stale_subsidized_orders(%s)',(user,)).fetchone()[0]
    assert result['expired_count']==1 and result['released_point_amount']==100
    assert db.execute('select status,point_reserved from payment_orders where id=%s',(order[0],)).fetchone()==('canceled',False)
