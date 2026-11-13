"""Migration 0072: phone pre-emption and one-use public coupons.

Disposable PostgreSQL only (same guards as test_phone_auth_migration)::

    createdb phoneauth_test_0072
    PHONE_AUTH_TEST_ALLOW_DROP=1 \\
      TEST_DATABASE_URL=postgresql://.../phoneauth_test_0072 \\
      pytest services/api/tests/test_phone_coupon_0072_migration.py
"""

from pathlib import Path

import pytest

from tests.test_phone_auth_migration import phone_auth_db  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[3]
UP_0061 = ROOT / "infra/migrations/0061_phone_auth.sql"
UP_0072 = ROOT / "supabase/migrations/0072_phone_preemption_and_coupon_once.sql"
SQL = UP_0072.read_text(encoding="utf-8")
PROOF = "proof-0072"

PAYMENT_ORDERS = """
create table public.payment_orders (
  id uuid primary key default gen_random_uuid(),
  user_id uuid, coupon_id uuid, user_coupon_id uuid,
  status text not null default 'ready',
  provider_payment_key text, fulfilled_at timestamptz,
  point_reserved boolean not null default false,
  updated_at timestamptz
);
"""


def test_0072_contract():
    low = SQL.lower()
    assert low.count("phone_verified_at is null") == 3  # verify, signup, change
    assert "set phone_verified_at=n where id=(u->>'id')::uuid" not in low
    assert "create trigger trg_public_coupon_once before insert on public.payment_orders" in low
    assert "create extension" not in low and low.strip().startswith("begin;") and low.strip().endswith("commit;")


def _setup(conn):
    import bcrypt

    conn.execute(PAYMENT_ORDERS)
    conn.execute(UP_0061.read_text(encoding="utf-8"))
    conn.execute(SQL)
    code_hash = bcrypt.hashpw(PROOF.encode(), bcrypt.gensalt(rounds=4)).decode().replace("$2b$", "$2a$", 1)
    ip = iter(range(1, 250))

    def verified(phone, purpose, token):
        conn.execute("update public.phone_verifications set created_at=created_at-interval '10 minutes'")  # skip resend cooldown
        created = conn.execute("select public.phone_auth_begin_send(%s,%s,%s)",
                               (phone, purpose, f"192.0.2.{next(ip)}")).fetchone()[0]
        conn.execute("select public.phone_auth_set_code_hash(%s,%s)", (created["verification_id"], code_hash))
        conn.execute("select public.phone_auth_finish_send(%s,'m',true)", (created["verification_id"],))
        return conn.execute("select public.phone_auth_verify(%s,%s,%s,%s)", (phone, purpose, PROOF, token)).fetchone()[0]

    return verified


def test_unverified_holder_cannot_capture_phone_login(phone_auth_db):
    conn, _ = phone_auth_db
    verified = _setup(conn)
    attacker = conn.execute("insert into public.app_users(role,phone,display_name) values('customer','01055550000','attacker') returning id").fetchone()[0]

    # The owner proves the number: no login into the attacker account, a new signup instead.
    result = verified("01055550000", "signup_login", "a" * 64)
    assert result["status"] == "new"
    assert conn.execute("select phone from public.app_users where id=%s", (attacker,)).fetchone() == (None,)
    signup = conn.execute("select public.phone_auth_signup(%s,'owner')", ("a" * 64,)).fetchone()[0]
    assert signup["status"] == "ok" and signup["user_id"] != str(attacker)

    # A verified holder still logs in normally.
    again = verified("01055550000", "signup_login", "b" * 64)
    assert again["status"] == "existing" and again["user_id"] == signup["user_id"]


