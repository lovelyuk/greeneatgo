"""Truthful DB-operator local adjudication; disposable loopback PostgreSQL only."""
import hashlib
import json
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
import psycopg
from psycopg.types.json import Jsonb
from test_local_abandonment_postgres import db as owner_db, notification_db
from test_failed_order_postgres import setup, coupon_order, pending_subsidy, complete

MIGRATIONS = Path(__file__).resolve().parents[3] / 'supabase/migrations'
SIGNATURE = 'operator_stop_payment_order(uuid,jsonb,text,text,boolean)'

@pytest.fixture
def db(owner_db):
    if not owner_db.execute("select to_regprocedure('abandon_owned_payment_order_intent(text,uuid,integer,boolean,boolean,text)')").fetchone()[0]:
        owner_db.execute((MIGRATIONS/'0067_explicit_checkout_cancel_intent.sql').read_text())
    migration = MIGRATIONS/'0068_operator_local_stop.sql'
    if migration.exists() and not owner_db.execute("select to_regprocedure('operator_stop_payment_order(uuid,jsonb,text,text,boolean)')").fetchone()[0]:
        owner_db.execute(migration.read_text())
    yield owner_db

def evidence(db, order):
    row = db.execute("select to_jsonb(o)-array['checkout_token','provider_response']::text[] from payment_orders o where id=%s", (order[0],)).fetchone()[0]
    return dict(authority='local_stop_adjudication', reason='manual_local_stop_unknown_provider',
        order_id=str(order[0]), merchant_order_id=order[1], user_id=row['user_id'], amount=row['amount'],
        source_sha256='b'*64, authorization_reference='synthetic explicit exact-order request',
        provider_finality='unknown', residual_late_approval_possible=True,
        observed=row,
        observed_discrepancies=db.execute("select coalesce(jsonb_agg(to_jsonb(d)-'payload' order by id),'[]'::jsonb) from payment_callback_discrepancies d where order_id=%s", (order[0],)).fetchone()[0])

def stop(db, order, e, dry=False, digest=None):
    canonical=json.dumps(e,sort_keys=True,separators=(',',':'))
    return db.execute('select operator_stop_payment_order(%s,%s,%s,%s,%s)',
        (order[0],Jsonb(e),digest or hashlib.sha256(canonical.encode()).hexdigest(),canonical,dry)).fetchone()[0]

def test_truthful_dryrun_commit_replay_immutable(db):
    _,order,user=setup(db);db.execute('select admit_payment_checkout(%s)',(order[0],));e=evidence(db,order)
    assert stop(db,order,e,True)['eligible'] is True
    assert db.execute('select count(*) from payment_order_operator_local_stops').fetchone()[0]==0
    assert db.execute('select status from payment_orders where id=%s',(order[0],)).fetchone()[0]=='ready'
    r=stop(db,order,e);db.commit()
    assert r['stopped'] is True and stop(db,order,e)['receipt_id']==r['receipt_id']
    assert db.execute('select actor_kind,actor_session_user,actor_current_user,user_id,evidence_sha256 from payment_order_operator_local_stops where order_id=%s',(order[0],)).fetchone()==('database_operator','postgres','postgres',user,hashlib.sha256(json.dumps(e,sort_keys=True,separators=(',',':')).encode()).hexdigest())
    assert db.execute('select status,checkout_started_at is not null,checkout_revoked_at is not null,point_reserved from payment_orders where id=%s',(order[0],)).fetchone()==('canceled',True,True,False)
    assert db.execute('select count(*) from payment_order_local_abandonments where order_id=%s',(order[0],)).fetchone()[0]==0
    assert db.execute('select count(*) from payment_order_closures where order_id=%s',(order[0],)).fetchone()[0]==0
    for statement in ['delete from payment_order_operator_local_stops','update payment_order_operator_local_stops set amount=amount']:
        with pytest.raises(psycopg.errors.RaiseException,match='IMMUTABLE'):
            with db.transaction(): db.execute(statement)
    with pytest.raises(psycopg.errors.RaiseException,match='CONFLICT'):
        with db.transaction(): stop(db,order,{**e,'authorization_reference':'different synthetic request'})
    for name in ['admit_payment_checkout','assert_payment_checkout_active']:
        with pytest.raises(psycopg.errors.RaiseException,match='CHECKOUT_NOT_ADMISSIBLE'):
            with db.transaction(): db.execute(f'select {name}(%s)',(order[0],))

