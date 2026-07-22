import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = REPO_ROOT / "infra/migrations/0031_decouple_app_users_from_supabase_auth.sql"


def _sql(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").lower()).strip()


def test_decoupling_covers_only_both_historical_auth_user_foreign_keys():
    initial = _sql(REPO_ROOT / "infra/migrations/0001_initial.sql")
    bulk_invites = _sql(REPO_ROOT / "infra/migrations/0017_employee_bulk_invites.sql")
    migration = _sql(MIGRATION)
    body = migration.split("do $$", maxsplit=1)[1]

    assert re.search(
        r"create table if not exists app_users \([^;]*id uuid primary key references auth\.users\s*\(id\)",
        initial,
    )
    assert re.search(
        r"create table if not exists employee_bulk_invites \([^;]*claimed_by uuid references auth\.users\s*\(id\)",
        bulk_invites,
    )

    # Exact relation/column discovery prevents broad-dropping future auth FKs,
    # while dynamic conname use remains independent of constraint names.
    assert "join pg_class source_table on source_table.oid = con.conrelid" in body
    assert "join pg_namespace source_ns on source_ns.oid = source_table.relnamespace" in body
    assert "join pg_attribute source_column" in body
    assert "source_ns.nspname = 'public'" in body
    assert "source_table.relname = 'app_users'" in body
    assert "source_column.attname = 'id'" in body
    assert "source_table.relname = 'employee_bulk_invites'" in body
    assert "source_column.attname = 'claimed_by'" in body
    assert "alter table %i.%i drop constraint %i" in body
    assert "auth_fk.conname" in body


def test_decoupling_is_idempotent_name_independent_and_preserves_other_fks():
    migration = _sql(MIGRATION)

    assert "con.contype = 'f'" in migration
    assert "con.confrelid = to_regclass('auth.users')" in migration
    assert "auth_fk.conname" in migration
    assert migration.count("drop constraint") == 1
    assert "drop constraint %i" in migration
    assert "app_users_id_fkey" not in migration
    assert "employee_bulk_invites_claimed_by_fkey" not in migration
    assert " cascade" not in migration


def test_claimed_by_gets_idempotent_provider_neutral_app_users_fk():
    migration = _sql(MIGRATION)

    assert "references public.app_users(id)" in migration
    assert "con.confrelid = to_regclass('public.app_users')" in migration
    assert "source_column.attname = 'claimed_by'" in migration
    assert "referenced_column.attname = 'id'" in migration
    assert "if not exists" in migration
