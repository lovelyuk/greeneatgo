"""DB-only operator adjudication. Synthetic data, isolated PostgreSQL only."""
import hashlib
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Barrier
import pytest
import psycopg
from psycopg.types.json import Jsonb
from test_kiwoom_notification_postgres import notification_db as notification_schema, complete
from test_failed_order_postgres import setup, coupon_order, pending_subsidy, MIGRATION

MANUAL = MIGRATION.with_name('0065_manual_database_order_closure.sql')

@pytest.fixture(scope='module')
def notification_db():
    import os
    from urllib.parse import urlsplit
    url=os.getenv('TEST_DATABASE_URL')
    if not url: pytest.skip('dedicated local PostgreSQL required')
    u=urlsplit(url)
    assert (u.hostname,u.port,u.path)==('127.0.0.1',55496,'/manual_close_test'), 'NEVER run schema harness outside dedicated disposable loopback DB'
    return notification_schema.__wrapped__()

@pytest.fixture
def db(notification_db):
    with psycopg.connect(notification_db) as c:
        c.execute(MIGRATION.read_text())
        if MANUAL.exists() and not c.execute("select to_regprocedure('manual_close_failed_payment_order(uuid,jsonb,text,text,boolean)')").fetchone()[0]:
            c.execute(MANUAL.read_text())
        yield c
        c.rollback()

def evidence(db, order):
    row = db.execute("select to_jsonb(o)-'checkout_token' from payment_orders o where id=%s", (order[0],)).fetchone()[0]
    return dict(authority='manual_database_operator', outcome='failed', order_id=str(order[0]),
        user_id=row['user_id'], amount=row['amount'], source_sha256='b'*64,
        observed_discrepancies=db.execute("select coalesce(jsonb_agg(jsonb_build_object('id',d.id,'kind',d.kind,'cpid',d.cpid,'transaction_id',d.transaction_id,'amount',d.amount,'payment_method',d.payment_method,'received_at',d.received_at,'fingerprint',d.fingerprint,'code',d.payload->>'RESULTCODE') order by d.id),'[]'::jsonb) from payment_callback_discrepancies d where order_id=%s",(order[0],)).fetchone()[0],
        source_reference='synthetic secured failed attempt document',
        user_authorization_reference='synthetic explicit one-order authorization',
        complete_attempt_coverage=False, irreversible_no_future_approval=False,
        residual_late_approval_possible=True,
        attempt=dict(transaction_id='synthetic-failed-trx',outcome='failed',code='1001',cpid='CPID',payment_method='CARD',
            occurred_at='2026-10-14T00:00:00Z',reference='synthetic source row 1'),
        observed=row)

def close(db, order, e, dry=True, digest=None):
    canonical=json.dumps(e,sort_keys=True,separators=(',',':'))
    return db.execute('select manual_close_failed_payment_order(%s,%s,%s,%s,%s)',
        (order[0],Jsonb(e),digest or hashlib.sha256(canonical.encode()).hexdigest(),canonical,dry)).fetchone()[0]

def legacy(db):
    _,order,user=setup(db)
    db.execute('update payment_orders set checkout_guard_epoch=null where id=%s',(order[0],))
    return order,user

def test_manual_truthful_actor_dryrun_apply_replay_and_immutable(db):
    order,user=legacy(db); e=evidence(db,order)
    assert close(db,order,e)['eligible'] is True
    assert db.execute('select count(*) from payment_order_reviews').fetchone()[0]==0
    result=close(db,order,e,False)
    assert result['closed'] is True
    assert close(db,order,e,False)['closure_id']==result['closure_id']
    assert db.execute('select actor_id,actor_kind,actor_session_user,actor_current_user from payment_order_reviews where id=%s',(result['review_id'],)).fetchone()==(None,'manual_database_operator','postgres','postgres')
    assert db.execute('select status,checkout_guard_epoch,checkout_revoked_at is not null from payment_orders where id=%s',(order[0],)).fetchone()==('failed',None,True)
    for table in ['payment_order_reviews','payment_order_closures']:
        with pytest.raises(psycopg.errors.RaiseException,match='IMMUTABLE'):
            with db.transaction(): db.execute(f'delete from {table}')
    with pytest.raises(psycopg.errors.RaiseException,match='CONFLICT'):
        with db.transaction(): close(db,order,{**e,'source_reference':'different synthetic document'},False)
    late=complete(db,order,'synthetic-late')
    assert late['fulfilled'] is False and late['reconciliation_required'] is True
    assert close(db,order,e,False)['closed'] is False
    assert db.execute('select count(*) from payment_notification_inbox where order_id=%s',(order[0],)).fetchone()[0]==0
    assert db.execute('select count(*) from vouchers where order_id=%s',(order[0],)).fetchone()[0]==0