def test_signup_and_change_displace_unverified_holder(phone_auth_db):
    conn, _ = phone_auth_db
    verified = _setup(conn)
    # Token issued while the number was free; an unverified row appears before signup.
    assert verified("01066660000", "signup_login", "c" * 64)["status"] == "new"
    late = conn.execute("insert into public.app_users(role,phone) values('employee','01066660000') returning id").fetchone()[0]
    signup = conn.execute("select public.phone_auth_signup(%s,'owner')", ("c" * 64,)).fetchone()[0]
    assert signup["status"] == "ok" and signup["user_id"] != str(late)
    assert conn.execute("select phone from public.app_users where id=%s", (late,)).fetchone() == (None,)

    actor = conn.execute("insert into public.app_users(role,phone,phone_verified_at) values('customer','01011112222',now()) returning id").fetchone()[0]
    squatter = conn.execute("insert into public.app_users(role,phone) values('customer','01077770000') returning id").fetchone()[0]
    assert verified("01077770000", "change_phone", "d" * 64)["status"] == "verified"
    assert conn.execute("select public.phone_auth_change(%s,%s)", ("d" * 64, actor)).fetchone()[0] == {"status": "ok", "phone": "01077770000"}
    assert conn.execute("select phone from public.app_users where id=%s", (squatter,)).fetchone() == (None,)

    # A verified holder is never displaced.
    owner = conn.execute("insert into public.app_users(role,phone,phone_verified_at) values('customer','01088880000',now()) returning id").fetchone()[0]
    assert verified("01088880000", "change_phone", "e" * 64)["status"] == "verified"
    assert conn.execute("select public.phone_auth_change(%s,%s)", ("e" * 64, actor)).fetchone()[0] == {"status": "conflict"}
    assert conn.execute("select phone from public.app_users where id=%s", (owner,)).fetchone() == ("01088880000",)


def test_public_coupon_is_one_use_per_person(phone_auth_db):
    psycopg = pytest.importorskip("psycopg")
    conn, _ = phone_auth_db
    _setup(conn)
    user, other = (conn.execute("select gen_random_uuid()").fetchone()[0] for _ in range(2))
    coupon = conn.execute("select gen_random_uuid()").fetchone()[0]

    def order(u=user, c=coupon, issued=None, **kw):
        cols = {"user_id": u, "coupon_id": c, "user_coupon_id": issued, **kw}
        names = ",".join(cols)
        marks = ",".join(["%s"] * len(cols))
        return conn.execute(f"insert into public.payment_orders({names}) values({marks}) returning id", tuple(cols.values())).fetchone()[0]

    first = order()
    second = order()  # replaces the unpaid first checkout
    assert conn.execute("select status from public.payment_orders where id=%s", (first,)).fetchone() == ("canceled",)
    conn.execute("update public.payment_orders set status='done',provider_payment_key='pk',fulfilled_at=now() where id=%s", (second,))
    with pytest.raises(psycopg.errors.RaiseException, match="COUPON_ALREADY_USED"):
        order()
    order(u=other)  # another person may still use it
    order(issued=conn.execute("select gen_random_uuid()").fetchone()[0])  # issued coupons keep their own rule

    reserved_user = conn.execute("select gen_random_uuid()").fetchone()[0]
    order(u=reserved_user, point_reserved=True)
    with pytest.raises(psycopg.errors.RaiseException, match="COUPON_IN_PROGRESS"):
        order(u=reserved_user)


def test_withdrawn_account_number_can_sign_up_again_0076(phone_auth_db):
    conn, _ = phone_auth_db
    verified = _setup(conn)
    conn.execute((ROOT / "supabase/migrations/0076_account_deletion_resignup.sql").read_text(encoding="utf-8"))
    assert verified("01099990000", "signup_login", "f" * 64)["status"] == "new"
    first = conn.execute("select public.phone_auth_signup(%s,'first')", ("f" * 64,)).fetchone()[0]
    conn.execute("update public.app_users set phone=null,phone_verified_at=null,display_name='탈퇴회원',status='left' where id=%s", (first["user_id"],))
    assert verified("01099990000", "signup_login", "g" * 64)["status"] == "new"
    again = conn.execute("select public.phone_auth_signup(%s,'again')", ("g" * 64,)).fetchone()[0]
    assert again["status"] == "ok" and again["user_id"] != first["user_id"]
    assert conn.execute("select status from public.app_users where id=%s", (first["user_id"],)).fetchone() == ("left",)
