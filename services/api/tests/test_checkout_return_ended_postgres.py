"""Unknown normal return provenance uses the same atomic local lifecycle."""
import pytest
import psycopg
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from test_checkout_cancel_intent_postgres import intent_db, db, notification_db
from test_failed_order_postgres import setup, pending_subsidy, coupon_order, complete

def ended(c,order,user,source='sdk_frame_fail',ack=None,intent=False):
    return c.execute('select abandon_owned_payment_order_intent(%s,%s,%s,%s,%s,%s)',(order[1],user,1100,ack,intent,source)).fetchone()[0]

@pytest.mark.parametrize('source',['sdk_frame_fail','mobile_fail'])
def test_truthful_ended_receipt_and_replay(intent_db,source):
    c=intent_db;_,order,user=setup(c)
    receipt=ended(c,order,user,source)
    assert receipt['recovery_action']=='locally_abandoned'
    assert receipt['local_abandonment']['provider_finality']=='unknown'
    assert ended(c,order,user,source)==receipt
    assert c.execute('select acknowledge_provider_uncertainty,explicit_checkout_cancel_intent,checkout_return_ended from payment_order_local_abandonments where order_id=%s',(order[0],)).fetchone()==(None,False,source)

@pytest.mark.parametrize('source,ack,intent',[('FAIL',None,False),('9999',None,False),('mobile_success',None,False),('sdk_frame_fail',True,False),('mobile_fail',None,True),('sdk_frame_fail',None,None)])
def test_unsafe_provenance_or_ambiguous_auth_rejected(intent_db,source,ack,intent):
    c=intent_db;_,order,user=setup(c)
    with pytest.raises(psycopg.errors.RaiseException,match='AUTHORIZATION'):
        with c.transaction():ended(c,order,user,source,ack,intent)
    assert c.execute('select status from payment_orders where id=%s',(order[0],)).fetchone()[0]=='ready'

@pytest.mark.parametrize('resource',['points','coupon'])
def test_ended_resources_exact_once_late_and_second_approval(intent_db,resource):
    c=intent_db
    if resource=='points':order,user=pending_subsidy(c)
    else:_,order,user,coupon,_=coupon_order(c)
    c.execute('select admit_payment_checkout(%s)',(order[0],))
    ended(c,order,user);ended(c,order,user)
    if resource=='points': assert c.execute('select point_balance,point_reserved from app_users where id=%s',(user,)).fetchone()==(1000,0)
    else:assert c.execute('select status,reserved_order_id from user_coupons where id=%s',(coupon,)).fetchone()==('available',None)
    for tx in ['ended-late','ended-second','ended-late']:assert complete(c,order,tx)['reconciliation_required'] is True
    assert ended(c,order,user)['recovery_action']=='reconcile'
    for table in ['vouchers','refund_requests','payment_order_closures']:assert c.execute(f'select count(*) from {table} where order_id=%s',(order[0],)).fetchone()[0]==0
    assert c.execute("select count(*) from payment_callback_discrepancies where order_id=%s and kind='late_approval'",(order[0],)).fetchone()[0]==2

@pytest.mark.parametrize('rival',['approve','stop'])
def test_ended_approval_race_and_idempotent_concurrency(intent_db,notification_db,rival):
    c=intent_db;order,user=pending_subsidy(c);c.execute('select admit_payment_checkout(%s)',(order[0],));c.commit();barrier=Barrier(2)
    def run(kind):
        with psycopg.connect(notification_db) as conn:
            barrier.wait()
            try:return complete(conn,order,'ended-race') if kind=='approve' else ended(conn,order,user)
            except psycopg.errors.RaiseException as e:return str(e)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(run,'stop');b=pool.submit(run,rival);a.result();b.result()
    status=c.execute('select status from payment_orders where id=%s',(order[0],)).fetchone()[0]
    assert status in ['done','canceled']
    assert c.execute('select count(*) from payment_order_local_abandonments where order_id=%s',(order[0],)).fetchone()[0]==(1 if status=='canceled' else 0)
    assert c.execute('select point_balance,point_reserved from app_users where id=%s',(user,)).fetchone()==(1000 if status=='canceled' else 900,0)

@pytest.mark.parametrize('kind',['foreign','done','approval_marker'])
def test_ended_never_grants_provider_or_other_owner_authority(intent_db,kind):
    c=intent_db;actor,order,user=setup(c)
    if kind=='done':complete(c,order,'ended-prior-approval')
    if kind=='approval_marker':c.execute("update payment_orders set provider_payment_key='synthetic-approval' where id=%s",(order[0],))
    with pytest.raises(psycopg.errors.RaiseException):
        with c.transaction():ended(c,order,actor if kind=='foreign' else user)
