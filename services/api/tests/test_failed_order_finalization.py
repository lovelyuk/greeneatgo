"""Synthetic fixtures only. No provider calls or production data."""
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import payments, platform

USER = '00000000-0000-4000-8000-000000000001'
ORDER = '00000000-0000-4000-8000-000000000002'
CLOSURE = '00000000-0000-4000-8000-000000000003'


def test_verified_closure_is_owner_scoped_and_bounded():
    app = FastAPI()
    app.include_router(payments.router)
    row = dict(id=ORDER, order_id='GE-fixture', user_id=USER, amount=100, status='canceled')
    closure = dict(id=CLOSURE, evidence_sha256='a'*64, outcome='canceled', closed_at='2026-10-14T00:00:00+00:00')
    with patch.object(payments, 'JoinRepository') as cls, patch.object(payments, 'get_settings', return_value=SimpleNamespace()):
        repo = cls.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id=USER, email=None)
        repo.get_profile.return_value = SimpleNamespace(id=USER, role='customer', status='active')
        repo.client.rest_get.side_effect = [[row], [closure], []]
        response = TestClient(app).get('/payments/recovery', params={'order_id':'GE-fixture','amount':100}, headers={'Authorization':'Bearer fixture'})
        assert response.status_code == 200
        data = response.json()['data']
        assert data == dict(order_id='GE-fixture', user_id=USER, amount=100, status='canceled', recovery_action='closed', checkout_url=None, resumable=False, completion=None, closure={**closure,'scope':'order','finality':'verified'})
        assert repo.client.rest_get.call_args_list[1].args[0] == 'payment_order_closures'
        assert repo.client.rest_get.call_args_list[1].args[1]['user_id'] == f'eq.{USER}'


def review_payload(**changes):
    body = dict(user_id=USER, amount=100, outcome='canceled', source_sha256='b'*64,
                source_reference='synthetic secured evidence reference', attempts=[dict(transaction_id='fixture-trx', outcome='failed')],
                authority='attempt_only', complete_attempt_coverage=False, irreversible_no_future_approval=False)
    return {**body, **changes}


def test_operator_producer_records_review_but_attempt_only_is_not_closure():
    app = FastAPI()
    app.include_router(platform.router)
    with patch.object(platform, 'JoinRepository') as cls:
        repo = cls.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id=USER, email=None)
        repo.get_profile.return_value = SimpleNamespace(id=USER, role='platform_admin', status='active')
        repo.client.rpc.return_value = {'recovery_action':'reconcile','closed':False}
        response = TestClient(app).post(f'/admin/platform/payment-orders/{ORDER}/review',json=review_payload(),headers={'Authorization':'Bearer fixture'})
        assert response.status_code == 200
        assert response.json()['data']['closed'] is False
        name, args = repo.client.rpc.call_args.args
        assert name == 'review_failed_payment_order'
        assert args['p_actor_id'] == USER
        assert args['p_order_id'] == ORDER
        assert len(args['p_evidence_sha256']) == 64
        assert args['p_evidence']['authority'] == 'attempt_only'
        assert args['p_dry_run'] is True

def test_checkout_admission_is_committed_before_hash_for_every_type():
    import pytest
    from fastapi import HTTPException
    from app.repositories.supabase_http import SupabaseHttpError
    for pay_type in ['direct','voucher','subsidized']:
        row = dict(id=ORDER,order_id='GE-fixture',user_id=USER,amount=100,status='ready',pay_type=pay_type,tax_type='taxable',requested_payment_method='TOTAL')
        with patch.object(payments,'JoinRepository') as cls, patch.object(payments,'get_settings',return_value=SimpleNamespace(kiwoompay_cpid='FIXTURE',kiwoompay_base_url='https://example.invalid',public_api_base_url='https://example.invalid',kiwoompay_app_url='fixture://')), patch.object(payments,'_enforce_subsidized_order_expiry',side_effect=lambda repo,o:o), patch.object(payments,'_ensure_voucher_order_available'), patch.object(payments,'request_payment_hash') as provider:
            repo=cls.return_value
            repo.client.rest_get.return_value=[row]
            repo.client.rpc.side_effect=SupabaseHttpError(409,'fixture admission denied')
            with pytest.raises(HTTPException):
                payments.checkout('fixture-token')
            provider.assert_not_called()
            assert repo.client.rpc.call_args.args == ('admit_payment_checkout',{'p_order_id':ORDER})


def test_late_approval_reaches_durable_rpc_before_ack():
    app=FastAPI()
    app.include_router(payments.router)
    with patch.object(payments,'JoinRepository') as cls, patch.object(payments,'get_settings',return_value=SimpleNamespace(kiwoompay_cpid='FIXTURE',kiwoompay_notification_ips=[])):
        repo=cls.return_value
        repo.client.rest_get.return_value=[dict(id=ORDER,order_id='GE-fixture',amount=100,status='canceled')]
        response=TestClient(app).get('/payments/notification',params=dict(CPID='FIXTURE',ORDERNO='GE-fixture',DAOUTRX='fixture-trx',AMOUNT=100,PAYMETHOD='CARD'))
        assert response.status_code==200 and '<RESULT>SUCCESS</RESULT>' in response.text
        assert repo.client.rpc.call_args.args[0]=='complete_kiwoom_payment_notification'


