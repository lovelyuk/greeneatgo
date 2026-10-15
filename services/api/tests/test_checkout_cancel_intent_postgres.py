"""New authorization shares locked 0066 lifecycle, never certifies provider stop."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path
import pytest
import psycopg
from test_local_abandonment_postgres import db, notification_db, abandon
from test_failed_order_postgres import setup, pending_subsidy, coupon_order, complete

MIGRATION=Path(__file__).resolve().parents[3]/'supabase/migrations/0067_explicit_checkout_cancel_intent.sql'

@pytest.fixture
def intent_db(db):
    if not db.execute("select to_regprocedure('abandon_owned_payment_order_intent(text,uuid,integer,boolean,boolean,text)')").fetchone()[0]:
        db.execute(MIGRATION.read_text())
    return db

def cancel(db,order,user,amount=1100,ack=None,intent=True):
    return db.execute('select abandon_owned_payment_order_intent(%s,%s,%s,%s,%s)',
                      (order[1],user,amount,ack,intent)).fetchone()[0]

def test_distinct_truthful_receipt_replay_and_legacy_compatibility(intent_db):
    c=intent_db;_,order,user=setup(c)
    result=cancel(c,order,user)
    assert c.execute('select acknowledge_provider_uncertainty,explicit_checkout_cancel_intent from payment_order_local_abandonments where order_id=%s',(order[0],)).fetchone()==(None,True)
    assert result['recovery_action']=='locally_abandoned'
    assert result['local_abandonment']['provider_finality']=='unknown'
    assert result['local_abandonment']['residual_late_approval_possible'] is True
    assert cancel(c,order,user)==result
    assert abandon(c,order,user)==result
    _,legacy,owner=setup(c)
    assert abandon(c,legacy,owner)['recovery_action']=='locally_abandoned'
    assert c.execute('select acknowledge_provider_uncertainty,explicit_checkout_cancel_intent from payment_order_local_abandonments where order_id=%s',(legacy[0],)).fetchone()==(True,False)
    with pytest.raises(psycopg.errors.RaiseException,match='IMMUTABLE'):
        with c.transaction(): c.execute('update payment_order_local_abandonments set explicit_checkout_cancel_intent=false where order_id=%s',(order[0],))

@pytest.mark.parametrize('ack,intent',[(None,False),(False,False),(None,None),(True,True),(False,True),(True,None)])
def test_producer_requires_exactly_one_authorization(intent_db,ack,intent):
    c=intent_db;_,order,user=setup(c)
    with pytest.raises(psycopg.errors.RaiseException,match='EXPLICIT_LOCAL_AUTHORIZATION_REQUIRED'):
        with c.transaction(): cancel(c,order,user,ack=ack,intent=intent)
    assert c.execute('select status from payment_orders where id=%s',(order[0],)).fetchone()[0]=='ready'

@pytest.mark.parametrize('kind',['owner','amount','done','failed'])
def test_intent_never_bypasses_owner_amount_or_financial_history(intent_db,kind):
    c=intent_db;actor,order,user=setup(c)
    if kind=='done': complete(c,order,'already-approved')
    if kind=='failed': c.execute("update payment_orders set status='failed' where id=%s",(order[0],))
    with pytest.raises(psycopg.errors.RaiseException):
        with c.transaction(): cancel(c,order,actor if kind=='owner' else user,amount=100 if kind=='amount' else 1100)

@pytest.mark.parametrize('resource',['points','coupon'])
def test_exact_resource_release_and_late_approval_quarantine(intent_db,resource):
    c=intent_db
    if resource=='points': order,user=pending_subsidy(c)
    else: _,order,user,coupon,_=coupon_order(c)
    c.execute('select admit_payment_checkout(%s)',(order[0],))
    result=cancel(c,order,user)
    assert cancel(c,order,user)==result
    if resource=='points':
        assert c.execute('select point_balance,point_reserved from app_users where id=%s',(user,)).fetchone()==(1000,0)
    else:
        assert c.execute('select status,reserved_order_id from user_coupons where id=%s',(coupon,)).fetchone()==('available',None)
    for tx in ['late-intent','second-late-intent']:
        assert complete(c,order,tx)['reconciliation_required'] is True
    assert cancel(c,order,user)['recovery_action']=='reconcile'
    for table in ['vouchers','refund_requests','payment_order_closures']:
        assert c.execute(f'select count(*) from {table} where order_id=%s',(order[0],)).fetchone()[0]==0

@pytest.mark.parametrize('rival',['approve','cancel'])
def test_intent_serializes_with_approval_and_replay(intent_db,notification_db,rival):
    c=intent_db;order,user=pending_subsidy(c)
    c.execute('select admit_payment_checkout(%s)',(order[0],));c.commit()
    barrier=Barrier(2)
    def run(which):
        with psycopg.connect(notification_db) as conn:
            barrier.wait()
            try: return complete(conn,order,'race-intent') if which=='approve' else cancel(conn,order,user)
            except psycopg.errors.RaiseException as exc: return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(run,'cancel');b=pool.submit(run,rival); outcomes=[a.result(),b.result()]
    state=c.execute('select status,point_reserved from payment_orders where id=%s',(order[0],)).fetchone()
    receipts=c.execute('select count(*) from payment_order_local_abandonments where order_id=%s',(order[0],)).fetchone()[0]
    assert (state,receipts) in [(('canceled',False),1),(('done',False),0)],outcomes
    assert c.execute('select point_balance,point_reserved from app_users where id=%s',(user,)).fetchone()==(1000 if state[0]=='canceled' else 900,0)

def test_http_explicit_intent_real_producer_and_recovery_readback(intent_db):
    from types import SimpleNamespace
    from unittest.mock import patch
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import payments
    from test_local_abandonment_postgres import LocalClient
    c=intent_db;_,order,user=setup(c)
    class Client(LocalClient):
        def rpc(self,name,args):
            if name=='abandon_owned_payment_order_intent':
                return cancel(self.db,order,user,amount=args['p_amount'],
                              ack=args['p_acknowledge_provider_uncertainty'],
                              intent=args['p_explicit_checkout_cancel_intent'])
            return super().rpc(name,args)
    repo=SimpleNamespace(client=Client(c),auth_user_from_token=lambda t:SimpleNamespace(id=user,email=None),
                         get_profile=lambda *a,**kw:SimpleNamespace(id=user,role='customer',status='active'))
    app=FastAPI();app.include_router(payments.router)
    with patch.object(payments,'JoinRepository',return_value=repo),patch.object(payments,'get_settings',return_value=SimpleNamespace()):
        client=TestClient(app);headers={'Authorization':'Bearer synthetic-owner'}
        response=client.post(f'/payments/orders/{order[1]}/abandon',headers=headers,
                             json={'amount':1100,'explicit_checkout_cancel_intent':True})
        assert response.status_code==200,response.text
        data=response.json()['data']
        assert data['order_id']==order[1] and data['user_id']==str(user)
        assert data['recovery_action']=='locally_abandoned'
        assert client.get('/payments/recovery',params={'order_id':order[1],'amount':1100},headers=headers).json()['data']==data
        assert complete(c,order,'late-http-intent')['reconciliation_required'] is True
        late=client.get('/payments/recovery',params={'order_id':order[1],'amount':1100},headers=headers).json()['data']
        assert late['recovery_action']=='reconcile'
        assert late['local_abandonment']==data['local_abandonment']


def test_new_function_is_service_only_and_table_remains_read_only(intent_db):
    c=intent_db;sig='abandon_owned_payment_order_intent(text,uuid,integer,boolean,boolean,text)'
    for role in ['anon','authenticated']:
        assert not c.execute("select has_function_privilege(%s,%s,'EXECUTE')",(role,sig)).fetchone()[0]
        assert not c.execute("select has_table_privilege(%s,'payment_order_local_abandonments','SELECT,INSERT,UPDATE,DELETE')",(role,)).fetchone()[0]
    assert c.execute("select has_function_privilege('service_role',%s,'EXECUTE')",(sig,)).fetchone()[0]
    assert not c.execute("select has_table_privilege('service_role','payment_order_local_abandonments','INSERT,UPDATE,DELETE')").fetchone()[0]
