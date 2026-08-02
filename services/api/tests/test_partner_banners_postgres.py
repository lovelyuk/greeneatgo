"""Real PostgreSQL coverage for the partner-banner reward critical section.

This module intentionally never drops schemas/databases. TEST_DATABASE_URL must point
at a database whose normal migration chain has already been applied. Rows use random
UUIDs, so this can safely share a CI PostgreSQL instance with other integration suites. Immutable point-ledger evidence is deliberately
retained under random UUIDs; the suite never attempts to bypass ledger protections.
"""
from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

MIGRATION = Path(__file__).resolve().parents[3] / "infra/migrations/0060_partner_banners.sql"


@pytest.fixture(scope="module")
def banner_db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to run partner-banner PostgreSQL integration tests")
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(url, autocommit=True) as conn:
        required = ("partners", "partner_banners", "banner_rewards", "banner_reward_grants", "user_coupons")
        missing = [name for name in required if conn.execute("select to_regclass(%s)", (f"public.{name}",)).fetchone()[0] is None]
        if missing:
            pytest.skip(f"TEST_DATABASE_URL must be migrated through 0060; missing: {missing}")
    return url


@pytest.fixture(scope="module")
def seeded(banner_db):
    import psycopg
    ids = {name: uuid.uuid4() for name in ("company", "merchant", "product", "voucher_product", "user", "same_event_user", "partner", "point_banner", "point_reward", "same_event_banner", "same_event_reward", "coupon", "coupon_banner", "coupon_reward")}
    tag = uuid.uuid4().hex
    with psycopg.connect(banner_db, autocommit=True) as conn:
        conn.execute("insert into companies(id,name) values (%s,%s)", (ids["company"], f"banner-pg-{tag}"))
        conn.execute("insert into merchants(id,name,qr_token,view_token) values (%s,%s,%s,%s)", (ids["merchant"], f"banner-pg-{tag}", f"qr-{tag}", f"view-{tag}"))
        conn.execute("insert into merchant_products(id,merchant_id,name,price,tax_type) values (%s,%s,'banner product',2000,'taxable')", (ids["product"], ids["merchant"]))
        conn.execute("""insert into voucher_products(id,merchant_id,name,voucher_count,bonus_count,unit_price,discount_rate,status,tax_type)
                        values (%s,%s,'banner voucher',1,0,2000,0,'active','taxable')""",
                     (ids["voucher_product"], ids["merchant"]))
        conn.execute("insert into app_users(id,company_id,display_name,role,status) values (%s,%s,%s,'employee','active')", (ids["user"], ids["company"], f"banner-pg-{tag}"))
        conn.execute("insert into app_users(id,company_id,display_name,role,status) values (%s,%s,%s,'employee','active')", (ids["same_event_user"], ids["company"], f"banner-replay-{tag}"))
        conn.execute("insert into partners(id,merchant_id,name,site_url,status,created_by) values (%s,%s,%s,'https://partner.example','active',%s)", (ids["partner"], ids["merchant"], f"partner-{tag}", ids["user"]))
        conn.execute("""insert into partner_banners(id,merchant_id,partner_id,title,image_url,image_alt,link_url,open_mode,placement,created_by)
                        values (%s,%s,%s,'daily','https://cdn.example/banner.webp','alt','https://partner.example/go','webview','home_bottom',%s)""",
                     (ids["point_banner"], ids["merchant"], ids["partner"], ids["user"]))
        conn.execute("""insert into banner_rewards(id,banner_id,merchant_id,reward_type,point_amount,grant_policy,total_budget)
                        values (%s,%s,%s,'point',100,'daily',250)""", (ids["point_reward"], ids["point_banner"], ids["merchant"]))
        conn.execute("""insert into partner_banners(id,merchant_id,partner_id,title,image_url,image_alt,link_url,open_mode,placement,created_by)
                        values (%s,%s,%s,'same event','https://cdn.example/same.webp','alt','https://partner.example/same','webview','home_bottom',%s)""",
                     (ids["same_event_banner"], ids["merchant"], ids["partner"], ids["user"]))
        conn.execute("""insert into banner_rewards(id,banner_id,merchant_id,reward_type,point_amount,grant_policy,total_budget)
                        values (%s,%s,%s,'point',25,'unlimited',1000)""",
                     (ids["same_event_reward"], ids["same_event_banner"], ids["merchant"]))
        conn.execute("""insert into merchant_coupons(id,merchant_id,name,discount_type,discount_value,is_active,created_by)
                        values (%s,%s,'issued coupon','fixed',1000,true,%s)""", (ids["coupon"], ids["merchant"], ids["user"]))
        conn.execute("""insert into partner_banners(id,merchant_id,partner_id,title,image_url,image_alt,link_url,open_mode,placement,created_by)
                        values (%s,%s,%s,'coupon','https://cdn.example/coupon.webp','alt','https://partner.example/coupon','external','event_page',%s)""",
                     (ids["coupon_banner"], ids["merchant"], ids["partner"], ids["user"]))
        conn.execute("""insert into banner_rewards(id,banner_id,merchant_id,reward_type,coupon_id,coupon_valid_days,grant_policy,total_budget)
                        values (%s,%s,%s,'coupon',%s,7,'once',1)""", (ids["coupon_reward"], ids["coupon_banner"], ids["merchant"], ids["coupon"]))
    yield ids


