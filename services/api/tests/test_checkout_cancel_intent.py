"""Explicit local intent is not fabricated uncertainty consent or PG finality."""
import pytest
from test_local_abandonment import harness, HEADERS, USER
from test_pc_sdk_checkout import seam, PATH

NONCE='0123456789abcdef0123456789abcdef'

def test_distinct_explicit_intent_authorization(harness):
    client,repo=harness
    result=client.post('/payments/orders/GE-synthetic/abandon',headers=HEADERS,
                       json={'amount':100,'explicit_checkout_cancel_intent':True})
    assert result.status_code==200,result.text
    repo.client.rpc.assert_called_once_with('abandon_owned_payment_order_intent',dict(
        p_order_id='GE-synthetic',p_user_id=USER,p_amount=100,
        p_acknowledge_provider_uncertainty=None,p_explicit_checkout_cancel_intent=True))
    assert result.json()['data']['local_abandonment']['provider_finality']=='unknown'

@pytest.mark.parametrize('body',[
    {'explicit_checkout_cancel_intent':False}, {'explicit_checkout_cancel_intent':'true'},
    {'explicit_checkout_cancel_intent':1}, {'explicit_checkout_cancel_intent':None},
    {'explicit_checkout_cancel_intent':True,'acknowledge_provider_uncertainty':True},
    {'explicit_checkout_cancel_intent':True,'provider_finality':'verified'},
])
def test_invalid_intent_never_mutates(harness,body):
    client,repo=harness
    assert client.post('/payments/orders/GE-synthetic/abandon',headers=HEADERS,json={'amount':100,**body}).status_code==422
    repo.client.rpc.assert_not_called()

@pytest.mark.parametrize('sdk',[False,True])
def test_configured_same_origin_hash_return_urls(seam,sdk):
    s=seam;s.settings.admin_app_url='https://shop.example'
    if sdk:
        response=s.client.post(PATH+'?return_nonce='+NONCE,headers={'Authorization':'Bearer fixture-owner-token'})
        assert response.status_code==200,response.text
        fields=response.json()['data']['fields']
        for key,kind in [('CLOSEURL','cancel'),('FAILURL','fail'),('RETURNURL','success'),('HOMEURL','success')]:
            assert fields[key]==f'https://shop.example/payment-return#{kind}.{NONCE}'
            assert len(fields[key])<=100
    else:
        from unittest.mock import patch
        from app.routers import payments
        repo=payments.JoinRepository()
        repo.rest_get=lambda table,params:[dict(s.order)]
        with patch.object(payments,'JoinRepository',return_value=repo):
            response=s.client.get('/payments/checkout/fixture-checkout-token?return_nonce='+NONCE)
        # Native GET lookup deliberately has no user_id filter.
        assert response.status_code==200,response.text
        assert f'name="CLOSEURL" value="https://shop.example/payment-return#cancel.{NONCE}"' in response.text
        assert f'name="FAILURL" value="https://shop.example/payment-return#fail.{NONCE}"' in response.text

@pytest.mark.parametrize('nonce',['short','A'*32,'g'*32,'a'*33,'a'*31,'a'*32+'%0A'])
def test_bad_correlation_is_rejected_before_admission(seam,nonce):
    s=seam
    result=s.client.post(PATH+'?return_nonce='+nonce,headers={'Authorization':'Bearer fixture-owner-token'})
    assert result.status_code==422,result.text
    assert s.events==[]

@pytest.mark.parametrize('origin',['https://user:pass@shop.example','javascript:alert(1)','https://shop.example?url=https://evil.example','https://'+('x'*70)+'.example'])
def test_bad_config_fails_before_checkout_admission(seam,origin):
    s=seam;s.settings.admin_app_url=origin
    result=s.client.post(PATH+'?return_nonce='+NONCE,headers={'Authorization':'Bearer fixture-owner-token'})
    assert result.status_code==503,result.text
    assert not s.hashes and 'admit_payment_checkout' not in s.events
