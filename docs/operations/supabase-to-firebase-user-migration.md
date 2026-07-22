# Supabase → Firebase existing-user migration runbook

This runbook migrates **confirmed Supabase email/password users** while preserving their bcrypt password hashes. Firebase UIDs remain the canonical Supabase/app-user UUIDs, and each imported account receives the signed custom claim `greeneatgo_internal_id` with that same UUID.

The utility is intentionally dry-run by default and prints aggregate counts only. It does not print emails, display names, hashes, database URLs, or credentials.

## Safety model and limitations

- The script reads `auth.users` directly, joins `public.app_users`, and selects only identities with a non-empty email and password hash. OAuth-only and phone-only identities are not imported.
- Every selected record must have a canonical lowercase/hyphenated UUID, syntactically valid email and bcrypt modular-crypt hash, confirmed email, and matching `public.app_users` row with a non-empty `display_name`.
- The complete source set and Firebase directory are preflighted before any write. Duplicate source emails/UIDs and conflicting Firebase emails/UIDs abort the run.
- A Firebase user with both the exact UID and same case-insensitive email is treated as an idempotent rerun: profile fields, verified status, and the internal-ID claim are updated. Other existing claims are preserved. The password hash is not overwritten for such already-existing accounts because Firebase does not expose it for comparison.
- **The operation is not transactional.** Firebase bulk import can return per-record errors, a later batch can fail after earlier batches succeeded, and exact-user updates happen after imports. The command exits nonzero and reports aggregate failure counts without exposing record data. Correct the cause and rerun; successful imports become exact existing users on the deterministic rerun.
- Avoid concurrent Firebase account creation during the apply window. A race after preflight can still produce a partial import error.

## 1. Prerequisites

1. Deploy and validate the backend dual-auth support **before** importing users. Apply the auth-FK decoupling migration required by that deployment.
2. In **Firebase Console → Authentication → Sign-in method**, enable **Email/Password** for the target Firebase project.
3. Confirm the target Firebase project is the one configured in the client/backend. Use a service account with permission to list, import, and update Firebase Authentication users. Store it only in the deployment shell/secret manager.
4. Take and retain a current Supabase/Postgres backup. Record the target Firebase project ID separately for the change ticket (do not paste credentials).
5. Schedule a low-traffic change window and prevent concurrent account provisioning if possible.
6. Install the API dependencies from `services/api` (for example, `uv sync`). The migration requires the project dependencies, including `firebase-admin` and `psycopg`.

## 2. Set credentials securely

Set one Firebase credential variable and one database URL in the current process. Do not place these values in source control, shell history, tickets, or logs.

- `FIREBASE_SERVICE_ACCOUNT_JSON`: service-account JSON, **or**
- `FIREBASE_SERVICE_ACCOUNT_JSON_BASE64`: strict Base64 encoding of that JSON
- `SUPABASE_DB_URL`: direct/pooler Postgres URL with read access to `auth.users` and `public.app_users`; `DATABASE_URL` is accepted as a fallback

The existing backend Firebase credential helper is used. If both Firebase variables are present, the Base64 value takes precedence. Prefer an ephemeral secret-injection mechanism over interactive `export` commands.

## 3. Dry-run (mandatory)

From `services/api`:

```bash
.venv/bin/python scripts/migrate_supabase_users_to_firebase.py
```

Expected output contains only aggregate readiness counts, for example `source`, `new`, `existing_exact`, and `conflicts`. It ends with `no writes performed`. Any validation or conflict count aborts the migration; investigate in controlled database/Firebase tooling, not by adding record-level logging to this script.

Save the aggregate output and reconcile the source count against an independently approved aggregate count of confirmed password users with matching app-user rows.

## 4. Apply

Only after a clean dry-run and change approval:

```bash
.venv/bin/python scripts/migrate_supabase_users_to_firebase.py --apply
```

The default batch size is 500. If operationally required, set `--batch-size N`; `N` must be 1–1000. Do not run multiple copies concurrently.

A successful command exits 0 and reports aggregate imported/updated/failure counts. Any nonzero exit means the operation may be partial. Do not delete Firebase users or restore blindly: preserve output, resolve the configuration/conflict, run dry-run again, and deterministically rerun `--apply`.

## 5. Verify before client release

1. In Firebase Console, confirm aggregate user count changes and inspect a small, approved sample:
   - Firebase UID equals the existing Supabase UUID.
   - Email is verified.
   - Display name is populated from `public.app_users`.
   - The custom claim is not shown in every Console view; verify it through a restricted Admin SDK check or a freshly issued ID token without logging the token or PII.
2. Using designated test accounts, verify sign-in with the existing password. This proves bcrypt compatibility. Never ask users for passwords and never log them.
3. Verify the backend accepts a **fresh** Firebase ID token and resolves the account to the same app-user UUID. Claims are token-cached; sign out/in or force-refresh the token after claim updates.
4. Test the Firebase password-reset flow end to end and then verify sign-in with the new password.
5. Confirm existing Supabase-token traffic still works during the dual-auth transition and monitor authentication error/latency aggregates.
6. Only after these checks pass, release the Firebase-auth-enabled app. Keep dual-auth active for the approved transition period and follow the separate rollback/decommission plan.

## Rollback/incident guidance

There is no atomic rollback. Pause the app release/account provisioning, keep dual-auth serving existing clients, capture only aggregate command/error output, and determine which deterministic rerun step failed. Do not mass-delete imported Firebase users: that can remove subsequent legitimate password resets or account changes. Escalate with the Supabase backup, change timestamps, aggregate counts, and Firebase audit logs—never service-account JSON, database URLs, emails, ID tokens, or password hashes.
