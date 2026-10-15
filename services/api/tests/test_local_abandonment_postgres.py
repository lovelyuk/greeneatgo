"""Synthetic customer local abandonment; dedicated disposable PostgreSQL only."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
import psycopg
from psycopg import sql
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_manual_order_close_postgres import notification_db
from test_failed_order_postgres import setup, coupon_order, pending_subsidy, MIGRATION, complete

MANUAL=MIGRATION.with_name('0065_manual_database_order_closure.sql')
LOCAL=MIGRATION.with_name('0066_owner_local_abandonment.sql')

@pytest.fixture
def db(notification_db):
    with psycopg.connect(notification_db) as c:
        c.execute(MIGRATION.read_text())
        if not c.execute("select to_regprocedure('manual_close_failed_payment_order(uuid,jsonb,text,text,boolean)')").fetchone()[0]:
            c.execute(MANUAL.read_text())
        if LOCAL.exists() and not c.execute("select to_regprocedure('abandon_owned_payment_order(text,uuid,integer,boolean)')").fetchone()[0]:
            c.execute(LOCAL.read_text())
        yield c
        c.rollback()

def abandon(db,order,user,amount=1100,consent=True):
    return db.execute('select abandon_owned_payment_order(%s,%s,%s,%s)',(order[1],user,amount,consent)).fetchone()[0]

def test_owner_local_abandonment_producer_exists_is_immutable_replay_and_uncertain(db):
    _,order,user=setup(db)
    db.execute('select admit_payment_checkout(%s)',(order[0],))
    epoch=db.execute('select checkout_guard_epoch from payment_orders where id=%s',(order[0],)).fetchone()[0]
    result=abandon(db,order,user)
    assert result['recovery_action']=='locally_abandoned'
    assert result['local_abandonment']['requested_by']==str(user)
    assert result['local_abandonment']['provider_finality']=='unknown'
    assert result['local_abandonment']['residual_late_approval_possible'] is True
    assert abandon(db,order,user)==result
    assert db.execute('select status,checkout_guard_epoch,checkout_revoked_at is not null from payment_orders where id=%s',(order[0],)).fetchone()==('canceled',epoch,True)
    assert db.execute('select count(*) from payment_order_closures where order_id=%s',(order[0],)).fetchone()[0]==0
    for operation in ['delete from','update']:
        with pytest.raises(psycopg.errors.RaiseException,match='IMMUTABLE'):
            with db.transaction():
                db.execute(operation+' payment_order_local_abandonments'+(' set amount=amount' if operation=='update' else '')+' where order_id=%s',(order[0],))
    for function in ['admit_payment_checkout','assert_payment_checkout_active']:
        with pytest.raises(psycopg.errors.RaiseException,match='CHECKOUT_NOT_ADMISSIBLE'):
            with db.transaction(): db.execute(f'select {function}(%s)',(order[0],))

@pytest.mark.parametrize('change',['owner','amount','consent','null_consent','zero','failed','legacy'])
def test_owner_amount_consent_positive_ready_and_legacy_epoch(db,change):
    actor,order,user=setup(db)
    if change=='failed': db.execute("update payment_orders set status='failed' where id=%s",(order[0],))
    if change=='zero': db.execute('update payment_orders set amount=0 where id=%s',(order[0],))
    if change=='legacy':
        db.execute('update payment_orders set checkout_guard_epoch=null where id=%s',(order[0],))
        assert abandon(db,order,user)['recovery_action']=='locally_abandoned'
        assert db.execute('select checkout_guard_epoch from payment_orders where id=%s',(order[0],)).fetchone()[0] is None
        return
    with pytest.raises(psycopg.errors.RaiseException):
        with db.transaction(): abandon(db,order,actor if change=='owner' else user,amount=100 if change=='amount' else 1100,consent=None if change=='null_consent' else change!='consent')
    assert db.execute('select count(*) from payment_order_local_abandonments where order_id=%s',(order[0],)).fetchone()[0]==0

@pytest.mark.parametrize('kind',['approved','fulfilled','points','late_charge','inbox','closure'])
def test_financial_history_blocks_local_abandonment(db,kind):
    actor,order,user=setup(db)
    if kind=='approved': db.execute('update payment_orders set approved_at=now() where id=%s',(order[0],))
    if kind=='fulfilled':
        order,user=pending_subsidy(db)
        db.execute('update payment_orders set fulfilled_at=now() where id=%s',(order[0],))
    if kind in ['late_charge','inbox']:
        complete(db,order,'history-'+kind)
        if kind=='late_charge': complete(db,order,'second-history')
    if kind=='closure':
        from test_failed_order_postgres import review
        review(db,actor,order,user)
    if kind=='points':
        company=db.execute("insert into companies(name) values('synthetic') returning id").fetchone()[0]
        db.execute("insert into point_transactions(user_id,company_id,amount,balance_after,type,reason,related_order_id) values(%s,%s,1,1,'charge','synthetic',%s)",(user,company,order[0]))
    with pytest.raises(psycopg.errors.RaiseException):
        with db.transaction(): abandon(db,order,user)

@pytest.mark.parametrize('resource',['points','coupon','coupon_conflict','wallet_conflict'])
def test_releases_only_own_resources_once(db,resource):
    if resource.startswith('coupon'):
        _,order,user,coupon,other=coupon_order(db)
        if resource=='coupon_conflict':
            db.execute('update user_coupons set reserved_order_id=%s where id=%s',(other[0],coupon))
            with pytest.raises(psycopg.errors.RaiseException,match='COUPON_RESERVATION_CONFLICT'):
                with db.transaction(): abandon(db,order,user)
            return
        abandon(db,order,user); abandon(db,order,user)
        assert db.execute('select status,reserved_order_id,used_order_id from user_coupons where id=%s',(coupon,)).fetchone()==('available',None,None)
    else:
        order,user=pending_subsidy(db)
        if resource=='wallet_conflict':
            db.execute('update app_users set point_reserved=0 where id=%s',(user,))
            with pytest.raises(psycopg.errors.RaiseException,match='RESERVATION_OWNERSHIP_CONFLICT'):
                with db.transaction(): abandon(db,order,user)
            return
        abandon(db,order,user); abandon(db,order,user)
        assert db.execute('select point_balance,point_reserved from app_users where id=%s',(user,)).fetchone()==(1000,0)
        assert db.execute('select point_reserved from payment_orders where id=%s',(order[0],)).fetchone()[0] is False
    result=complete(db,order,'late-resource-charge')
    assert result['reconciliation_required'] is True
    assert abandon(db,order,user)['recovery_action']=='reconcile'
    assert db.execute('select count(*) from vouchers where order_id=%s',(order[0],)).fetchone()[0]==0
    assert db.execute('select count(*) from refund_requests where order_id=%s',(order[0],)).fetchone()[0]==0

@pytest.mark.parametrize('rival',['approve','abandon'])
def test_concurrent_approval_or_replay_serializes_without_double_resources(db,notification_db,rival):
    order,user=pending_subsidy(db)
    db.execute('select admit_payment_checkout(%s)',(order[0],))
    db.commit()
    barrier=Barrier(2)
    def run(which):
        with psycopg.connect(notification_db) as c:
            barrier.wait()
            try: return complete(c,order,'race-approval') if which=='approve' else abandon(c,order,user)
            except psycopg.errors.RaiseException as exc: return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(run,'abandon');b=pool.submit(run,rival); outcomes=[a.result(),b.result()]
    state=db.execute('select status,point_reserved from payment_orders where id=%s',(order[0],)).fetchone()
    receipts=db.execute('select count(*) from payment_order_local_abandonments where order_id=%s',(order[0],)).fetchone()[0]
    assert (state,receipts) in [(('canceled',False),1),(('done',False),0)],outcomes
    balance,reserved=db.execute('select point_balance,point_reserved from app_users where id=%s',(user,)).fetchone()
    assert reserved==0 and balance==(1000 if state[0]=='canceled' else 900)
    assert db.execute('select count(*) from refund_requests where order_id=%s',(order[0],)).fetchone()[0]==0

def test_service_only_and_existing_manual_privileges_preserved(db):
    sig='abandon_owned_payment_order(text,uuid,integer,boolean)'
    for role in ['anon','authenticated']:
        assert not db.execute('select has_function_privilege(%s,%s,\'EXECUTE\')',(role,sig)).fetchone()[0]
        assert not db.execute("select has_table_privilege(%s,'payment_order_local_abandonments','SELECT')",(role,)).fetchone()[0]
    assert db.execute("select has_function_privilege('service_role',%s,'EXECUTE')",(sig,)).fetchone()[0]
    assert not db.execute("select has_table_privilege('service_role','payment_order_local_abandonments','INSERT,UPDATE,DELETE')").fetchone()[0]
    assert not db.execute("select has_function_privilege('service_role','manual_close_failed_payment_order(uuid,jsonb,text,text,boolean)','EXECUTE')").fetchone()[0]

class LocalClient:
    def __init__(self,db): self.db=db
    def rpc(self,name,args):
        assert name=='abandon_owned_payment_order'
        return self.db.execute('select abandon_owned_payment_order(%s,%s,%s,%s)',(args['p_order_id'],args['p_user_id'],args['p_amount'],args['p_acknowledge_provider_uncertainty'])).fetchone()[0]
    def rest_get(self,table,filters):
        assert table in ['payment_orders','payment_order_closures','payment_callback_discrepancies','payment_order_local_abandonments']
        columns=filters['select'].split(',');where=[];values=[]
        for key,value in filters.items():
            if key in ['select','limit','order']: continue
            assert value.startswith(('eq.','neq.'))
            operator=sql.SQL('<>') if value.startswith('neq.') else sql.SQL('=')
            where.append(sql.SQL('{}{}%s').format(sql.Identifier(key),operator));values.append(value.split('.',1)[1])
        result=self.db.execute(sql.SQL('select {} from {} where {} limit {}').format(sql.SQL(',').join(map(sql.Identifier,columns)),sql.Identifier(table),sql.SQL(' and ').join(where),sql.Literal(int(filters.get('limit',1)))),values)
        return [json.loads(json.dumps(dict(zip(columns,row)),default=lambda v:v.isoformat() if hasattr(v,'isoformat') else str(v))) for row in result.fetchall()]

def test_http_owner_token_producer_recovery_history_late_charge(db):
    from app.routers import payments
    _,order,user=setup(db)
    repo=SimpleNamespace(client=LocalClient(db),auth_user_from_token=lambda t:SimpleNamespace(id=user,email=None),get_profile=lambda *a,**kw:SimpleNamespace(id=user,role='customer',status='active'))
    app=FastAPI();app.include_router(payments.router);client=TestClient(app)
    headers={'Authorization':'Bearer synthetic-owner'}
    with patch.object(payments,'JoinRepository',return_value=repo),patch.object(payments,'get_settings',return_value=SimpleNamespace()):
        response=client.post(f'/payments/orders/{order[1]}/abandon',json=dict(amount=1100,acknowledge_provider_uncertainty=True),headers=headers)
        assert response.status_code==200,response.text
        data=response.json()['data'];assert data['recovery_action']=='locally_abandoned'
        recovered=client.get('/payments/recovery',params=dict(order_id=order[1],amount=1100),headers=headers)
        assert recovered.json()['data']==data
        history=client.get('/payments/local-abandonments',headers=headers)
        assert history.status_code==200 and history.json()['data']['orders']==[data]
        complete(db,order,'late-http-charge');complete(db,order,'second-late-http-charge')
        late=client.get('/payments/recovery',params=dict(order_id=order[1],amount=1100),headers=headers).json()['data']
        assert late['recovery_action']=='reconcile' and late['local_abandonment']==data['local_abandonment']
        assert late['completion'] is None and late['checkout_url'] is None and late['resumable'] is False
        assert client.get('/payments/local-abandonments',headers=headers).json()['data']['orders']==[late]
        assert client.post(f'/payments/orders/{order[1]}/abandon',json=dict(amount=1100,acknowledge_provider_uncertainty=True),headers=headers).json()['data']==late


@pytest.mark.parametrize('history',['voucher','refund','coupon_redemption','notification_inbox'])
def test_independent_resource_history_cannot_be_abandoned(db,history):
    actor,order,user,coupon,_=coupon_order(db)
    merchant,product,catalog=db.execute('select merchant_id,voucher_product_id,coupon_id from payment_orders where id=%s',(order[0],)).fetchone()
    if history=='voucher':
        db.execute('insert into vouchers(user_id,merchant_id,product_id,order_id,issue_index,purchase_price) values(%s,%s,%s,%s,1,1100)',(user,merchant,product,order[0]))
    elif history=='refund':
        db.execute('insert into refund_requests(order_id,merchant_id,user_id,requested_by,refund_amount) values(%s,%s,%s,%s,0)',(order[0],merchant,user,actor))
    elif history=='coupon_redemption':
        db.execute("insert into coupon_redemptions(order_id,coupon_id,user_id,merchant_id,discount_amount,coupon_snapshot) values(%s,%s,%s,%s,100,'{}')",(order[0],catalog,user,merchant))
    else:
        db.execute("insert into payment_notification_inbox(order_id,merchant_id,provider_transaction_id,provider_order_id,cpid,amount,payment_method,normalized_payload,source_ip) values(%s,%s,%s,%s,'CPID',1100,'CARD','{}','127.0.0.1')",(order[0],merchant,'synthetic-'+str(order[0]),order[1]))
    before=db.execute('select status,reserved_order_id from user_coupons where id=%s',(coupon,)).fetchone()
    with pytest.raises(psycopg.errors.RaiseException,match='HISTORY'):
        with db.transaction(): abandon(db,order,user)
    assert db.execute('select status,reserved_order_id from user_coupons where id=%s',(coupon,)).fetchone()==before
    assert db.execute('select count(*) from payment_order_local_abandonments where order_id=%s',(order[0],)).fetchone()[0]==0


def test_local_receipt_cannot_be_promoted_to_verified_closure(db):
    from test_failed_order_postgres import review
    actor,order,user=setup(db)
    abandon(db,order,user)
    with pytest.raises(psycopg.errors.RaiseException,match='LOCAL_ABANDONMENT_NOT_VERIFIED_CLOSURE'):
        with db.transaction(): review(db,actor,order,user)
    assert db.execute('select count(*) from payment_order_closures where order_id=%s',(order[0],)).fetchone()[0]==0


@pytest.mark.parametrize('winner',['approve','abandon'])
def test_deterministic_serialized_winner_and_late_charge(db,notification_db,winner):
    from threading import Event
    order,user=pending_subsidy(db)
    db.execute('select admit_payment_checkout(%s)',(order[0],))
    db.commit()
    attempted=Event()
    # Hold the shared order lock until rival has attempted its transaction.
    with psycopg.connect(notification_db) as first:
        first.execute('select id from payment_orders where id=%s for update',(order[0],))
        def rival():
            with psycopg.connect(notification_db) as c:
                attempted.set()
                try: return abandon(c,order,user) if winner=='approve' else complete(c,order,'deterministic-late')
                except psycopg.errors.RaiseException as exc: return str(exc)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(rival);assert attempted.wait(5)
            if winner=='approve': complete(first,order,'deterministic-first')
            else: abandon(first,order,user)
            first.commit();result=future.result(timeout=10)
    if winner=='approve':
        assert isinstance(result,str) and 'HISTORY' in result
        assert db.execute('select status from payment_orders where id=%s',(order[0],)).fetchone()[0]=='done'
    else:
        assert result['reconciliation_required'] is True
        assert db.execute('select count(*) from vouchers where order_id=%s',(order[0],)).fetchone()[0]==0
        assert abandon(db,order,user)['recovery_action']=='reconcile'
    assert db.execute('select point_balance,point_reserved from app_users where id=%s',(user,)).fetchone()==(900 if winner=='approve' else 1000,0)


def test_released_coupon_new_distinct_order_then_old_charge_never_redeems_twice(db):
    import uuid
    _,old,user,coupon,_=coupon_order(db)
    receipt=abandon(db,old,user)
    tag=str(uuid.uuid4())
    fresh=db.execute("""insert into payment_orders(order_id,checkout_token,user_id,merchant_id,merchant_name,product_name,
        amount,status,pay_type,voucher_product_id,voucher_count,paid_voucher_count,bonus_voucher_count,voucher_purchase_price,
        gross_amount,requested_point_amount,coupon_id,coupon_discount_amount,coupon_snapshot,user_coupon_id)
        select %s,%s,user_id,merchant_id,merchant_name,product_name,amount,'ready',pay_type,voucher_product_id,
        voucher_count,paid_voucher_count,bonus_voucher_count,voucher_purchase_price,gross_amount,requested_point_amount,
        coupon_id,coupon_discount_amount,coupon_snapshot,user_coupon_id from payment_orders where id=%s
        returning id,order_id""",('GE-new-'+tag,'token-new-'+tag,old[0])).fetchone()
    merchant=db.execute('select merchant_id from payment_orders where id=%s',(fresh[0],)).fetchone()[0]
    db.execute('select reserve_user_coupon(%s,%s,%s,%s)',(fresh[0],coupon,user,merchant))
    db.execute('select admit_payment_checkout(%s)',(fresh[0],))
    complete(db,fresh,'fresh-'+tag)
    assert fresh[0]!=old[0] and fresh[1]!=old[1]
    late=complete(db,old,'old-late-'+tag)
    assert late['reconciliation_required'] is True
    assert db.execute('select used_order_id from user_coupons where id=%s',(coupon,)).fetchone()[0]==fresh[0]
    assert db.execute('select count(*) from coupon_redemptions where user_id=%s',(user,)).fetchone()[0]==1
    assert db.execute('select count(*) from vouchers where order_id=%s',(old[0],)).fetchone()[0]==0
    assert abandon(db,old,user)['local_abandonment']['id']==receipt['local_abandonment']['id']
    assert db.execute('select count(*) from refund_requests where order_id=%s',(old[0],)).fetchone()[0]==0


def test_used_coupon_for_foreign_order_cannot_complete_ready_order(db):
    _,order,user,coupon,other=coupon_order(db)
    db.execute("update user_coupons set status='used',reserved_order_id=null,reserved_at=null,used_order_id=%s,used_at=now() where id=%s",(other[0],coupon))
    db.execute('select admit_payment_checkout(%s)',(order[0],))
    with pytest.raises(psycopg.errors.RaiseException,match='USER_COUPON_CONSUME_CONFLICT'):
        with db.transaction(): complete(db,order,'foreign-used-coupon-charge')
    assert db.execute('select status from payment_orders where id=%s',(order[0],)).fetchone()[0]=='ready'
    assert db.execute('select used_order_id from user_coupons where id=%s',(coupon,)).fetchone()[0]==other[0]
    assert db.execute('select count(*) from vouchers where order_id=%s',(order[0],)).fetchone()[0]==0


def test_other_order_point_reservation_is_preserved_not_stolen(db):
    first,user=pending_subsidy(db);second,_=pending_subsidy(db)
    company=db.execute('select company_id from app_users where id=%s',(user,)).fetchone()[0]
    db.execute('update payment_orders set user_id=%s,company_id=%s where id=%s',(user,company,second[0]))
    db.execute('update app_users set point_reserved=200 where id=%s',(user,))
    abandon(db,first,user);abandon(db,first,user)
    assert db.execute('select point_reserved from app_users where id=%s',(user,)).fetchone()[0]==100
    assert db.execute('select status,point_reserved from payment_orders where id=%s',(second[0],)).fetchone()==('ready',True)
    db.execute('update app_users set point_reserved=0 where id=%s',(user,))
    with pytest.raises(psycopg.errors.RaiseException,match='RESERVATION_OWNERSHIP_CONFLICT'):
        with db.transaction(): abandon(db,second,user)


def test_concurrent_coupon_abandon_replay_is_one_receipt_one_release(db,notification_db):
    _,order,user,coupon,_=coupon_order(db);db.commit();barrier=Barrier(2)
    def run():
        with psycopg.connect(notification_db) as c:
            barrier.wait()
            return abandon(c,order,user)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(run);b=pool.submit(run);assert a.result()==b.result()
    assert db.execute('select count(*) from payment_order_local_abandonments where order_id=%s',(order[0],)).fetchone()[0]==1
    assert db.execute('select status,reserved_order_id,used_order_id from user_coupons where id=%s',(coupon,)).fetchone()==('available',None,None)