@pytest.mark.parametrize('change',[{'complete_attempt_coverage':True},{'irreversible_no_future_approval':True},{'residual_late_approval_possible':False},{'authority':'trusted_provider_irreversible_closure'},{'actor_id':'00000000-0000-4000-8000-000000000001'},{'user_authorization_reference':''},{'attempt':{}},{'amount':True}])
def test_invalid_evidence_rejects(db,change):
    order,_=legacy(db);e=evidence(db,order)
    with pytest.raises((psycopg.errors.RaiseException,psycopg.errors.InvalidTextRepresentation)):
        with db.transaction(): close(db,order,{**e,**change},False)
    assert db.execute('select count(*) from payment_order_closures').fetchone()[0]==0

def test_stale_and_forged_evidence_reject(db):
    order,_=legacy(db);e=evidence(db,order)
    with pytest.raises(psycopg.errors.RaiseException):
        with db.transaction(): close(db,order,e,False,digest='a'*64)
    db.execute("update payment_orders set checkout_started_at=now() where id=%s",(order[0],))
    with pytest.raises(psycopg.errors.RaiseException,match='STALE'):
        with db.transaction(): close(db,order,e,False)

@pytest.mark.parametrize('role',['anon','authenticated','service_role'])
def test_api_roles_denied_and_set_role_session_bypass_denied(db,role):
    order,_=legacy(db);e=evidence(db,order)
    sig='manual_close_failed_payment_order(uuid,jsonb,text,text,boolean)'
    assert not db.execute('select has_function_privilege(%s,%s,\'EXECUTE\')',(role,sig)).fetchone()[0]
    # Superuser grants simulate a future mistaken grant; body must still fail.
    with pytest.raises(psycopg.errors.RaiseException,match='FORBIDDEN'):
        with db.transaction():
            db.execute(f'grant execute on function {sig} to {role}')
            db.execute(f'grant usage on schema public to {role}')
            if role=='service_role': db.execute('grant postgres to service_role')
            db.execute(f'set local session authorization {role}')
            db.execute('set local role postgres') if role=='service_role' else None
            close(db,order,e,False)

@pytest.mark.parametrize('state',['used','another_order'])
def test_coupon_conflict(db,state):
    _,order,_,coupon,other=coupon_order(db)
    if state=='used':
        db.execute("update user_coupons set status='used',reserved_order_id=null,reserved_at=null,used_order_id=%s,used_at=now() where id=%s",(other[0],coupon))
    else: db.execute('update user_coupons set reserved_order_id=%s where id=%s',(other[0],coupon))
    e=evidence(db,order)
    with pytest.raises(psycopg.errors.RaiseException,match='COUPON'):
        with db.transaction(): close(db,order,e,False)

