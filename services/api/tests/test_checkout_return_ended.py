"""Normal return is local-stop intent, never verified cancel/PG authority."""
import pytest
from test_local_abandonment import harness, HEADERS, USER

@pytest.mark.parametrize('source',['sdk_frame_fail','mobile_fail'])
def test_ended_provenance_without_fabricated_ack(harness,source):
    client,repo=harness
    response=client.post('/payments/orders/GE-synthetic/abandon',headers=HEADERS,json={'amount':100,'checkout_return_ended':source})
    assert response.status_code==200,response.text
    repo.client.rpc.assert_called_once_with('abandon_owned_payment_order_intent',dict(p_order_id='GE-synthetic',p_user_id=USER,p_amount=100,p_acknowledge_provider_uncertainty=None,p_explicit_checkout_cancel_intent=False,p_checkout_return_ended=source))

@pytest.mark.parametrize('source',[True,'FAIL','cancel','9999','mobile_success',None,{}])
def test_unsafe_ended_source_rejected(harness,source):
    client,repo=harness
    response=client.post('/payments/orders/GE-synthetic/abandon',headers=HEADERS,json={'amount':100,'checkout_return_ended':source})
    assert response.status_code==422
    repo.client.rpc.assert_not_called()

def test_ended_and_warning_not_both(harness):
    client,repo=harness
    assert client.post('/payments/orders/GE-synthetic/abandon',headers=HEADERS,json={'amount':100,'checkout_return_ended':'sdk_frame_fail','acknowledge_provider_uncertainty':True}).status_code==422
    repo.client.rpc.assert_not_called()
