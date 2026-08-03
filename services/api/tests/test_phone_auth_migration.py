"""Contract and disposable-PostgreSQL tests for migration 0061.

The integration fixture is deliberately destructive only with both guards set::

    createdb phoneauth_test_0061
    PHONE_AUTH_TEST_ALLOW_DROP=1 \
      TEST_DATABASE_URL=postgresql://.../phoneauth_test_0061 \
      pytest services/api/tests/test_phone_auth_migration.py

Never point this test at a shared or production database.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest


ROOT = Path(__file__).resolve().parents[3]
UP_PATH = ROOT / "infra/migrations/0061_phone_auth.sql"
DOWN_PATH = ROOT / "infra/rollbacks/0061_phone_auth_down.sql"
UP = UP_PATH.read_text(encoding="utf-8").lower()
DOWN = DOWN_PATH.read_text(encoding="utf-8").lower()


def _compact(sql: str) -> str:
    return " ".join(sql.split())


def test_phone_auth_migration_contract():
    sql = _compact(UP)

    preflight = sql.index("do $$")
    normalization = sql.index("update public.app_users set phone = nullif")
    assert preflight < normalization
    assert "non-null normalized phone value(s)" in sql
    assert "duplicate login-role phone after normalization" in sql
    assert "nullif(regexp_replace(phone, '[^0-9]', '', 'g'), '')" in sql
    assert "add column phone_verified_at timestamptz" in sql
    assert "add column if not exists phone_verified_at" not in sql
    assert "constraint app_users_phone_login_format_check" in sql
    assert "phone is null or phone ~ '^010[0-9]{8}$'" in sql
    assert "create unique index uq_app_users_phone_login" in sql
    assert "create unique index if not exists uq_app_users_phone_login" not in sql
    assert "on public.app_users(phone)" in sql
    assert "phone is not null and role in ('customer', 'employee')" in sql

    assert "drop index public.uq_app_users_company_phone;" in sql
    assert sql.index("drop index public.uq_app_users_company_phone;") < normalization

    # Existing app-user columns and constraints remain owned by earlier migrations.
    forbidden_up_statements = (
        "drop index if exists public.uq_app_users_company_phone;",
        "drop constraint app_users_phone_format_check;",
        "drop constraint if exists app_users_phone_format_check;",
        "drop column phone;",
        "drop column if exists phone;",
    )
    for statement in forbidden_up_statements:
        assert statement not in sql

    assert "create function public.clear_phone_verification_on_phone_change_0061()" in sql
    assert "new.phone is distinct from old.phone" in sql
    assert "new.phone_verified_at is not distinct from old.phone_verified_at" in sql
    assert "create trigger app_users_clear_phone_verification_on_phone_change_0061" in sql

    assert "create table public.phone_verifications" in sql
    for column in (
        "id uuid primary key",
        "phone text not null",
        "code_hash text not null",
        "purpose text not null",
        "attempts integer not null default 0",
        "max_attempts integer not null default 5",
        "expires_at timestamptz not null",
        "verified_at timestamptz",
        "consumed_at timestamptz",
        "request_ip inet",
        "provider_msg_id text",
        "created_at timestamptz not null default now()",
    ):
        assert column in sql
    assert "purpose in ('signup_login', 'change_phone')" in sql
    assert "create index idx_phone_verifications_lookup" in sql
    assert "create index idx_phone_verifications_created_at" in sql
    assert "create index idx_phone_verifications_ip_created_at" in sql

    assert "create table public.phone_verification_tokens" in sql
    assert "token text primary key" in sql
    assert "verification_id uuid not null" in sql
    assert "foreign key (verification_id, purpose)" in sql
    assert "references public.phone_verifications(id, purpose) on delete cascade" in sql
    assert "one-way hash of the verification bearer token; never plaintext" in sql
    assert "create index idx_phone_verification_tokens_phone" in sql
    assert "create index idx_phone_verification_tokens_created_at" in sql
    assert "phone_auth_begin_send(p_phone text,p_purpose text,p_request_ip inet)" in sql
    assert "phone_auth_set_code_hash(p_verification_id uuid,p_code_hash text)" in sql
    assert "'$pending$'" in sql
    assert "p_code_secret" not in sql
    assert "p_code_proof" in sql
    assert "extensions.crypt(p_code_proof,v.code_hash)" in sql
    assert "extensions.digest(" in sql
    assert "create extension" not in sql and "drop extension" not in sql
    assert sql.count("enable row level security") == 2
    assert "from public, anon, authenticated, service_role" in sql
    assert "grant select, insert, update on table" in sql
    assert "to service_role" in sql
    assert "grant delete" not in sql
    assert "create policy" not in sql
    assert "notify pgrst, 'reload schema'" in sql


def test_phone_auth_down_migration_removes_only_0061_objects():
    sql = _compact(DOWN)

    assert "drop table public.phone_verification_tokens" in sql
    assert "drop table public.phone_verifications" in sql
    assert "drop trigger app_users_clear_phone_verification_on_phone_change_0061" in sql
    assert "drop function public.clear_phone_verification_on_phone_change_0061()" in sql
    assert "drop index public.uq_app_users_phone_login" in sql
    assert "drop constraint app_users_phone_login_format_check" in sql
    assert "drop column phone_verified_at" in sql
    forbidden_down_statements = (
        "drop constraint app_users_phone_format_check;",
        "drop constraint if exists app_users_phone_format_check;",
        "drop index if exists public.uq_app_users_company_phone;",
        "drop column phone;",
        "drop column if exists phone;",
    )
    for statement in forbidden_down_statements:
        assert statement not in sql
    assert "create unique index uq_app_users_company_phone on public.app_users(company_id, phone)" in sql
    assert "0061 rollback preflight failed: duplicate company phone" in sql
    assert "notify pgrst, 'reload schema'" in sql


@pytest.fixture
def phone_auth_db():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to a disposable phoneauth_test_* database")
    if os.getenv("PHONE_AUTH_TEST_ALLOW_DROP") != "1":
        pytest.fail(
            "refusing destructive setup: set PHONE_AUTH_TEST_ALLOW_DROP=1 in addition "
            "to TEST_DATABASE_URL"
        )

    psycopg = pytest.importorskip("psycopg")
    conn = psycopg.connect(url, autocommit=True)
    database_name = conn.execute("select current_database()").fetchone()[0]
    if not database_name.startswith("phoneauth_test_"):
        conn.close()
        pytest.fail(
            "refusing destructive setup: database name must start with phoneauth_test_"
        )

    def reset_schema():
        conn.execute("drop extension if exists pgcrypto cascade")
        conn.execute("drop schema if exists public cascade; drop schema if exists extensions cascade")
        conn.execute("create schema public; create schema extensions")
        conn.execute("create extension pgcrypto schema extensions")
        conn.execute(
            """
            do $$ begin
              if not exists(select 1 from pg_roles where rolname='anon') then
                create role anon nologin;
              end if;
              if not exists(select 1 from pg_roles where rolname='authenticated') then
                create role authenticated nologin;
              end if;
              if not exists(select 1 from pg_roles where rolname='service_role') then
                create role service_role nologin bypassrls;
              end if;
            end $$;
            create table public.app_users (
              id uuid primary key default gen_random_uuid(),
              role text not null check (role in (
                'customer','employee','company_admin','merchant_admin','platform_admin'
              )),
              company_id uuid,
              phone text,
              display_name text not null default 'Test User',
              status text not null default 'active',
              constraint app_users_phone_format_check
                check (phone is null or phone ~ '^010[0-9]{8}$')
            );
            create unique index uq_app_users_company_phone
              on public.app_users(company_id, phone)
              where company_id is not null and phone is not null;
            """
        )

    reset_schema()
    try:
        yield conn, reset_schema
    finally:
        # The same two guards remain true for cleanup; leave no test objects behind.
        conn.execute("rollback")
        conn.execute("drop extension if exists pgcrypto cascade")
        conn.execute("drop schema if exists public cascade; drop schema if exists extensions cascade; create schema public")
        conn.close()


def _drop_0017_constraint_for_legacy_seed(conn):
    conn.execute(
        "alter table public.app_users drop constraint app_users_phone_format_check"
    )


def _restore_0017_constraint_not_valid(conn):
    conn.execute(
        """alter table public.app_users add constraint app_users_phone_format_check
             check (phone is null or phone ~ '^010[0-9]{8}$') not valid"""
    )


def test_phone_normalization_preflights_fail_closed(phone_auth_db):
    import psycopg

    conn, reset_schema = phone_auth_db
    _drop_0017_constraint_for_legacy_seed(conn)
    conn.execute(
        "insert into public.app_users(role, phone) values ('customer', '010-12A4-5678')"
    )
    _restore_0017_constraint_not_valid(conn)
    with pytest.raises(psycopg.errors.RaiseException, match="non-null normalized phone"):
        conn.execute(UP_PATH.read_text(encoding="utf-8"))
    conn.execute("rollback")
    assert conn.execute("select phone from public.app_users").fetchone() == (
        "010-12A4-5678",
    )
    assert conn.execute(
        "select count(*) from information_schema.columns where table_schema='public' "
        "and table_name='app_users' and column_name='phone_verified_at'"
    ).fetchone() == (0,)

    # Nonblank legacy junk must not silently become NULL merely because digit
    # stripping produces an empty string.
    reset_schema()
    _drop_0017_constraint_for_legacy_seed(conn)
    conn.execute(
        "insert into public.app_users(role, phone) values ('merchant_admin', 'letters!?')"
    )
    _restore_0017_constraint_not_valid(conn)
    with pytest.raises(psycopg.errors.RaiseException, match="non-null normalized phone"):
        conn.execute(UP_PATH.read_text(encoding="utf-8"))
    conn.execute("rollback")
    assert conn.execute("select phone from public.app_users").fetchone() == ("letters!?",)

    reset_schema()
    _drop_0017_constraint_for_legacy_seed(conn)
    conn.execute(
        """
        insert into public.app_users(role, phone) values
          ('customer', '010-1234-5678'),
          ('employee', '010 1234 5678')
        """
    )
    _restore_0017_constraint_not_valid(conn)
    with pytest.raises(psycopg.errors.RaiseException, match="duplicate login-role phone"):
        conn.execute(UP_PATH.read_text(encoding="utf-8"))
    conn.execute("rollback")
    assert conn.execute(
        "select array_agg(phone order by phone) from public.app_users"
    ).fetchone() == (["010 1234 5678", "010-1234-5678"],)


def test_phone_auth_up_down_up_database_behavior(phone_auth_db):
    import psycopg

    conn, _ = phone_auth_db
    _drop_0017_constraint_for_legacy_seed(conn)
    conn.execute(
        """
        insert into public.app_users(role, phone) values
          ('customer', '010-1234-5678'),
          ('merchant_admin', '')
        """
    )
    _restore_0017_constraint_not_valid(conn)
    conn.execute(UP_PATH.read_text(encoding="utf-8"))
    assert conn.execute(
        "select array_agg(phone order by role) from public.app_users"
    ).fetchone() == (["01012345678", None],)
    assert conn.execute(
        "select n.nspname from pg_extension e join pg_namespace n on n.oid=e.extnamespace "
        "where e.extname='pgcrypto'"
    ).fetchone() == ("extensions",)

    company_id = "11111111-1111-1111-1111-111111111111"
    conn.execute(
        "insert into public.app_users(role,company_id,phone) values "
        "('merchant_admin',%s,'01066667777'),('customer',%s,'01066667777')",
        (company_id, company_id),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "insert into public.app_users(role,company_id,phone) values "
            "('employee',%s,'01066667777')", (company_id,)
        )

    conn.execute(
        "insert into public.app_users(role, phone) values ('merchant_admin', '01012345678')"
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "insert into public.app_users(role, phone) values ('employee', '01012345678')"
        )

    user_id = conn.execute(
        """insert into public.app_users(role, phone, phone_verified_at)
           values ('customer', '01022223333', '2026-01-01 00:00:00+00') returning id"""
    ).fetchone()[0]
    conn.execute(
        "update public.app_users set phone='01033334444' where id=%s", (user_id,)
    )
    assert conn.execute(
        "select phone_verified_at from public.app_users where id=%s", (user_id,)
    ).fetchone() == (None,)
    conn.execute(
        """update public.app_users
           set phone='01044445555', phone_verified_at='2026-02-02 00:00:00+00'
           where id=%s""",
        (user_id,),
    )
    assert str(
        conn.execute(
            "select phone_verified_at from public.app_users where id=%s", (user_id,)
        ).fetchone()[0]
    ) == "2026-02-02 00:00:00+00:00"

    tables = ("phone_verifications", "phone_verification_tokens")
    for table in tables:
        assert conn.execute(
            "select relrowsecurity from pg_class where oid=%s::regclass",
            (f"public.{table}",),
        ).fetchone() == (True,)
        assert conn.execute(
            "select count(*) from pg_policy where polrelid=%s::regclass",
            (f"public.{table}",),
        ).fetchone() == (0,)
        for role in ("anon", "authenticated"):
            for privilege in ("select", "insert", "update", "delete"):
                assert conn.execute(
                    "select has_table_privilege(%s, %s, %s)",
                    (role, f"public.{table}", privilege),
                ).fetchone() == (False,)
        for privilege in ("select", "insert", "update"):
            assert conn.execute(
                "select has_table_privilege('service_role', %s, %s)",
                (f"public.{table}", privilege),
            ).fetchone() == (True,)
        assert conn.execute(
            "select has_table_privilege('service_role', %s, 'delete')",
            (f"public.{table}",),
        ).fetchone() == (False,)
        # PUBLIC is pseudo-role OID 0 in ACLs (not a pg_roles row).
        assert conn.execute(
            """select not exists (
                 select 1 from pg_class c, lateral aclexplode(c.relacl) acl
                 where c.oid=%s::regclass and acl.grantee=0
                   and acl.privilege_type in ('SELECT','INSERT','UPDATE','DELETE')
               )""",
            (f"public.{table}",),
        ).fetchone() == (True,)

    verification_id = conn.execute(
        """insert into public.phone_verifications(phone, code_hash, purpose, expires_at)
           values ('01055556666', 'code-hash', 'change_phone', now()+interval '5 min')
           returning id"""
    ).fetchone()[0]
    conn.execute(
        """insert into public.phone_verification_tokens
             (token, verification_id, purpose, phone, expires_at)
           values ('token-hash-only', %s, 'change_phone', '01055556666', now()+interval '5 min')""",
        (verification_id,),
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            """insert into public.phone_verification_tokens
                 (token, verification_id, purpose, phone, expires_at)
               values ('mismatched-hash', %s, 'signup_login', '01055556666', now()+interval '5 min')""",
            (verification_id,),
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            """insert into public.phone_verification_tokens
                 (token, verification_id, purpose, phone, expires_at)
               values ('bad-purpose-hash', %s, 'password_reset', '01055556666', now()+interval '5 min')""",
            (verification_id,),
        )
    conn.execute("delete from public.phone_verifications where id=%s", (verification_id,))
    assert conn.execute(
        "select count(*) from public.phone_verification_tokens where token='token-hash-only'"
    ).fetchone() == (0,)

    # A second apply fails fast and cannot silently adopt/reconfigure 0061 objects.
    with pytest.raises(psycopg.errors.UndefinedObject):
        conn.execute(UP_PATH.read_text(encoding="utf-8"))
    conn.execute("rollback")

    # 0061 can contain data forbidden by 0017. Rollback must fail atomically
    # rather than silently omit or weaken the original company-phone index.
    with pytest.raises(psycopg.errors.RaiseException, match="duplicate company phone"):
        conn.execute(DOWN_PATH.read_text(encoding="utf-8"))
    conn.execute("rollback")
    assert conn.execute(
        "select to_regclass('public.phone_verifications') is not null"
    ).fetchone() == (True,)
    conn.execute(
        "delete from public.app_users where company_id=%s and role='merchant_admin'",
        (company_id,),
    )

    conn.execute(DOWN_PATH.read_text(encoding="utf-8"))
    assert conn.execute(
        "select to_regclass('public.phone_verifications'), "
        "to_regclass('public.phone_verification_tokens'), "
        "to_regclass('public.uq_app_users_phone_login')"
    ).fetchone() == (None, None, None)
    assert conn.execute(
        """select exists (
             select 1 from pg_constraint
             where conrelid='public.app_users'::regclass
               and conname='app_users_phone_format_check'
           ), to_regclass('public.uq_app_users_company_phone') is not null"""
    ).fetchone() == (True, True)
    assert conn.execute(
        "select to_regprocedure('public.clear_phone_verification_on_phone_change_0061()')"
    ).fetchone() == (None,)

    # Down removes only owned objects, so a clean re-apply succeeds.
    conn.execute(UP_PATH.read_text(encoding="utf-8"))
    assert conn.execute(
        "select to_regclass('public.phone_verifications') is not null"
    ).fetchone() == (True,)


def test_atomic_phone_auth_rpcs_attempts_limits_cleanup_and_signup(phone_auth_db):
    import bcrypt
    from uuid import UUID, uuid5

    conn, _ = phone_auth_db
    conn.execute(UP_PATH.read_text(encoding="utf-8"))
    code_proof = "valid-context-bound-proof"
    code_hash = bcrypt.hashpw(code_proof.encode(), bcrypt.gensalt(rounds=4)).decode().replace("$2b$", "$2a$", 1)

    def begin(phone="01070000000", ip="203.0.113.1"):
        result = conn.execute(
            "select public.phone_auth_begin_send(%s,'signup_login',%s)",
            (phone, ip),
        ).fetchone()[0]
        if result["status"] == "created":
            assert conn.execute(
                "select public.phone_auth_set_code_hash(%s,%s)",
                (result["verification_id"], code_hash),
            ).fetchone() == (True,)
        return result

    created = begin()
    assert created["status"] == "created"
    assert conn.execute(
        "select public.phone_auth_set_code_hash(%s,%s)",
        (created["verification_id"], code_hash),
    ).fetchone() == (False,)
    assert begin()["status"] == "cooldown"
    conn.execute("select public.phone_auth_finish_send(%s,'provider-message',true)", (created["verification_id"],))
    for attempt in range(1, 5):
        result = conn.execute(
            "select public.phone_auth_verify(%s,'signup_login',%s,%s)",
            ("01070000000", "wrong-context-proof", f"wrong-{attempt}"),
        ).fetchone()[0]
        assert result == {"status": "invalid_code", "attempts": attempt}
    result = conn.execute(
        "select public.phone_auth_verify(%s,'signup_login',%s,%s)",
        ("01070000000", "wrong-context-proof", "wrong-5"),
    ).fetchone()[0]
    assert result["status"] == "too_many_attempts"
    assert conn.execute(
        "select public.phone_auth_verify(%s,'signup_login',%s,%s)",
        ("01070000000", code_proof, "replay"),
    ).fetchone()[0]["status"] == "expired"

    created = begin("01070000001", "203.0.113.2")
    conn.execute("select public.phone_auth_finish_send(%s,'provider-2',true)", (created["verification_id"],))
    token_hash = "a" * 64
    assert conn.execute(
        "select public.phone_auth_verify(%s,'signup_login',%s,%s)",
        ("01070000001", code_proof, token_hash),
    ).fetchone()[0]["status"] == "new"
    signed = conn.execute("select public.phone_auth_signup(%s,%s)", (token_hash, "홍길동")).fetchone()[0]
    expected = uuid5(UUID("ad2bd92b-c52f-4b30-bb59-4f789edbcdb0"), "phone_01070000001")
    assert signed["status"] == "ok" and UUID(signed["user_id"]) == expected
    assert conn.execute("select public.phone_auth_signup(%s,%s)", (token_hash, "홍길동")).fetchone()[0]["status"] == "invalid_token"

    conn.execute("delete from public.phone_verification_tokens; delete from public.phone_verifications")
    for minutes in range(2, 7):
        conn.execute(
            "insert into public.phone_verifications(phone,purpose,code_hash,expires_at,created_at) values('01070000002','signup_login',%s,now(),now()-(%s||' minutes')::interval)",
            (code_hash, minutes),
        )
    assert begin("01070000002")["status"] == "phone_hour_limit"

    conn.execute("delete from public.phone_verifications")
    for hours in range(2, 12):
        conn.execute(
            "insert into public.phone_verifications(phone,purpose,code_hash,expires_at,created_at) values('01070000003','signup_login',%s,now(),now()-(%s||' hours')::interval)",
            (code_hash, hours),
        )
    assert begin("01070000003")["status"] == "phone_day_limit"

    conn.execute("delete from public.phone_verifications")
    for i in range(20):
        conn.execute(
            "insert into public.phone_verifications(phone,purpose,request_ip,code_hash,expires_at,created_at) values(%s,'signup_login','198.51.100.9',%s,now(),now()-interval '2 minutes')",
            (f"0108{i:07d}", code_hash),
        )
    assert begin("01079999999", "198.51.100.9")["status"] == "ip_hour_limit"

    old_id = conn.execute(
        "insert into public.phone_verifications(phone,purpose,code_hash,expires_at,created_at) values('01071112222','signup_login',%s,now(),now()-interval '8 days') returning id",
        (code_hash,),
    ).fetchone()[0]
    begin("01073334444", "192.0.2.2")
    assert conn.execute("select count(*) from public.phone_verifications where id=%s", (old_id,)).fetchone() == (0,)

    for role in ("anon", "authenticated"):
        assert conn.execute(
            "select has_function_privilege(%s,'public.phone_auth_begin_send(text,text,inet)','execute')",
            (role,),
        ).fetchone() == (False,)
    assert conn.execute(
        "select has_function_privilege('service_role','public.phone_auth_begin_send(text,text,inet)','execute')"
    ).fetchone() == (True,)
    for role in ("anon", "authenticated"):
        assert conn.execute(
            "select has_function_privilege(%s,'public.phone_auth_set_code_hash(uuid,text)','execute')",
            (role,),
        ).fetchone() == (False,)
    assert conn.execute(
        "select has_function_privilege('service_role','public.phone_auth_set_code_hash(uuid,text)','execute')"
    ).fetchone() == (True,)
    assert conn.execute(
        "select has_function_privilege('service_role','public.phone_auth_uuid5_0061(text)','execute')"
    ).fetchone() == (False,)


def test_concurrent_ip_limit_code_exchange_and_signup_are_atomic(phone_auth_db):
    """Independent sessions prove transaction locks, not single-session behavior."""
    import bcrypt
    import psycopg

    conn, _ = phone_auth_db
    conn.execute(UP_PATH.read_text(encoding="utf-8"))
    url = os.environ["TEST_DATABASE_URL"]
    code_proof = "concurrent-context-bound-proof"
    code_hash = bcrypt.hashpw(code_proof.encode(), bcrypt.gensalt(rounds=4)).decode().replace("$2b$", "$2a$", 1)
    barrier = Barrier(30)

    def concurrent_begin(i):
        with psycopg.connect(url, autocommit=True) as worker:
            barrier.wait()
            return worker.execute(
                "select public.phone_auth_begin_send(%s,'signup_login','198.51.100.77')",
                (f"0109{i:07d}",),
            ).fetchone()[0]

    with ThreadPoolExecutor(max_workers=30) as pool:
        begin_results = list(pool.map(concurrent_begin, range(30)))
    assert sum(result["status"] == "created" for result in begin_results) == 20
    assert conn.execute("select count(*) from public.phone_verifications where request_ip='198.51.100.77'").fetchone() == (20,)

    created = conn.execute("select public.phone_auth_begin_send('01061234567','signup_login','192.0.2.50')").fetchone()[0]
    assert conn.execute("select public.phone_auth_set_code_hash(%s,%s)", (created["verification_id"], code_hash)).fetchone() == (True,)
    conn.execute("select public.phone_auth_finish_send(%s,'delivered',true)", (created["verification_id"],))
    verify_barrier = Barrier(12)

    def concurrent_verify(i):
        token_hash = f"{i:064x}"
        with psycopg.connect(url, autocommit=True) as worker:
            verify_barrier.wait()
            result = worker.execute("select public.phone_auth_verify('01061234567','signup_login',%s,%s)", (code_proof, token_hash)).fetchone()[0]
        return token_hash, result

    with ThreadPoolExecutor(max_workers=12) as pool:
        verify_results = list(pool.map(concurrent_verify, range(1, 13)))
    winners = [token for token, result in verify_results if result["status"] == "new"]
    assert len(winners) == 1
    assert sum(result["status"] == "expired" for _, result in verify_results) == 11
    signup_barrier = Barrier(2)

    def concurrent_signup(_):
        with psycopg.connect(url, autocommit=True) as worker:
            signup_barrier.wait()
            return worker.execute("select public.phone_auth_signup(%s,'Concurrent User')", (winners[0],)).fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        signup_results = list(pool.map(concurrent_signup, range(2)))
    assert sorted(result["status"] for result in signup_results) == ["invalid_token", "ok"]
    assert conn.execute("select count(*) from public.app_users where phone='01061234567' and role in ('customer','employee')").fetchone() == (1,)


def test_change_phone_token_conflict_retry_roles_and_login_scope(phone_auth_db):
    import bcrypt

    conn, _ = phone_auth_db
    conn.execute(UP_PATH.read_text(encoding="utf-8"))
    code_proof = "change-context-bound-proof"
    code_hash = bcrypt.hashpw(code_proof.encode(), bcrypt.gensalt(rounds=4)).decode().replace("$2b$", "$2a$", 1)

    def reserve(phone, purpose, ip):
        created = conn.execute(
            "select public.phone_auth_begin_send(%s,%s,%s)", (phone, purpose, ip)
        ).fetchone()[0]
        assert conn.execute(
            "select public.phone_auth_set_code_hash(%s,%s)",
            (created["verification_id"], code_hash),
        ).fetchone() == (True,)
        return created
    actor = conn.execute("insert into public.app_users(role,phone) values('customer','01011110000') returning id").fetchone()[0]
    holder = conn.execute("insert into public.app_users(role,phone) values('employee','01022220000') returning id").fetchone()[0]
    merchant = conn.execute("insert into public.app_users(role,phone) values('merchant_admin','01022220000') returning id").fetchone()[0]
    created = reserve("01022220000", "change_phone", "192.0.2.60")
    conn.execute("select public.phone_auth_finish_send(%s,'delivered',true)", (created["verification_id"],))
    verified = conn.execute("select public.phone_auth_verify('01022220000','change_phone',%s,%s)", (code_proof, "c" * 64)).fetchone()[0]
    assert verified == {"status": "verified", "expires_in": 300}
    assert conn.execute("select public.phone_auth_change(%s,%s)", ("c" * 64, actor)).fetchone()[0] == {"status": "conflict"}
    assert conn.execute("select consumed_at is null from public.phone_verification_tokens where token=%s", ("c" * 64,)).fetchone() == (True,)
    assert conn.execute("select public.phone_auth_change(%s,%s)", ("c" * 64, merchant)).fetchone()[0] == {"status": "forbidden"}
    conn.execute("update public.app_users set phone='01033330000' where id=%s", (holder,))
    assert conn.execute("select public.phone_auth_change(%s,%s)", ("c" * 64, actor)).fetchone()[0] == {"status": "ok", "phone": "01022220000"}
    assert conn.execute("select public.phone_auth_change(%s,%s)", ("c" * 64, actor)).fetchone()[0] == {"status": "invalid_token"}

    # An admin-only phone is treated as a new customer login identity.
    conn.execute("insert into public.app_users(role,phone) values('platform_admin','01044441111')")
    created = reserve("01044441111", "signup_login", "192.0.2.62")
    conn.execute("select public.phone_auth_finish_send(%s,'delivered-admin',true)", (created["verification_id"],))
    ignored_admin = conn.execute("select public.phone_auth_verify('01044441111','signup_login',%s,%s)", (code_proof, "b" * 64)).fetchone()[0]
    assert ignored_admin["status"] == "new"

    # A customer sharing a merchant phone is the only login account returned.
    conn.execute("update public.app_users set phone='01044440000' where id=%s", (merchant,))
    customer = conn.execute("insert into public.app_users(role,phone,display_name) values('customer','01044440000','Customer') returning id").fetchone()[0]
    created = reserve("01044440000", "signup_login", "192.0.2.61")
    conn.execute("select public.phone_auth_finish_send(%s,'delivered',true)", (created["verification_id"],))
    login = conn.execute("select public.phone_auth_verify('01044440000','signup_login',%s,%s)", (code_proof, "d" * 64)).fetchone()[0]
    assert login["status"] == "existing" and login["user_id"] == str(customer)


def test_signup_recovers_existing_id_rejects_status_and_fails_safe_on_id_collision(phone_auth_db):
    from uuid import UUID, uuid5

    conn, _ = phone_auth_db
    conn.execute(UP_PATH.read_text(encoding="utf-8"))

    def token(phone, value):
        verification_id = conn.execute("insert into public.phone_verifications(phone,purpose,code_hash,expires_at,verified_at,consumed_at) values(%s,'signup_login','x',now()+interval '5 min',now(),now()) returning id", (phone,)).fetchone()[0]
        conn.execute("insert into public.phone_verification_tokens(token,verification_id,purpose,phone,expires_at) values(%s,%s,'signup_login',%s,now()+interval '5 min')", (value, verification_id, phone))

    imported = conn.execute("insert into public.app_users(role,phone,status) values('customer','01055550000','paused') returning id").fetchone()[0]
    token("01055550000", "e" * 64)
    recovered = conn.execute("select public.phone_auth_signup(%s,'Ignored')", ("e" * 64,)).fetchone()[0]
    assert recovered["status"] == "ok" and recovered["user_id"] == str(imported)
    conn.execute("insert into public.app_users(role,phone,status) values('customer','01055550001','left')")
    token("01055550001", "f" * 64)
    assert conn.execute("select public.phone_auth_signup(%s,'Nope')", ("f" * 64,)).fetchone()[0] == {"status": "unavailable"}

    target = "01055550002"
    deterministic = uuid5(UUID("ad2bd92b-c52f-4b30-bb59-4f789edbcdb0"), f"phone_{target}")
    conn.execute("insert into public.app_users(id,role,phone) values(%s,'merchant_admin','01055559999')", (deterministic,))
    token(target, "a" * 64)
    assert conn.execute("select public.phone_auth_signup(%s,'Safe')", ("a" * 64,)).fetchone()[0] == {"status": "id_conflict"}
    assert conn.execute("select count(*) from public.app_users where phone=%s", (target,)).fetchone() == (0,)
