#!/usr/bin/env python3
"""Safely import existing Supabase email/password users into Firebase Auth.

Dry-run is the default. This command never logs source records, e-mail addresses,
or password hashes; its output is aggregate-only.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Iterable, Sequence
from uuid import UUID

# Permit direct execution from services/api/scripts.
API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from firebase_admin import auth  # noqa: E402

from app.services.firebase_auth import INTERNAL_ID_CLAIM  # noqa: E402
from app.services.push_notifications import _firebase_app  # noqa: E402

MAX_FIREBASE_IMPORT_BATCH = 1000
DEFAULT_BATCH_SIZE = 500
# Supabase/GoTrue crypt hashes are modular-crypt bcrypt strings. Firebase wants
# the complete encoded hash as bytes (including algorithm, cost, and salt).
BCRYPT_RE = re.compile(r"^\$2[aby]\$(0[4-9]|[12][0-9]|3[01])\$[./A-Za-z0-9]{53}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class MigrationError(RuntimeError):
    """A safe, deliberately non-PII operational error."""


@dataclass(frozen=True)
class SourceUser:
    uid: str
    email: str
    password_hash: str
    email_confirmed: bool
    app_user_id: str | None
    display_name: str | None


@dataclass(frozen=True)
class Plan:
    source: tuple[SourceUser, ...]
    to_import: tuple[SourceUser, ...]
    to_update: tuple[SourceUser, ...]


class FirebaseGateway:
    def __init__(self) -> None:
        self.app = _firebase_app()

    def list_users(self) -> Iterable[Any]:
        page = auth.list_users(app=self.app)
        while page:
            yield from page.users
            page = page.get_next_page()

    def import_users(self, records: Sequence[Any]) -> Any:
        return auth.import_users(
            list(records), hash_alg=auth.UserImportHash.bcrypt(), app=self.app
        )

    def update_existing(self, user: SourceUser, claims: dict[str, Any]) -> None:
        auth.update_user(
            user.uid,
            email=user.email,
            email_verified=True,
            display_name=user.display_name,
            app=self.app,
        )
        auth.set_custom_user_claims(user.uid, claims, app=self.app)


def database_url_from_env() -> str:
    value = (os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not value:
        raise MigrationError("SUPABASE_DB_URL or DATABASE_URL is required")
    return value


def load_source_users(database_url: str) -> list[SourceUser]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - deployment packaging guard
        raise MigrationError("psycopg is not installed; install API dependencies") from exc

    # Select only password identities. OAuth-only/phone-only identities have no
    # reusable bcrypt hash and are intentionally outside this migration.
    query = """
        select au.id::text as uid,
               au.email,
               au.encrypted_password as password_hash,
               (au.email_confirmed_at is not null) as email_confirmed,
               pu.id::text as app_user_id,
               pu.display_name
          from auth.users au
          left join public.app_users pu on pu.id = au.id
         where au.email is not null
           and au.encrypted_password is not null
           and au.encrypted_password <> ''
         order by au.id
    """
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
    except Exception as exc:
        raise MigrationError("Supabase database read failed") from exc
    return [SourceUser(**dict(row)) for row in rows]


def _canonical_uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def validate_source(users: Sequence[SourceUser]) -> None:
    invalid_uuid = invalid_email = invalid_hash = unconfirmed = missing_profile = 0
    duplicate_uid = duplicate_email = 0
    seen_uids: set[str] = set()
    seen_emails: set[str] = set()

    for user in users:
        canonical_email = user.email.strip().casefold() if isinstance(user.email, str) else ""
        if not _canonical_uuid(user.uid):
            invalid_uuid += 1
        if not canonical_email or not EMAIL_RE.fullmatch(user.email.strip()):
            invalid_email += 1
        if not isinstance(user.password_hash, str) or not BCRYPT_RE.fullmatch(user.password_hash):
            invalid_hash += 1
        if user.email_confirmed is not True:
            unconfirmed += 1
        if user.app_user_id != user.uid or not isinstance(user.display_name, str) or not user.display_name.strip():
            missing_profile += 1
        if user.uid in seen_uids:
            duplicate_uid += 1
        seen_uids.add(user.uid)
        if canonical_email in seen_emails:
            duplicate_email += 1
        seen_emails.add(canonical_email)

    problems = {
        "invalid_uuid": invalid_uuid,
        "invalid_email": invalid_email,
        "invalid_bcrypt": invalid_hash,
        "unconfirmed_email": unconfirmed,
        "missing_or_invalid_app_user": missing_profile,
        "duplicate_uid": duplicate_uid,
        "duplicate_email": duplicate_email,
    }
    if any(problems.values()):
        summary = ", ".join(f"{name}={count}" for name, count in problems.items() if count)
        raise MigrationError(f"Source preflight failed ({summary})")


def build_plan(source: Sequence[SourceUser], firebase_users: Iterable[Any]) -> Plan:
    validate_source(source)
    by_uid: dict[str, Any] = {}
    by_email: dict[str, Any] = {}
    firebase_duplicate_uid = firebase_duplicate_email = 0
    for existing in firebase_users:
        uid = getattr(existing, "uid", None)
        email = getattr(existing, "email", None)
        if isinstance(uid, str):
            if uid in by_uid:
                firebase_duplicate_uid += 1
            by_uid[uid] = existing
        if isinstance(email, str) and email.strip():
            key = email.strip().casefold()
            if key in by_email:
                firebase_duplicate_email += 1
            by_email[key] = existing
    if firebase_duplicate_uid or firebase_duplicate_email:
        raise MigrationError(
            "Firebase preflight failed "
            f"(duplicate_uid={firebase_duplicate_uid}, duplicate_email={firebase_duplicate_email})"
        )

    to_import: list[SourceUser] = []
    to_update: list[SourceUser] = []
    uid_conflicts = email_conflicts = 0
    for user in source:
        existing_uid = by_uid.get(user.uid)
        existing_email = by_email.get(user.email.strip().casefold())
        if existing_uid is None and existing_email is None:
            to_import.append(user)
            continue
        exact = (
            existing_uid is not None
            and getattr(existing_uid, "email", "").strip().casefold()
            == user.email.strip().casefold()
            and (existing_email is None or getattr(existing_email, "uid", None) == user.uid)
        )
        if exact:
            to_update.append(user)
        else:
            if existing_uid is not None:
                uid_conflicts += 1
            if existing_email is not None and getattr(existing_email, "uid", None) != user.uid:
                email_conflicts += 1
    if uid_conflicts or email_conflicts:
        raise MigrationError(
            "Firebase preflight failed "
            f"(uid_conflicts={uid_conflicts}, email_conflicts={email_conflicts})"
        )
    return Plan(tuple(source), tuple(to_import), tuple(to_update))


def import_record(user: SourceUser) -> Any:
    return auth.ImportUserRecord(
        uid=user.uid,
        email=user.email.strip(),
        email_verified=True,
        display_name=(user.display_name or "").strip(),
        password_hash=user.password_hash.encode("ascii"),
        custom_claims={INTERNAL_ID_CLAIM: user.uid},
    )


def _existing_claims(firebase_by_uid: dict[str, Any], uid: str) -> dict[str, Any]:
    current = getattr(firebase_by_uid[uid], "custom_claims", None)
    return dict(current) if isinstance(current, dict) else {}


def apply_plan(
    plan: Plan,
    gateway: FirebaseGateway,
    firebase_users: Sequence[Any],
    batch_size: int,
) -> tuple[int, int]:
    if not 1 <= batch_size <= MAX_FIREBASE_IMPORT_BATCH:
        raise MigrationError(f"batch size must be between 1 and {MAX_FIREBASE_IMPORT_BATCH}")

    imported = 0
    for start in range(0, len(plan.to_import), batch_size):
        batch = plan.to_import[start : start + batch_size]
        try:
            result = gateway.import_users([import_record(user) for user in batch])
        except Exception as exc:
            raise MigrationError("Firebase import request failed; migration may be partial") from exc
        errors = list(getattr(result, "errors", ()) or ())
        failure_count = int(getattr(result, "failure_count", len(errors)) or 0)
        success_count = int(getattr(result, "success_count", len(batch) - failure_count))
        imported += success_count
        if errors or failure_count or success_count != len(batch):
            # Error details can contain PII, so report counts only.
            raise MigrationError(
                "Firebase import batch had failures; migration is partial "
                f"(batch_size={len(batch)}, success={success_count}, failures={max(failure_count, len(errors))})"
            )

    firebase_by_uid = {item.uid: item for item in firebase_users}
    updated = 0
    for user in plan.to_update:
        claims = _existing_claims(firebase_by_uid, user.uid)
        claims[INTERNAL_ID_CLAIM] = user.uid
        try:
            gateway.update_existing(user, claims)
        except Exception as exc:
            raise MigrationError("Firebase existing-user update failed; migration may be partial") from exc
        updated += 1
    return imported, updated


def run(
    *,
    apply: bool,
    batch_size: int,
    source_loader: Callable[[str], list[SourceUser]] = load_source_users,
    gateway_factory: Callable[[], FirebaseGateway] = FirebaseGateway,
    out: Callable[[str], None] = print,
) -> int:
    database_url = database_url_from_env()
    try:
        source = source_loader(database_url)
    except MigrationError:
        raise
    except Exception as exc:
        raise MigrationError("Supabase database read failed") from exc
    try:
        gateway = gateway_factory()
        firebase_users = list(gateway.list_users())
    except MigrationError:
        raise
    except Exception as exc:
        raise MigrationError("Firebase directory preflight failed") from exc
    plan = build_plan(source, firebase_users)
    out(
        "Preflight ready: "
        f"source={len(plan.source)}, new={len(plan.to_import)}, existing_exact={len(plan.to_update)}, conflicts=0"
    )
    if not apply:
        out("Dry-run complete: no writes performed. Re-run with --apply after reviewing the runbook.")
        return 0
    imported, updated = apply_plan(plan, gateway, firebase_users, batch_size)
    out(f"Apply complete: imported={imported}, updated_exact={updated}, failures=0")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform Firebase writes (default: dry-run)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(apply=args.apply, batch_size=args.batch_size)
    except MigrationError as exc:
        print(f"Migration aborted: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
