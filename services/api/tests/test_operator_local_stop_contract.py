"""Producer -> real recovery serializer -> frontend discriminated validator."""
from types import SimpleNamespace
from unittest.mock import patch
import json
import subprocess
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from test_operator_local_stop_postgres import db, notification_db, setup, evidence, stop, complete, MIGRATIONS
from test_local_abandonment_postgres import LocalClient, db as owner_db
from app.services.local_abandonment import public_operator_local_stop

class OperatorClient(LocalClient):
    def rest_get(self,table,filters):
        if table in ['payment_order_operator_local_stops','payment_notification_inbox']:
            from psycopg import sql
            columns=filters['select'].split(',');where=[];values=[]
            for key,value in filters.items():
                if key in ['select','limit','order']: continue
                assert value.startswith('eq.')
                where.append(sql.SQL('{}=%s').format(sql.Identifier(key)));values.append(value[3:])
            rows=self.db.execute(sql.SQL('select {} from {} where {} limit {}').format(sql.SQL(',').join(map(sql.Identifier,columns)),sql.Identifier(table),sql.SQL(' and ').join(where),sql.Literal(int(filters.get('limit',1)))),values).fetchall()
            return [json.loads(json.dumps(dict(zip(columns,row)),default=lambda v:v.isoformat() if hasattr(v,'isoformat') else str(v))) for row in rows]
        return super().rest_get(table,filters)

def test_exact_legacy_pending_real_receipt_api_frontend_and_late_charge(db):
    from app.routers import payments
    _,order,user=setup(db)
    db.execute('update payment_orders set checkout_guard_epoch=null where id=%s',(order[0],))
    e=evidence(db,order);r=stop(db,order,e);db.commit()
    repo=SimpleNamespace(client=OperatorClient(db),auth_user_from_token=lambda t:SimpleNamespace(id=user,email=None),get_profile=lambda *a,**kw:SimpleNamespace(id=user,role='customer',status='active'))
    app=FastAPI();app.include_router(payments.router);client=TestClient(app);headers={'Authorization':'Bearer synthetic-owner'}
    with patch.object(payments,'JoinRepository',return_value=repo),patch.object(payments,'get_settings',return_value=SimpleNamespace()):
        response=client.get('/payments/recovery',params=dict(order_id=order[1],amount=1100),headers=headers)
        assert response.status_code==200,response.text
        dto=response.json()['data'];receipt=dto['local_abandonment']
        assert dto['recovery_action']=='locally_abandoned'
        assert receipt['source']=='manual_database_operator' and receipt['actor_kind']=='database_operator'
        assert 'requested_by' not in receipt and 'evidence' not in receipt and 'actor_session_user' not in receipt
        assert receipt['id']==r['receipt_id']
        script="import {validLocalAbandonment} from './src/paymentClosure.js'; const r=JSON.parse(process.argv[1]); if(!validLocalAbandonment(r,{order_id:r.order_id,amount:r.amount},r.user_id)) process.exit(1);"
        subprocess.run(['node','--input-type=module','-e',script,json.dumps(dto)],cwd=MIGRATIONS.parents[1]/'apps/admin',check=True)
        history=client.get('/payments/local-abandonments',headers=headers)
        assert history.status_code==200,history.text
        assert history.json()['data']['orders']==[dto]
        complete(db,order,'late-api-synthetic');late=client.get('/payments/recovery',params=dict(order_id=order[1],amount=1100),headers=headers).json()['data']
        assert late['recovery_action']=='reconcile' and late['local_abandonment']==receipt
        subprocess.run(['node','--input-type=module','-e',script.replace('if(!valid','if(valid'),json.dumps(late)],cwd=MIGRATIONS.parents[1]/'apps/admin',check=True)

@pytest.mark.parametrize('change',[{'actor_kind':'owner'},{'actor_session_user':'service_role'},{'actor_current_user':'other'},{'source':'owner_request'},{'requested_by':'00000000-0000-4000-8000-000000000001'},{'reason':'provider_failed'},{'evidence_sha256':'bad'},{'provider_finality':'verified'}])
def test_public_operator_receipt_rejects_wrong_authority(db,change):
    _,order,user=setup(db);stop(db,order,evidence(db,order))
    row=db.execute('select to_jsonb(r) from payment_order_operator_local_stops r where order_id=%s',(order[0],)).fetchone()[0]
    o=db.execute('select to_jsonb(o) from payment_orders o where id=%s',(order[0],)).fetchone()[0]
    with pytest.raises((ValueError,KeyError,TypeError)):
        public_operator_local_stop({**row,**change},order=o,owner=str(user))
