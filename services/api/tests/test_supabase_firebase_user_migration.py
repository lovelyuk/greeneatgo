from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.firebase_auth import INTERNAL_ID_CLAIM
from scripts import migrate_supabase_users_to_firebase as migration

UID1 = "123e4567-e89b-12d3-a456-426614174000"
UID2 = "123e4567-e89b-12d3-a456-426614174001"
HASH = "$2b$12$" + "A" * 53
SECRET_EMAIL = "private.person@example.test"


def source(uid: str = UID1, email: str = SECRET_EMAIL, **changes: Any):
    values: dict[str, Any] = dict(
        uid=uid,
        email=email,
        password_hash=HASH,
        email_confirmed=True,
        app_user_id=uid,
        display_name="Private Name",
    )
    values.update(changes)
    return migration.SourceUser(**values)


@dataclass
class Result:
    success_count: int
    failure_count: int = 0
    errors: tuple[Any, ...] = ()


class FakeGateway:
    def __init__(self, existing=(), result=None):
        self.existing = list(existing)
        self.result = result
        self.import_calls: list[list[Any]] = []
        self.update_calls: list[tuple[Any, dict[str, Any]]] = []

    def list_users(self):
        return iter(self.existing)

    def import_users(self, records):
        self.import_calls.append(list(records))
        return self.result or Result(success_count=len(records))

    def update_existing(self, user, claims):
        self.update_calls.append((user, claims))


@pytest.fixture(autouse=True)
def database_url(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://not-logged")
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_dry_run_preflights_without_writes_and_has_no_pii():
    gateway = FakeGateway()
    output: list[str] = []

    result = migration.run(
        apply=False,
        batch_size=500,
        source_loader=lambda _: [source()],
        gateway_factory=lambda: gateway,  # type: ignore[arg-type]
        out=output.append,
    )

    assert result == 0
    assert "source=1, new=1, existing_exact=0, conflicts=0" in output[0]
    assert "no writes performed" in output[1]
    assert SECRET_EMAIL not in "\n".join(output)
    assert HASH not in "\n".join(output)
    assert not gateway.import_calls
    assert not gateway.update_calls


def test_apply_preserves_bcrypt_and_sets_custom_claim():
    gateway = FakeGateway()
    output: list[str] = []

    migration.run(
        apply=True,
        batch_size=500,
        source_loader=lambda _: [source()],
        gateway_factory=lambda: gateway,  # type: ignore[arg-type]
        out=output.append,
    )

    assert len(gateway.import_calls) == 1
    record = gateway.import_calls[0][0]
    assert record.uid == UID1
    assert record.password_hash == HASH.encode("ascii")
    assert record.email_verified is True
    assert record.display_name == "Private Name"
    assert record.custom_claims == {INTERNAL_ID_CLAIM: UID1}
    assert not gateway.update_calls
    assert output[-1] == "Apply complete: imported=1, updated_exact=0, failures=0"
    assert SECRET_EMAIL not in "\n".join(output)
    assert HASH not in "\n".join(output)


def test_exact_existing_user_is_idempotently_updated_and_claims_are_preserved():
    existing = SimpleNamespace(
        uid=UID1,
        email=SECRET_EMAIL.upper(),
        custom_claims={"existing_role": "employee"},
    )
    gateway = FakeGateway([existing])

    migration.run(
        apply=True,
        batch_size=500,
        source_loader=lambda _: [source()],
        gateway_factory=lambda: gateway,  # type: ignore[arg-type]
        out=lambda _: None,
    )

    assert not gateway.import_calls
    assert len(gateway.update_calls) == 1
    updated_user, claims = gateway.update_calls[0]
    assert updated_user.uid == UID1
    assert claims == {"existing_role": "employee", INTERNAL_ID_CLAIM: UID1}


@pytest.mark.parametrize(
    "changes, label",
    [
        ({"uid": "not-a-uuid", "app_user_id": "not-a-uuid"}, "invalid_uuid=1"),
        ({"email": "not-an-email"}, "invalid_email=1"),
        ({"password_hash": "plaintext-secret"}, "invalid_bcrypt=1"),
        ({"email_confirmed": False}, "unconfirmed_email=1"),
        ({"app_user_id": None}, "missing_or_invalid_app_user=1"),
        ({"display_name": ""}, "missing_or_invalid_app_user=1"),
    ],
)
def test_source_validation_aborts_before_firebase_write_without_pii(changes, label):
    gateway = FakeGateway()
    with pytest.raises(migration.MigrationError) as error:
        migration.run(
            apply=True,
            batch_size=500,
            source_loader=lambda _: [source(**changes)],
            gateway_factory=lambda: gateway,  # type: ignore[arg-type]
            out=lambda _: None,
        )
    assert label in str(error.value)
    assert SECRET_EMAIL not in str(error.value)
    assert HASH not in str(error.value)
    assert not gateway.import_calls
    assert not gateway.update_calls


def test_uid_or_email_conflict_aborts_entire_plan_without_pii():
    conflicting = SimpleNamespace(uid=UID2, email=SECRET_EMAIL, custom_claims=None)
    gateway = FakeGateway([conflicting])
    with pytest.raises(migration.MigrationError) as error:
        migration.run(
            apply=True,
            batch_size=500,
            source_loader=lambda _: [source()],
            gateway_factory=lambda: gateway,  # type: ignore[arg-type]
            out=lambda _: None,
        )
    assert "email_conflicts=1" in str(error.value)
    assert SECRET_EMAIL not in str(error.value)
    assert not gateway.import_calls
    assert not gateway.update_calls


def test_duplicate_source_email_aborts_before_writes():
    gateway = FakeGateway()
    with pytest.raises(migration.MigrationError, match="duplicate_email=1"):
        migration.run(
            apply=True,
            batch_size=500,
            source_loader=lambda _: [source(), source(uid=UID2, app_user_id=UID2)],
            gateway_factory=lambda: gateway,  # type: ignore[arg-type]
            out=lambda _: None,
        )
    assert not gateway.import_calls


def test_import_result_error_is_safe_partial_failure():
    gateway = FakeGateway(result=Result(success_count=0, failure_count=1, errors=(object(),)))
    with pytest.raises(migration.MigrationError) as error:
        migration.run(
            apply=True,
            batch_size=500,
            source_loader=lambda _: [source()],
            gateway_factory=lambda: gateway,  # type: ignore[arg-type]
            out=lambda _: None,
        )
    message = str(error.value)
    assert "migration is partial" in message
    assert "failures=1" in message
    assert SECRET_EMAIL not in message
    assert HASH not in message
    assert not gateway.update_calls


def test_default_cli_mode_is_dry_run():
    assert migration.parse_args([]).apply is False


def test_batch_size_is_bounded_before_any_import():
    gateway = FakeGateway()
    plan = migration.Plan((source(),), (source(),), ())
    with pytest.raises(migration.MigrationError, match="between 1 and 1000"):
        migration.apply_plan(plan, gateway, [], 1001)  # type: ignore[arg-type]
    assert not gateway.import_calls
