"""Local synthetic FastAPI/PostgreSQL adapter, never production/provider I/O.
Run with FINALIZE_TEST_DATABASE_URL bound to the dedicated loopback database.
Only transport/auth are replaced. Review/hash, recovery and purchase routers
and migration RPCs are the actual production code.
"""
import json
import os
import socket
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'services/api'), str(ROOT / 'services/api/tests')]
URL = os.environ['FINALIZE_TEST_DATABASE_URL']
u = urlparse(URL)
assert u.hostname == '127.0.0.1' and u.port == 55487 and u.path == '/phoneauth_test_frontend_finalize', 'dedicated local synthetic DB required'
connect = socket.socket.connect

def local_connect(sock, address):
    if isinstance(address, tuple):
        assert address[:2] == ('127.0.0.1', 55487), 'external network forbidden'
    return connect(sock, address)
socket.socket.connect = local_connect
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.config import Settings
from app.routers import payments, platform, voucher_products
from app.repositories.supabase_http import SupabaseHttpError

OWNER = '11111111-1111-4111-8111-111111111111'
ACTOR = '22222222-2222-4222-8222-222222222222'
MERCHANT = '33333333-3333-4333-8333-333333333333'
PRODUCT = '44444444-4444-4444-8444-444444444444'
OLD = 'GE-synthetic-closed'
settings = Settings(supabase_url='https://fixture.invalid', supabase_anon_key='synthetic', supabase_service_role_key='synthetic', env='test', pilot_merchant_id=MERCHANT, public_api_base_url='http://127.0.0.1:4175/api-fixture')
if os.environ.get('RETURN_ENDED_FIXTURE') == '1':
    from dataclasses import replace
    settings = replace(settings,admin_app_url='http://127.0.0.1:4175',kiwoompay_cpid='TEST0001',kiwoompay_base_url='https://apitest.kiwoompay.co.kr')

class SqlClient:
    def __init__(self, db):
        self.db = db
        self.settings = settings
    def rest_get(self, table, params):
        allowed = {'payment_order_local_abandonments', 'payment_orders', 'payment_order_closures', 'payment_callback_discrepancies', 'voucher_products', 'merchants', 'app_users'}
        assert table in allowed, table
        select = params.get('select', '*')
        columns = sql.SQL('*') if select == '*' else sql.SQL(',').join(sql.Identifier(c) for c in select.split(','))
        query = sql.SQL('select {} from {} where true').format(columns, sql.Identifier(table))
        args = []
        for key, value in params.items():
            if key in {'select', 'order', 'limit'}:
                continue
            if value == 'is.null':
                query += sql.SQL(' and {} is null').format(sql.Identifier(key))
            else:
                assert value.startswith(('eq.', 'neq.')), (key, value)
                op = sql.SQL('<>') if value.startswith('neq.') else sql.SQL('=')
                query += sql.SQL(' and {}{}%s').format(sql.Identifier(key), op)
                args.append(value.split('.', 1)[1])
        if 'order' in params:
            orders = []
            for term in params['order'].split(','):
                col, direction = term.split('.')
                assert direction in {'asc', 'desc'}
                orders.append(sql.SQL('{} {}').format(sql.Identifier(col), sql.SQL(direction)))
            query += sql.SQL(' order by ') + sql.SQL(',').join(orders)
        if 'limit' in params:
            query += sql.SQL(' limit %s'); args.append(int(params['limit']))
        rows = self.db.execute(query, args).fetchall()
        # PostgREST transport emits UUID/timestamptz as JSON strings.
        return json.loads(json.dumps(rows, default=lambda value: value.isoformat() if hasattr(value, 'isoformat') else str(value)))
    def rest_post(self, table, values):
        assert table == 'payment_orders'
        keys = list(values)
        query = sql.SQL('insert into {} ({}) values ({}) returning *').format(sql.Identifier(table),
            sql.SQL(',').join(map(sql.Identifier, keys)), sql.SQL(',').join(sql.Placeholder() for _ in keys))
        return self.db.execute(query, [Jsonb(values[k]) if isinstance(values[k], dict) else values[k] for k in keys]).fetchall()
    def rpc(self, name, args):
        assert name in {'review_failed_payment_order', 'admit_payment_checkout', 'assert_payment_checkout_active', 'abandon_owned_payment_order', 'abandon_owned_payment_order_intent'}
        query = sql.SQL('select {}({}) as result').format(sql.Identifier(name), sql.SQL(',').join(
            sql.SQL('{} => %s').format(sql.Identifier(k)) for k in args))
        try:
            with self.db.transaction():
                return self.db.execute(query, [Jsonb(v) if isinstance(v, dict) else v for v in args.values()]).fetchone()['result']
        except psycopg.Error as exc:
            raise SupabaseHttpError(409, str(exc)) from exc

class Repo:
    def __init__(self, db): self.client = SqlClient(db)
    def auth_user_from_token(self, token):
        assert token in {'fixture-access', 'fixture-operator'}
        return SimpleNamespace(id=ACTOR if token == 'fixture-operator' else OWNER, email=None)
    def get_profile(self, user_id, email=None):
        row = self.client.rest_get('app_users', {'select':'*', 'id':f'eq.{user_id}'})[0]
        row['id'] = str(row['id'])
        return SimpleNamespace(**row)