@pytest.mark.parametrize('change',[{'amount':1},{'amount':True},{'order_id':str(uuid.UUID(int=1))},{'merchant_order_id':'wrong-order'}, {'user_id':str(uuid.UUID(int=2))},{'authority':'owner_request'}, {'provider_finality':'verified'},{'residual_late_approval_possible':False},{'source_sha256':'bad'},{'authorization_reference':''},{'actor_id':'fake'},{'complete_attempt_coverage':True},{'attempt':{'code':'invented'}}])
def test_invalid_evidence(db,change):
    _,order,_=setup(db);e=evidence(db,order)
    with pytest.raises(psycopg.errors.RaiseException,match='EVIDENCE_INVALID'):
        with db.transaction(): stop(db,order,{**e,**change})

def test_hash_and_stale_and_wrong_order(db):
    _,order,_=setup(db);e=evidence(db,order)
    with pytest.raises(psycopg.errors.RaiseException,match='EVIDENCE_INVALID'):
        with db.transaction(): stop(db,order,e,digest='a'*64)
    db.execute('update payment_orders set checkout_started_at=now() where id=%s',(order[0],))
    with pytest.raises(psycopg.errors.RaiseException,match='STALE'):
        with db.transaction(): stop(db,order,e)
    with pytest.raises(psycopg.errors.RaiseException,match='ORDER_NOT_FOUND'):
        with db.transaction(): stop(db,(uuid.uuid4(),'GE-synthetic'),e)

@pytest.mark.parametrize('role',['anon','authenticated','service_role'])
def test_roles_denied_even_if_accidentally_granted(db,role):
    _,order,_=setup(db);e=evidence(db,order)
    assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')",(role,SIGNATURE)).fetchone()[0]
    assert not db.execute("select has_table_privilege(%s,'payment_order_operator_local_stops','INSERT,UPDATE,DELETE')",(role,)).fetchone()[0]
    with pytest.raises(psycopg.errors.RaiseException,match='FORBIDDEN'):
        with db.transaction():
            db.execute(f'grant execute on function {SIGNATURE} to {role}')
            db.execute(f'grant usage on schema public to {role}')
            if role=='service_role': db.execute('grant postgres to service_role')
            db.execute(f'set local session authorization {role}')
            if role=='service_role': db.execute('set local role postgres')
            stop(db,order,e)

@pytest.mark.parametrize('kind',['zero','approved','fulfilled','voucher','refund','points','redemption','inbox','spent','coupon_foreign','wallet_conflict','owner_stop','closure','review','provider_response'])
def test_financial_guards(db,kind):
    actor,order,user,coupon,other=coupon_order(db)
    merchant,product,catalog=db.execute('select merchant_id,voucher_product_id,coupon_id from payment_orders where id=%s',(order[0],)).fetchone()
    if kind=='zero':
        _,order,user=setup(db)
        db.execute('update payment_orders set amount=0 where id=%s',(order[0],))
    if kind=='provider_response': db.execute("update payment_orders set provider_response='{}' where id=%s",(order[0],))
    if kind=='review':
        from test_failed_order_postgres import review
        db.execute('select admit_payment_checkout(%s)',(order[0],))
        review(db,actor,order,user,authority='attempt_only',attempts=[])
    if kind=='approved': db.execute('update payment_orders set approved_at=now() where id=%s',(order[0],))
    if kind=='fulfilled': db.execute('update payment_orders set fulfilled_at=now() where id=%s',(order[0],))
    if kind=='voucher': db.execute('insert into vouchers(user_id,merchant_id,product_id,order_id,issue_index,purchase_price) values(%s,%s,%s,%s,1,1100)',(user,merchant,product,order[0]))
    if kind=='refund': db.execute('insert into refund_requests(order_id,merchant_id,user_id,requested_by,refund_amount) values(%s,%s,%s,%s,0)',(order[0],merchant,user,actor))
    if kind=='points':
        company=db.execute("insert into companies(name) values('synthetic') returning id").fetchone()[0]
        db.execute("insert into point_transactions(user_id,company_id,amount,balance_after,type,reason,related_order_id) values(%s,%s,1,1,'charge','synthetic',%s)",(user,company,order[0]))
    if kind=='redemption': db.execute("insert into coupon_redemptions(order_id,coupon_id,user_id,merchant_id,discount_amount,coupon_snapshot) values(%s,%s,%s,%s,100,'{}')",(order[0],catalog,user,merchant))
    if kind=='inbox': db.execute("insert into payment_notification_inbox(order_id,merchant_id,provider_transaction_id,provider_order_id,cpid,amount,payment_method,normalized_payload,source_ip) values(%s,%s,%s,%s,'CPID',1100,'CARD','{}','127.0.0.1')",(order[0],merchant,'synthetic-'+str(order[0]),order[1]))
    if kind=='spent': db.execute("update user_coupons set status='used',reserved_order_id=null,reserved_at=null,used_order_id=%s,used_at=now() where id=%s",(other[0],coupon))
    if kind=='coupon_foreign': db.execute('update user_coupons set reserved_order_id=%s where id=%s',(other[0],coupon))
    if kind=='wallet_conflict':
        order,user=pending_subsidy(db);db.execute('update app_users set point_reserved=0 where id=%s',(user,))
    if kind=='owner_stop': db.execute('select abandon_owned_payment_order(%s,%s,1100,true)',(order[1],user))
    if kind=='closure':
        from test_failed_order_postgres import review
        review(db,actor,order,user)
    e=evidence(db,order)
    before=db.execute('select status,reserved_order_id,used_order_id from user_coupons where id=%s',(coupon,)).fetchone()
    with pytest.raises(psycopg.errors.RaiseException):
        with db.transaction(): stop(db,order,e)
    assert db.execute('select status,reserved_order_id,used_order_id from user_coupons where id=%s',(coupon,)).fetchone()==before
    assert db.execute('select count(*) from payment_order_operator_local_stops where order_id=%s',(order[0],)).fetchone()[0]==0