def _grant(url, banner_id, user_id, at, event_id=None):
    import psycopg
    event_id = event_id or uuid.uuid4()
    with psycopg.connect(url, autocommit=True) as conn:
        value = conn.execute("select grant_banner_reward(%s,%s,%s,%s)", (event_id, banner_id, user_id, at)).fetchone()[0]
    return event_id, value


def test_twenty_concurrent_daily_clicks_grant_one_transaction_and_correct_balance(banner_db, seeded):
    at = datetime(2035, 4, 10, 3, tzinfo=timezone.utc)
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: _grant(banner_db, seeded["point_banner"], seeded["user"], at)[1], range(20)))
    assert sum(result["granted"] is True for result in results) == 1
    import psycopg
    with psycopg.connect(banner_db) as conn:
        assert conn.execute("select count(*) from banner_reward_grants where reward_id=%s", (seeded["point_reward"],)).fetchone()[0] == 1
        tx = conn.execute("select amount,balance_after from point_transactions where related_banner_id=%s", (seeded["point_banner"],)).fetchall()
        assert len(tx) == 1 and tx[0][0] == 100
        balance = conn.execute("select point_balance from app_users where id=%s", (seeded["user"],)).fetchone()[0]
        assert tx[0][1] == balance == 100


def test_same_event_id_concurrent_replay_returns_exact_original_grant(banner_db, seeded):
    event_id = uuid.uuid4()
    at = datetime(2035, 4, 10, 4, tzinfo=timezone.utc)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: _grant(banner_db, seeded["same_event_banner"], seeded["same_event_user"], at, event_id)[1], range(12)))
    originals = [row for row in results if row["duplicate"] is False]
    replays = [row for row in results if row["duplicate"] is True]
    assert len(originals) == 1 and len(replays) == 11
    original = originals[0]
    for replay in replays:
        assert {k: replay[k] for k in ("granted", "reason", "grant_id", "reward_type", "units", "balance_after")} == {
            k: original[k] for k in ("granted", "reason", "grant_id", "reward_type", "units", "balance_after")
        }
    import psycopg
    with psycopg.connect(banner_db) as conn:
        assert conn.execute("select count(*) from banner_reward_grants where event_id=%s", (event_id,)).fetchone()[0] == 1


def test_next_kst_day_grants_again_then_budget_blocks(banner_db, seeded):
    _, second = _grant(banner_db, seeded["point_banner"], seeded["user"], datetime(2035, 4, 11, 3, tzinfo=timezone.utc))
    _, third = _grant(banner_db, seeded["point_banner"], seeded["user"], datetime(2035, 4, 12, 3, tzinfo=timezone.utc))
    assert second["granted"] is True and second["balance_after"] == 200
    assert third == {"granted": False, "reason": "budget_exhausted"}


def test_coupon_issue_and_same_event_replay_are_idempotent(banner_db, seeded):
    now = datetime.now(timezone.utc)
    event_id, first = _grant(banner_db, seeded["coupon_banner"], seeded["user"], now)
    _, replay = _grant(banner_db, seeded["coupon_banner"], seeded["user"], now, event_id)
    _, second = _grant(banner_db, seeded["coupon_banner"], seeded["user"], now + timedelta(hours=1))
    assert first["granted"] is True and first["user_coupon_id"]
    assert replay["granted"] is True and replay["duplicate"] is True and replay["user_coupon_id"] == first["user_coupon_id"]
    assert second == {"granted": False, "reason": "already_granted"}