def initialize(local=False, bank=False):
    with psycopg.connect(URL.replace('/phoneauth_test_frontend_finalize', '/postgres'), autocommit=True) as db:
        if not db.execute("select 1 from pg_database where datname='phoneauth_test_frontend_finalize'").fetchone():
            db.execute('create database phoneauth_test_frontend_finalize')
    os.environ['TEST_DATABASE_URL'] = URL
    from test_kiwoom_notification_postgres import notification_db
    notification_db.__wrapped__()
    with psycopg.connect(URL, row_factory=dict_row) as db:
        for name in ['0064_failed_order_finalization.sql','0065_manual_database_order_closure.sql','0066_owner_local_abandonment.sql','0067_explicit_checkout_cancel_intent.sql']:
            db.execute((ROOT / 'supabase/migrations' / name).read_text())
        db.execute("insert into app_users(id,display_name,role,status) values(%s,'Synthetic buyer','customer','active'),(%s,'Synthetic operator','platform_admin','active')", (OWNER, ACTOR))
        db.execute("insert into merchants(id,name,qr_token,view_token) values(%s,'Synthetic merchant','synthetic-qr','synthetic-view')", (MERCHANT,))
        db.execute("insert into voucher_products(id,merchant_id,name,voucher_count,unit_price,tax_type) values(%s,%s,'Synthetic ticket',1,1100,'taxable')", (PRODUCT, MERCHANT))
        if bank: db.execute("update voucher_products set kiwoom_pay_method='BANK' where id=%s",(PRODUCT,))
        db.execute("insert into payment_orders(order_id,checkout_token,user_id,merchant_id,voucher_product_id,merchant_name,product_name,amount,status,pay_type,tax_type,voucher_count,paid_voucher_count,bonus_voucher_count,voucher_purchase_price,gross_amount,requested_point_amount) values(%s,'synthetic-old-token',%s,%s,%s,'Synthetic merchant','Synthetic ticket',1100,'ready','voucher','taxable',1,1,0,1100,1100,0)", (OLD, OWNER, MERCHANT, PRODUCT))
        order = db.execute('select id from payment_orders where order_id=%s', (OLD,)).fetchone()['id']
        db.execute('select admit_payment_checkout(%s)', (order,))
        if not local: db.execute("update payment_orders set status='failed' where id=%s", (order,))
    return {'owner':OWNER, 'product_id':PRODUCT, 'order_id':OLD, 'internal_id':str(order), 'amount':1100}

def request(payload):
    with psycopg.connect(URL, row_factory=dict_row) as db, ExitStack() as stack:
        repo = Repo(db)
        for module in [payments, platform, voucher_products]:
            stack.enter_context(patch.object(module, 'JoinRepository', return_value=repo))
        for module in [payments, voucher_products]:
            stack.enter_context(patch.object(module, 'get_settings', return_value=settings))
        stack.enter_context(patch.object(payments, 'request_payment_hash', **({'return_value':'synthetic-transport-hash'} if os.environ.get('RETURN_ENDED_FIXTURE') == '1' else {'side_effect':AssertionError('provider forbidden')})))
        app = FastAPI()
        for module in [payments, platform, voucher_products]: app.include_router(module.router)
        app.include_router(payments.short_redirect_router)
        response = TestClient(app).request(payload.get('method', 'GET'), payload['path'],
            json=payload.get('body'), headers={'Authorization':'Bearer ' + payload.get('token', 'fixture-access')})
        return {'status': response.status_code, **({'json': response.json()} if 'application/json' in response.headers.get('content-type','') else {'html': response.text})}

def audit():
    with psycopg.connect(URL, row_factory=dict_row) as db:
        return {
            'orders': db.execute('select order_id,status,checkout_started_at is not null as started from payment_orders order by created_at').fetchall(),
            'closures': db.execute('select id,evidence_sha256,outcome,closed_at from payment_order_closures').fetchall(),
            'reviews': db.execute('select count(*) as count from payment_order_reviews').fetchone(),
            'local_receipts': db.execute('select * from payment_order_local_abandonments').fetchall(),
            'discrepancies': db.execute('select kind,transaction_id from payment_callback_discrepancies').fetchall(),
            'voucher_count': db.execute('select count(*) as count from vouchers').fetchone(),
            'refund_count': db.execute('select count(*) as count from refund_requests').fetchone(),
        }

def late_approval(provider_order_id=OLD):
    with psycopg.connect(URL, row_factory=dict_row) as db:
        order = db.execute('select id,order_id,amount from payment_orders where order_id=%s', (provider_order_id,)).fetchone()
        return db.execute("select complete_kiwoom_payment_notification(%s,%s,'TEST0001',%s,'CARD','synthetic-late-local',%s,'127.0.0.1') as result",
            (order['id'],order['order_id'],order['amount'],Jsonb({'RESULTCODE':'0000','DAOUTRX':'synthetic-late-local','AMOUNT':str(order['amount']),'PAYMETHOD':'CARD'}))).fetchone()['result']


command = sys.argv[1]
result = initialize(local=command!='init',bank=command=='init-bank') if command in {'init','init-local','init-bank'} else audit() if command == 'audit' else late_approval() if command == 'late-local' else late_approval(json.loads(sys.argv[2])['order_id']) if command == 'approve' else request(json.loads(sys.argv[2]))
print(json.dumps(result, default=str))