@pytest.mark.parametrize('kind',['coupon','points'])
def test_release_once_and_late_second_approval(db,kind):
    if kind=='coupon': _,order,user,coupon,_=coupon_order(db)
    else: order,user=pending_subsidy(db)
    e=evidence(db,order);r=stop(db,order,e);assert stop(db,order,e)['receipt_id']==r['receipt_id']
    if kind=='coupon': assert db.execute('select status,reserved_order_id from user_coupons where id=%s',(coupon,)).fetchone()==('available',None)
    else: assert db.execute('select point_balance,point_reserved from app_users where id=%s',(user,)).fetchone()==(1000,0)
    for trx in ['late-synthetic','second-synthetic']:
        assert complete(db,order,trx)['reconciliation_required'] is True
    assert stop(db,order,e)['stopped'] is False
    assert db.execute('select count(*) from payment_callback_discrepancies where order_id=%s',(order[0],)).fetchone()[0]==2
    for table in ['vouchers','refund_requests','payment_notification_inbox']:
        assert db.execute(f'select count(*) from {table} where order_id=%s',(order[0],)).fetchone()[0]==0

@pytest.mark.parametrize('winner',['approve','stop'])
def test_both_serialized_race_winners(db,notification_db,winner):
    order,user=pending_subsidy(db)
    db.execute('select admit_payment_checkout(%s)',(order[0],))
    e=evidence(db,order);db.commit();attempted=Event()
    with psycopg.connect(notification_db) as first:
        first.execute('select id from payment_orders where id=%s for update',(order[0],))
        def rival():
            with psycopg.connect(notification_db) as c:
                attempted.set()
                try: return stop(c,order,e) if winner=='approve' else complete(c,order,'late-race')
                except psycopg.errors.RaiseException as exc: return str(exc)
        with ThreadPoolExecutor(max_workers=1) as pool:
            f=pool.submit(rival);assert attempted.wait(5)
            complete(first,order,'first-race') if winner=='approve' else stop(first,order,e)
            first.commit();result=f.result(timeout=10)
    if winner=='approve': assert isinstance(result,str) and 'STALE' in result
    else: assert result['reconciliation_required'] is True
    assert db.execute('select point_balance,point_reserved from app_users where id=%s',(user,)).fetchone()==(900 if winner=='approve' else 1000,0)


def test_other_order_points_untouched_and_same_order_concurrent_replay(db,notification_db):
    first,user=pending_subsidy(db);second,_=pending_subsidy(db)
    company=db.execute('select company_id from app_users where id=%s',(user,)).fetchone()[0]
    db.execute('update payment_orders set user_id=%s,company_id=%s where id=%s',(user,company,second[0]))
    db.execute('update app_users set point_reserved=200 where id=%s',(user,))
    e=evidence(db,first);db.commit()
    def run():
        with psycopg.connect(notification_db) as c: return stop(c,first,e)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(run);b=pool.submit(run)
        assert a.result()['receipt_id']==b.result()['receipt_id']
    assert db.execute('select point_balance,point_reserved from app_users where id=%s',(user,)).fetchone()==(1000,100)
    assert db.execute('select status,point_reserved from payment_orders where id=%s',(second[0],)).fetchone()==('ready',True)
    assert db.execute('select count(*) from payment_order_operator_local_stops where order_id=%s',(first[0],)).fetchone()[0]==1


def test_operator_receipt_never_promotes_to_provider_closure(db):
    from test_failed_order_postgres import review
    actor,order,user=setup(db);stop(db,order,evidence(db,order))
    with pytest.raises(psycopg.errors.RaiseException,match='LOCAL_ABANDONMENT_NOT_VERIFIED_CLOSURE'):
        with db.transaction(): review(db,actor,order,user)
