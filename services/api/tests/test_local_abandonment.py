"""Owner token and fail-closed API contract; all identifiers/data synthetic."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers import payments
from app.repositories.supabase_http import SupabaseHttpError
from app.services.local_abandonment import public_local_abandonment

USER='00000000-0000-4000-8000-000000000001'
ORDER='00000000-0000-4000-8000-000000000002'
RECEIPT='00000000-0000-4000-8000-000000000003'
ROW=dict(id=ORDER,order_id='GE-synthetic',user_id=USER,amount=100,status='canceled')
RECORD=dict(id=RECEIPT,order_id=ORDER,user_id=USER,amount=100,source='owner_request',scope='local_order',outcome='abandoned',requested_by=USER,requested_at='2026-10-14T00:00:00+00:00',provider_finality='unknown',residual_late_approval_possible=True)
BODY=dict(amount=100,acknowledge_provider_uncertainty=True)
HEADERS={'Authorization':'Bearer synthetic-owner'}

@pytest.fixture
def harness():
    repo=Mock()
    repo.auth_user_from_token.return_value=SimpleNamespace(id=USER,email=None)
    repo.get_profile.return_value=SimpleNamespace(id=USER,role='customer',status='active')
    def get(table,filters):
        if table=='payment_orders': return [ROW.copy()]
        if table=='payment_order_closures': return []
        if table=='payment_order_local_abandonments': return [RECORD.copy()]
        if table in ['payment_callback_discrepancies','payment_order_operator_local_stops','payment_notification_inbox']: return []
        raise AssertionError(table)
    repo.client.rest_get.side_effect=get
    app=FastAPI();app.include_router(payments.router)
    with patch.object(payments,'JoinRepository',return_value=repo),patch.object(payments,'get_settings',return_value=SimpleNamespace()):
        yield TestClient(app),repo


def test_actual_owner_token_is_resolved_and_service_rpc_identity_is_not_client_actor(harness):
    client,repo=harness
    response=client.post('/payments/orders/GE-synthetic/abandon',json=BODY,headers=HEADERS)
    assert response.status_code==200,response.text
    repo.auth_user_from_token.assert_called_with('synthetic-owner')
    repo.client.rpc.assert_called_once_with('abandon_owned_payment_order',dict(p_order_id='GE-synthetic',p_user_id=USER,p_amount=100,p_acknowledge_provider_uncertainty=True))
    assert response.json()['data']==dict(order_id='GE-synthetic',user_id=USER,amount=100,status='canceled',recovery_action='locally_abandoned',resumable=False,checkout_url=None,completion=None,local_abandonment={k:v for k,v in RECORD.items() if k not in ['order_id','user_id','amount']})

@pytest.mark.parametrize('body',[
    {},{'amount':100},dict(BODY,acknowledge_provider_uncertainty=False),
    dict(BODY,acknowledge_provider_uncertainty='true'),dict(BODY,acknowledge_provider_uncertainty=1),
    dict(BODY,acknowledge_provider_uncertainty=None),dict(BODY,amount=0),dict(BODY,amount=True),dict(BODY,amount='100'),
    dict(BODY,user_id=USER),dict(BODY,actor_id=USER),dict(BODY,provider_finality='verified'),
])
def test_malformed_or_unconsented_request_never_reaches_rpc(harness,body):
    client,repo=harness
    assert client.post('/payments/orders/GE-synthetic/abandon',json=body,headers=HEADERS).status_code==422
    repo.client.rpc.assert_not_called()

@pytest.mark.parametrize('path',['/payments/orders/GE-synthetic/abandon','/payments/local-abandonments','/payments/recovery?order_id=GE-synthetic&amount=100'])
def test_unauthenticated_paths_fail_closed(harness,path):
    client,repo=harness
    response=client.post(path,json=BODY) if path.endswith('/abandon') else client.get(path)
    assert response.status_code==401
    repo.client.rpc.assert_not_called()

@pytest.mark.parametrize('role,status',[('platform_admin','active'),('merchant_admin','active'),('customer','blocked')])
def test_not_application_admin_or_inactive_owner_bypass(harness,role,status):
    client,repo=harness
    repo.get_profile.return_value=SimpleNamespace(id=USER,role=role,status=status)
    assert client.post('/payments/orders/GE-synthetic/abandon',json=BODY,headers=HEADERS).status_code==403
    repo.client.rpc.assert_not_called()

@pytest.mark.parametrize('error,status',[
    ('ORDER_NOT_FOUND',404),('AMOUNT_MISMATCH',400),('ORDER_HAS_PAYMENT_OR_RESOURCE_HISTORY',409),
    ('COUPON_RESERVATION_CONFLICT',409),('RESERVATION_OWNERSHIP_CONFLICT',409),('storage unavailable',503),
])
def test_service_failures_never_emit_receipt(harness,error,status):
    client,repo=harness
    repo.client.rpc.side_effect=SupabaseHttpError(400,error)
    response=client.post('/payments/orders/GE-synthetic/abandon',json=BODY,headers=HEADERS)
    assert response.status_code==status
    assert 'local_abandonment' not in response.text

@pytest.mark.parametrize('change',[
    {'id':'invalid'}, {'order_id':USER}, {'user_id':ORDER}, {'amount':101}, {'amount':True},
    {'source':'trusted_provider'}, {'scope':'order'}, {'outcome':'canceled'}, {'requested_by':ORDER},
    {'requested_at':'not-iso'}, {'requested_at':'2026-10-14T00:00:00'},
    {'provider_finality':'verified'}, {'residual_late_approval_possible':False},
])
def test_malformed_stored_receipt_cannot_retire_intent(change):
    with pytest.raises((ValueError,KeyError,TypeError)):
        public_local_abandonment({**RECORD,**change},order=ROW,owner=USER)


def test_successful_rpc_without_durable_readback_is_503(harness):
    client,repo=harness
    repo.client.rest_get.side_effect=[[ROW],[],[]]
    response=client.post('/payments/orders/GE-synthetic/abandon',json=BODY,headers=HEADERS)
    assert response.status_code==503


def test_late_charge_keeps_receipt_not_verified_closure(harness):
    client,repo=harness
    repo.client.rest_get.side_effect=[[ROW],[],[RECORD],[],[{'kind':'late_approval'}],[]]
    response=client.get('/payments/recovery',params=dict(order_id='GE-synthetic',amount=100),headers=HEADERS)
    assert response.status_code==200
    data=response.json()['data']
    assert data['recovery_action']=='reconcile' and data['local_abandonment']['provider_finality']=='unknown'
    assert 'closure' not in data and data['completion'] is None


def test_ready_recovery_is_read_only_no_expiry_or_reservation_mutation(harness):
    client,repo=harness
    repo.client.rest_get.side_effect=lambda table,filters: [{**ROW,'status':'ready','pay_type':'direct','tax_type':'taxable'}] if table=='payment_orders' else []
    with patch.object(payments,'_enforce_subsidized_order_expiry',side_effect=lambda repo,order:order) as expiry, patch.object(payments,'_ensure_voucher_order_available'):
        response=client.get('/payments/recovery?order_id=GE-synthetic&amount=100',headers=HEADERS)
    assert response.status_code==200,response.text
    expiry.assert_not_called()
    repo.client.rpc.assert_not_called()


def test_popup_return_pages_are_hints_not_finality_and_offer_safe_window_close():
    app=FastAPI(); app.include_router(payments.short_redirect_router)
    client=TestClient(app)
    for path in ['/p','/c','/f']:
        result=client.get(path)
        assert result.status_code==200
        assert 'PG 승인·취소·환불 확정이 아닙니다' in result.text
        assert 'window.close()' in result.text
        assert 'postMessage' not in result.text and 'opener' not in result.text


def test_history_is_owner_scoped_bounded_and_no_provider_details(harness):
    client,repo=harness
    response=client.get('/payments/local-abandonments?limit=10',headers=HEADERS)
    assert response.status_code==200
    table,filters=repo.client.rest_get.call_args_list[0].args
    assert table=='payment_order_local_abandonments' and filters['user_id']=='eq.'+USER and filters['limit']=='10'
    assert 'checkout_token' not in response.text and 'payload' not in response.text
    assert client.get('/payments/local-abandonments?limit=51',headers=HEADERS).status_code==422