@pytest.mark.parametrize('winner',['close','approval'])
def test_real_concurrent_close_approval_both_lock_orders(db,notification_db,winner):
    order,_=legacy(db);e=evidence(db,order);db.commit()
    started=Event()
    def contender():
        with psycopg.connect(notification_db) as c:
            c.execute("set lock_timeout='10s'")
            started.set()
            try: return complete(c,order,'synthetic-race') if winner=='close' else close(c,order,e,False)
            except psycopg.errors.RaiseException as exc: return str(exc)
    with ThreadPoolExecutor(max_workers=1) as pool:
        db.execute('select id from payment_orders where id=%s for update',(order[0],))
        result=close(db,order,e,False) if winner=='close' else complete(db,order,'synthetic-race')
        future=pool.submit(contender);assert started.wait(5)
        # Confirm second transaction really blocked on this first transaction.
        for _ in range(10000):
            if db.execute("select exists(select 1 from pg_stat_activity where wait_event_type='Lock' and pid<>pg_backend_pid() and datname=current_database())").fetchone()[0]: break
        else: pytest.fail('contender did not wait on real row lock')
        db.commit();other=future.result(timeout=15)
    state=db.execute('select status from payment_orders where id=%s',(order[0],)).fetchone()[0]
    assert state==('failed' if winner=='close' else 'done')
    assert db.execute('select count(*) from payment_order_closures where order_id=%s',(order[0],)).fetchone()[0]==(1 if winner=='close' else 0)
    assert (other.get('fulfilled') is False) if winner=='close' else isinstance(other,str)