def test_failure_notification_requires_durable_record_before_ack():
    app=FastAPI()
    app.include_router(payments.router)
    from app.repositories.supabase_http import SupabaseHttpError
    with patch.object(payments,'JoinRepository') as cls, patch.object(payments,'get_settings',return_value=SimpleNamespace(kiwoompay_cpid='FIXTURE',kiwoompay_notification_ips=[])):
        repo=cls.return_value
        client=TestClient(app)
        params=dict(CPID='FIXTURE',DAOUTRX='fixture-trx',AMOUNT=100,PAYMETHOD='BANK_CANCEL',CANCELDATE='20261014090000')
        assert '<RESULT>SUCCESS</RESULT>' in client.get('/payments/notification',params=params).text
        assert repo.client.rpc.call_args.args[0]=='record_kiwoom_nonapproval_notification'
        repo.client.rpc.side_effect=SupabaseHttpError(500,'fixture durable write failed')
        response=client.get('/payments/notification',params=params)
        assert response.status_code==500 and '<RESULT>FAIL</RESULT>' in response.text

def test_operator_permission_schema_and_attestation_fail_closed():
    import pytest
    from pydantic import ValidationError
    from app.services.failed_order_review import FailedOrderReview
    for changes in [dict(source_sha256='A'*64),dict(amount=True),dict(dry_run='false'),dict(actor_id=USER),dict(authority='trusted_provider_irreversible_closure'),dict(attempts=[dict(transaction_id='same',outcome='failed')]*2),dict(authority='no_issued_form'), dict(source_reference=' '*20), dict(authority='trusted_provider_irreversible_closure',complete_attempt_coverage=True,irreversible_no_future_approval=True,provider_closure_reference=' '*20)]:
        with pytest.raises(ValidationError):
            FailedOrderReview(**review_payload(**changes))
    app=FastAPI();app.include_router(platform.router)
    with patch.object(platform,'JoinRepository') as cls:
        repo=cls.return_value
        repo.auth_user_from_token.return_value=SimpleNamespace(id=USER,email=None)
        for role in ['customer','employee','merchant_admin','company_admin']:
            repo.get_profile.return_value=SimpleNamespace(id=USER,role=role,status='active')
            response=TestClient(app).post(f'/admin/platform/payment-orders/{ORDER}/review',json=review_payload(),headers={'Authorization':'Bearer fixture'})
            assert response.status_code==403
        repo.client.rpc.assert_not_called()


def test_malformed_or_missing_closure_never_discards_pending_intent():
    from app.services.payment_closure import public_closure
    for value in [{},dict(id=CLOSURE,evidence_sha256='A'*64,outcome='canceled',closed_at='2026-10-14T00:00:00Z'),dict(id=CLOSURE,evidence_sha256='a'*64,outcome='failed',closed_at='2026-10-14T00:00:00Z'),dict(id=CLOSURE,evidence_sha256='a'*64,outcome='canceled',closed_at='2026-10-14')]:
        assert public_closure(value,'canceled') is None

def test_revocation_during_hash_does_not_emit_payable_form():
    import pytest
    from fastapi import HTTPException
    from app.repositories.supabase_http import SupabaseHttpError
    row=dict(id=ORDER,order_id='GE-fixture',user_id=USER,amount=100,status='ready',pay_type='direct',tax_type='taxable',requested_payment_method='TOTAL',product_name='fixture')
    settings=SimpleNamespace(kiwoompay_cpid='FIXTURE',kiwoompay_base_url='https://example.invalid',public_api_base_url='https://example.invalid',kiwoompay_app_url='fixture://')
    with patch.object(payments,'JoinRepository') as cls, patch.object(payments,'get_settings',return_value=settings), patch.object(payments,'request_payment_hash',return_value='synthetic-hash') as provider:
        repo=cls.return_value
        repo.client.rest_get.return_value=[row]
        repo.client.rpc.side_effect=[{'admitted':True},SupabaseHttpError(409,'fixture revocation during hash')]
        with pytest.raises(HTTPException):
            payments.checkout('fixture-token')
        provider.assert_called_once()
        assert [c.args[0] for c in repo.client.rpc.call_args_list]==['admit_payment_checkout','assert_payment_checkout_active']

def test_late_approval_contradicts_closure_and_recovery_reconciles():
    app=FastAPI();app.include_router(payments.router)
    row=dict(id=ORDER,order_id='GE-fixture',user_id=USER,amount=100,status='canceled')
    closure=dict(id=CLOSURE,evidence_sha256='a'*64,outcome='canceled',closed_at='2026-10-14T00:00:00Z')
    with patch.object(payments,'JoinRepository') as cls,patch.object(payments,'get_settings',return_value=SimpleNamespace()):
        repo=cls.return_value
        repo.auth_user_from_token.return_value=SimpleNamespace(id=USER,email=None)
        repo.get_profile.return_value=SimpleNamespace(id=USER,role='customer',status='active')
        repo.client.rest_get.side_effect=[[row],[closure],[dict(id='synthetic-discrepancy')]]
        response=TestClient(app).get('/payments/recovery',params=dict(order_id='GE-fixture',amount=100),headers={'Authorization':'Bearer fixture'})
        assert response.status_code==200
        assert response.json()['data']['recovery_action']=='reconcile'
        assert 'closure' not in response.json()['data']