def test_issued_coupon_reserve_fulfill_use_and_second_reservation_fails(banner_db, seeded):
    import psycopg
    from psycopg.types.json import Jsonb
    with psycopg.connect(banner_db) as lookup:
        exists = lookup.execute("select exists(select 1 from user_coupons where merchant_id=%s)", (seeded["merchant"],)).fetchone()[0]
    if not exists:
        _grant(banner_db, seeded["coupon_banner"], seeded["user"], datetime.now(timezone.utc))
    with psycopg.connect(banner_db, autocommit=True) as conn:
        user_coupon = conn.execute("select id,coupon_snapshot from user_coupons where merchant_id=%s order by created_at desc limit 1", (seeded["merchant"],)).fetchone()
        order = uuid.uuid4(); token = uuid.uuid4().hex
        conn.execute("""insert into payment_orders(id,order_id,checkout_token,user_id,merchant_id,product_id,voucher_product_id,merchant_name,product_name,
                     amount,pay_type,voucher_count,voucher_purchase_price,requested_point_amount,gross_amount,coupon_id,user_coupon_id,coupon_discount_amount,coupon_snapshot)
                     values (%s,%s,%s,%s,%s,null,%s,'merchant','product',1000,'voucher',1,1000,0,2000,%s,%s,1000,%s)""",
                     (order, f"banner-{order}", token, seeded["user"], seeded["merchant"], seeded["voucher_product"], seeded["coupon"], user_coupon[0], Jsonb(user_coupon[1])))
        reserved = conn.execute("select reserve_user_coupon(%s,%s,%s,%s)", (order, user_coupon[0], seeded["user"], seeded["merchant"])).fetchone()[0]
        assert reserved["reserved"] is True
        conn.execute("update payment_orders set status='done' where id=%s", (order,))
        assert conn.execute("select status,used_order_id from user_coupons where id=%s", (user_coupon[0],)).fetchone() == ("used", order)
        order2 = uuid.uuid4()
        conn.execute("""insert into payment_orders(id,order_id,checkout_token,user_id,merchant_id,product_id,voucher_product_id,merchant_name,product_name,
                     amount,pay_type,voucher_count,voucher_purchase_price,requested_point_amount,gross_amount,coupon_id,user_coupon_id,coupon_discount_amount,coupon_snapshot)
                     values (%s,%s,%s,%s,%s,null,%s,'merchant','product',1000,'voucher',1,1000,0,2000,%s,%s,1000,%s)""",
                     (order2, f"banner-{order2}", uuid.uuid4().hex, seeded["user"], seeded["merchant"], seeded["voucher_product"], seeded["coupon"], user_coupon[0], Jsonb(user_coupon[1])))
        with pytest.raises(psycopg.errors.RaiseException, match="USER_COUPON_NOT_AVAILABLE"):
            conn.execute("select reserve_user_coupon(%s,%s,%s,%s)", (order2, user_coupon[0], seeded["user"], seeded["merchant"]))


def test_service_role_permissions_and_0060_replay(banner_db):
    import psycopg
    with psycopg.connect(banner_db, autocommit=True) as conn:
        privileges = conn.execute("select has_table_privilege('service_role','partners','select'),has_function_privilege('authenticated','grant_banner_reward(uuid,uuid,uuid,timestamptz)','execute')").fetchone()
        assert privileges == (True, False)
        # Advisory locking avoids racing another non-destructive migration replay.
        conn.execute("select pg_advisory_lock(hashtext('greeneatgo-0060-replay'))")
        try:
            conn.execute(MIGRATION.read_text(encoding="utf-8"))
        finally:
            conn.execute("select pg_advisory_unlock(hashtext('greeneatgo-0060-replay'))")
        assert conn.execute("select to_regprocedure('grant_banner_reward(uuid,uuid,uuid,timestamptz)') is not null").fetchone()[0]


def test_database_live_window_filter_semantics(banner_db, seeded):
    import psycopg
    with psycopg.connect(banner_db, autocommit=True) as conn:
        conn.execute("update partner_banners set ends_at=now()-interval '1 second' where id=%s", (seeded["point_banner"],))
        count = conn.execute("""select count(*) from partner_banners where id=%s and is_active
                                and (starts_at is null or starts_at<=now()) and (ends_at is null or ends_at>now())""", (seeded["point_banner"],)).fetchone()[0]
        assert count == 0


def test_paused_partner_blocks_grant_rpc(banner_db, seeded):
    import psycopg
    with psycopg.connect(banner_db, autocommit=True) as conn:
        conn.execute("update partners set status='paused' where id=%s", (seeded["partner"],))
        try:
            with pytest.raises(psycopg.errors.RaiseException, match="BANNER_NOT_LIVE"):
                conn.execute("select grant_banner_reward(%s,%s,%s,now())", (uuid.uuid4(), seeded["coupon_banner"], seeded["user"]))
        finally:
            conn.execute("update partners set status='active' where id=%s", (seeded["partner"],))


def test_hard_delete_cascades_events_and_grants_without_deleting_ledger(banner_db, seeded):
    import psycopg
    with psycopg.connect(banner_db, autocommit=True) as conn:
        assert conn.execute("select count(*) from banner_reward_grants where banner_id=%s", (seeded["same_event_banner"],)).fetchone()[0] == 1
        conn.execute("delete from partner_banners where id=%s", (seeded["same_event_banner"],))
        assert conn.execute("select count(*) from banner_events where banner_id=%s", (seeded["same_event_banner"],)).fetchone()[0] == 0
        assert conn.execute("select count(*) from banner_reward_grants where banner_id=%s", (seeded["same_event_banner"],)).fetchone()[0] == 0
        assert conn.execute("select count(*) from point_transactions where amount=25 and user_id=%s", (seeded["same_event_user"],)).fetchone()[0] == 1
        assert conn.execute("select count(*) from point_transactions where related_banner_id=%s", (seeded["same_event_banner"],)).fetchone()[0] == 1