def test_point_and_coupon_exact_once_concurrent_replay(db,notification_db):
    order,user=pending_subsidy(db);e=evidence(db,order);db.commit()
    barrier=Barrier(2)
    def run():
        with psycopg.connect(notification_db) as c:
            barrier.wait(timeout=5)
            return close(c,order,e,False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a,b=pool.submit(run),pool.submit(run);results=[a.result(),b.result()]
    assert len({r['closure_id'] for r in results})==1
    assert db.execute('select point_balance,point_reserved from app_users where id=%s',(user,)).fetchone()==(1000,0)
    _,order,_,coupon,_=coupon_order(db);e=evidence(db,order);db.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        a,b=pool.submit(run),pool.submit(run);results=[a.result(),b.result()]
    assert len({r['closure_id'] for r in results})==1
    assert db.execute('select status,reserved_order_id from user_coupons where id=%s',(coupon,)).fetchone()==('available',None)

def test_manual_db_producer_then_real_owned_http_recovery(db):
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
            pytest.fail('owner recovery must not call any closure/checkout/provider RPC')
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
    assert close(db,order,evidence(db,order),False)['closed'] is True
    with patch.object(platform,'JoinRepository',return_value=repo),patch.object(platform,'_platform_admin',return_value=SimpleNamespace(id=actor)),patch.object(payments,'JoinRepository',return_value=repo),patch.object(payments,'get_settings',return_value=SimpleNamespace()):
        recovered=client.get('/payments/recovery',params=dict(order_id=order[1],amount=1100),headers={'Authorization':'Bearer fixture'})
        assert recovered.status_code==200
        data=recovered.json()['data']
        assert data['recovery_action']=='closed' and data['status']=='failed'
        assert data['closure']['finality']=='verified' and data['closure']['scope']=='order'
        assert data['user_id']==str(user) and data['completion'] is None and data['checkout_url'] is None
        refused=client.post(f'/admin/platform/payment-orders/{order[0]}/review',json=evidence(db,order),headers={'Authorization':'Bearer fixture'})
        assert refused.status_code==422
        assert complete(db,order,'synthetic-http-late')['fulfilled'] is False
        reconciled=client.get('/payments/recovery',params=dict(order_id=order[1],amount=1100),headers={'Authorization':'Bearer fixture'}).json()['data']
        assert reconciled['recovery_action']=='reconcile' and 'closure' not in reconciled

@pytest.mark.parametrize('kind',['nonapproval','unmatched_nonapproval','late_approval','second_approval'])
def test_only_source_matched_nonapproval_permitted(db,kind):
    order,_=legacy(db)
    db.execute("insert into payment_callback_discrepancies(order_id,cpid,transaction_id,amount,payment_method,kind,payload,source_ip,fingerprint) values(%s,'CPID','synthetic-failed-trx',1100,'CARD',%s,%s,'127.0.0.1',%s)",
        (order[0],kind,Jsonb(dict(RESULTCODE='1001')),'synthetic-'+kind))
    e=evidence(db,order)
    if kind=='nonapproval':
        assert close(db,order,e,False)['closed'] is True
    else:
        with pytest.raises(psycopg.errors.RaiseException,match='DISCREPANCY'):
            with db.transaction(): close(db,order,e,False)

@pytest.mark.parametrize('field',['cpid','payment_method','code','transaction_id'])
def test_nonapproval_must_match_each_source_identity_field(db,field):
    order,_=legacy(db)
    db.execute("select record_kiwoom_nonapproval_notification('CPID',%s,'synthetic-failed-trx',1100,'CARD',%s,'127.0.0.1')",(order[1],Jsonb(dict(RESULTCODE='1001'))))
    e=evidence(db,order);e['attempt'][field]='synthetic-mismatch'
    with pytest.raises(psycopg.errors.RaiseException,match='DISCREPANCY'):
        with db.transaction(): close(db,order,e,False)

def test_uncovered_or_mismatched_nonapproval_rejects(db):
    order,_=legacy(db);e=evidence(db,order)
    db.execute("select record_kiwoom_nonapproval_notification('CPID',%s,'other-attempt',1100,'CARD',%s,'127.0.0.1')",(order[1],Jsonb(dict(RESULTCODE='1001'))))
    for ev in [e,evidence(db,order)]:
        with pytest.raises(psycopg.errors.RaiseException,match='DISCREPANCY'):
            with db.transaction(): close(db,order,ev,False)

def test_point_resource_history_and_underreserved_wallet_reject(db):
    order,user=pending_subsidy(db)
    db.execute('update app_users set point_reserved=0 where id=%s',(user,))
    e=evidence(db,order)
    with pytest.raises(psycopg.errors.RaiseException,match='RESERVATION'):
        with db.transaction(): close(db,order,e,False)
    company=db.execute('select company_id from app_users where id=%s',(user,)).fetchone()[0]
    db.execute("insert into point_transactions(user_id,company_id,type,amount,balance_after,reason,related_order_id) values(%s,%s,'adjust',1,1000,'synthetic',%s)",(user,company,order[0]))
    with pytest.raises(psycopg.errors.RaiseException,match='HISTORY'):
        with db.transaction(): close(db,order,e,False)

def test_original_app_producer_keeps_real_actor_requirement_after_addition(db):
    from test_failed_order_postgres import review
    actor,order,user=setup(db)
    with pytest.raises(psycopg.errors.RaiseException,match='FORBIDDEN'):
        with db.transaction(): review(db,None,order,user)
    result=review(db,actor,order,user)
    assert result['closed'] is True
    assert db.execute('select actor_id,actor_kind,actor_session_user,actor_current_user from payment_order_reviews where id=%s',(result['review_id'],)).fetchone()==(actor,'application_platform_admin',None,None)
    # Null actor never becomes valid merely because the column is nullable.
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            ev=evidence(db,order);canonical=json.dumps(ev,sort_keys=True)
            db.execute('insert into payment_order_reviews(order_id,user_id,amount,actor_id,evidence_sha256,evidence,canonical_evidence) values(%s,%s,1100,null,%s,%s,%s)',(order[0],user,hashlib.sha256(canonical.encode()).hexdigest(),Jsonb(ev),canonical))

@pytest.mark.parametrize('field',['order_id','user_id','amount','status','merchant_id','checkout_guard_epoch','checkout_started_at','checkout_revoked_at'])
def test_forged_observed_identity_and_guards_reject(db,field):
    order,_=legacy(db);e=evidence(db,order)
    e['observed'][field]='forged'
    with pytest.raises(psycopg.errors.RaiseException,match='STALE'):
        with db.transaction(): close(db,order,e,False)

def test_real_service_login_cannot_set_role_to_bypass(db,notification_db):
    from urllib.parse import urlsplit,urlunsplit
    order,_=legacy(db);e=evidence(db,order);db.commit()
    db.execute('alter role service_role login')
    db.commit()
    u=urlsplit(notification_db);url=urlunsplit((u.scheme,'service_role@'+u.netloc.split('@')[1],u.path,u.query,u.fragment))
    try:
        with psycopg.connect(url) as c:
            assert c.execute('select session_user,current_user').fetchone()==('service_role','service_role')
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with c.transaction(): close(c,order,e,False)
            db.execute('grant postgres to service_role');db.commit()
            c.execute('set role postgres')
            assert c.execute('select session_user,current_user').fetchone()==('service_role','postgres')
            with pytest.raises(psycopg.errors.RaiseException,match='FORBIDDEN'):
                with c.transaction(): close(c,order,e,False)
    finally:
        db.execute('revoke postgres from service_role');db.execute('alter role service_role nologin');db.commit()

def test_closure_cannot_link_another_order_review(db):
    from test_failed_order_postgres import review
    actor,order,user=setup(db)
    r=review(db,actor,order,user,authority='attempt_only')
    _,other,other_user=setup(db)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with db.transaction():
            db.execute("insert into payment_order_closures(order_id,user_id,amount,review_id,evidence_sha256,outcome) select %s,%s,amount,id,evidence_sha256,'failed' from payment_order_reviews where id=%s",(other[0],other_user,r['review_id']))

@pytest.mark.parametrize('history',['voucher','refund','coupon_redemption','notification_inbox','approved_marker','fulfilled_marker'])
def test_resource_and_approval_history_never_closes(db,history):
    actor,order,user,coupon,_=coupon_order(db)
    merchant,product,catalog=db.execute('select merchant_id,voucher_product_id,coupon_id from payment_orders where id=%s',(order[0],)).fetchone()
    if history=='voucher':
        db.execute("insert into vouchers(user_id,merchant_id,product_id,order_id,issue_index,purchase_price) values(%s,%s,%s,%s,1,1100)",(user,merchant,product,order[0]))
    elif history=='refund':
        db.execute('insert into refund_requests(order_id,merchant_id,user_id,requested_by,refund_amount) values(%s,%s,%s,%s,0)',(order[0],merchant,user,actor))
    elif history=='coupon_redemption':
        db.execute("insert into coupon_redemptions(order_id,coupon_id,user_id,merchant_id,discount_amount,coupon_snapshot) values(%s,%s,%s,%s,100,'{}')",(order[0],catalog,user,merchant))
    elif history=='notification_inbox':
        db.execute("insert into payment_notification_inbox(order_id,merchant_id,provider_transaction_id,provider_order_id,cpid,amount,payment_method,normalized_payload,source_ip) values(%s,%s,%s,%s,'CPID',1100,'CARD','{}','127.0.0.1')",(order[0],merchant,'synthetic-'+str(order[0]),order[1]))
    elif history=='approved_marker': db.execute('update payment_orders set approved_at=now() where id=%s',(order[0],))
    else: db.execute('update payment_orders set fulfilled_at=now() where id=%s',(order[0],))
    e=evidence(db,order)
    before_coupon=db.execute('select status,reserved_order_id,used_order_id from user_coupons where id=%s',(coupon,)).fetchone()
    with pytest.raises(psycopg.errors.RaiseException,match='HISTORY'):
        with db.transaction(): close(db,order,e,False)
    assert db.execute('select status from payment_orders where id=%s',(order[0],)).fetchone()[0]=='ready'
    assert db.execute('select status,reserved_order_id,used_order_id from user_coupons where id=%s',(coupon,)).fetchone()==before_coupon

def test_service_pause_is_nondestructive_and_keeps_late_approval_quarantine(db):
    # Only migration 0065 is integrated; exercise a synthetic service-ACL pause,
    # not the separate database-operator operational pause script.
    order,_=legacy(db);e=evidence(db,order);result=close(db,order,e,False)
    db.execute('revoke all on function public.manual_close_failed_payment_order(uuid,jsonb,text,text,boolean) from service_role')
    assert not db.execute("select has_function_privilege('service_role','manual_close_failed_payment_order(uuid,jsonb,text,text,boolean)','EXECUTE')").fetchone()[0]
    assert db.execute('select id from payment_order_closures where id=%s',(result['closure_id'],)).fetchone()
    assert complete(db,order,'synthetic-after-pause')['fulfilled'] is False
