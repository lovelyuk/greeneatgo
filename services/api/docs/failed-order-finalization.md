# Failed/canceled order evidence review (server)

## Security boundary and result

`POST /v1/admin/platform/payment-orders/{internal-order-uuid}/review` uses the existing active `platform_admin` permission architecture, not customer/merchant/company roles. The server supplies the actor and computes SHA-256 over canonical JSON including that actor, exact internal order, owner and amount. The service-only database function independently checks these identities, hash and actor under an order lock. Reviews, closures and callback discrepancies are append-only, RLS-enabled, and not client-readable. Only a bounded owner/amount-scoped closure DTO is exposed by recovery.

A provider export containing one failed/canceled attempt is **attempt evidence only**, not no-future-charge proof. The reviewed public documents supply no irreversible closure API. This implementation makes **no provider lookup, payment, cancellation or refund calls** from review. A trusted-provider attestation is an explicit, accountable operator decision backed by separately retained provider evidence, not an automated provider verification claim.

The existing private incident remains unresolved unless an authorized operator obtains adequate evidence and explicitly applies a review. Do not put private exports, real IDs, raw provider/customer payloads or credentials in source control.

## Deployment gate (not executed here)

The delegated migration is `supabase/migrations/0064_failed_order_finalization.sql`; this repository's previous migrations live under `infra/migrations`. Apply the new file explicitly **after 0063** using the normal approved migration process; it is not discovered by the existing infra-only migration glob.

1. Block checkout entry at ingress and drain all old API processes/in-flight hash requests before migration. Keep notifications available. A rolling mixture of old and new checkout implementations is unsafe.
2. Apply 0064 and deploy this API while checkout remains blocked. Validate all supported direct/voucher/subsidized checkout routes use `admit_payment_checkout` before requesting any PG hash, with post-hash revocation recheck.
3. Re-enable checkout only after all old instances are gone. New orders get a guarded epoch. Existing orders retain NULL: missing historical checkout markers never prove no previous form, and legacy unknown orders cannot issue another form.
4. Do not backfill old guard epochs or reset admission markers. A failed hash/network response remains ambiguous and cannot be retried through checkout. Recovery remains nonresumable.

The initial admission is the conservative **potential issuance boundary**, not a provider revoke. Post-hash recheck suppresses forms when revocation is already recorded, but HTTP delivery cannot atomically fence already-issued/in-flight provider forms. Issued-form closure therefore always requires the trusted complete-coverage, irreversible no-future-approval attestation. It must cover every outstanding form and in-flight request. A local row lock alone never supplies external finality.

## Operator dry-run/remediation

Use an authenticated platform admin session through the existing API. Default `dry_run: true` locks and evaluates the current order/wallet but writes nothing. Example shape below uses synthetic placeholders only; compute `source_sha256` from exact original evidence bytes and retain those bytes in restricted evidence storage, referenced by `source_reference`.

```json
{
  "user_id": "00000000-0000-4000-8000-000000000001",
  "amount": 100,
  "outcome": "canceled",
  "source_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "source_reference": "restricted-evidence/synthetic-case-001",
  "attempts": [{"transaction_id": "synthetic-trx", "outcome": "failed"}],
  "authority": "attempt_only",
  "complete_attempt_coverage": false,
  "irreversible_no_future_approval": false,
  "provider_closure_reference": null,
  "dry_run": true
}
```

- **One failed attempt / unknown issued-form finality:** keep `authority: attempt_only`. To durably record the review, explicitly resubmit with `dry_run: false`. This revokes further local entry, records actor/hash/exact attempts, retains reservations, and returns `closed: false`, `recovery_action: reconcile`. It does not falsely unblock the order.
- **Provably no issued form:** `authority: no_issued_form`, `attempts: []`. The DB additionally requires a post-cutover guarded order, no admission marker and no known callback attempt. Never select this for legacy unknown state. Explicit apply produces closure and releases only the order's unspent point reservation.
- **Issued or legacy-unknown form:** `authority: trusted_provider_irreversible_closure` requires `complete_attempt_coverage: true`, `irreversible_no_future_approval: true`, a substantive `provider_closure_reference`, and every enumerated attempt in failed/canceled state. Include every known durable attempt. Obtain provider evidence covering all forms, methods, transactions, visibility/in-flight races and future approval prevention. Neither one failed row, blank result, browser close, source canceled status nor merchant portal snapshot alone supplies this authority.
- Dry-run is advisory: repeat current checks atomically on explicit apply. An approval, issuance, refund, coupon redemption, point spend, inconsistent wallet reservation or other-order reservation conflict can block application.
- Exact evidence replay is idempotent. A different evidence hash after closure conflicts rather than rewriting history. Correct erroneous evidence with a new reviewed operational case; never delete history or reopen a closed payable order.

Verify the exact target through the API/approved service readback after apply: review/closure ID, owner, amount, hash, terminal outcome, wallet reservation and matching recovery DTO. A fresh purchase must be a new explicit user action, not automatic checkout replay.

## Resources and late notifications

Order, issued-coupon and wallet locks serialize review versus fulfillment/admission. Point release subtracts exactly the order's reservation, once, without changing balance or taking another order's reservation. Existing issued vouchers, point transactions, refund history, provider approval/inbox or coupon redemption block unpaid finalization. The 0059 promotion catalog remains reusable and is never mutated. The newer 0060 `user_coupons` instances are separately reserved: verify exact user, merchant, catalog and reservation owner under lock, refuse used/another-order instances, and release only this order's reservation exactly once (available or expired), including historically terminal stranded reservations. Successful native/zero/points fulfillment and approved refund workflows remain intact. Existing subsidized pre-entry expiry/client release is restricted to guarded, never-issued, non-revoked orders; unknown legacy/reviewed orders cannot bypass reconciliation through the old missing-marker sweeper.

Successful late approvals of failed/canceled/refunded orders and second DAOUTRX values are durably quarantined without new fulfillment or automatic refund. An observed late approval contradicts a prior closure attestation: recovery and review replay return reconcile, while keeping immutable closure history. Failure/cancel notifications are ACKed only after durable recording, including unmatched BANK_CANCEL (which may omit ORDERNO); they do not finalize an order. Sensitive callback fields remain normalized/masked. A storage failure returns FAIL so delivery may retry. Operators must investigate discrepancies and use existing authorized approved-transaction refund/reconciliation workflows where appropriate.

## Non-destructive rollback

`supabase/operations/pause_failed_order_review.sql` disables service-role execution of the review producer only. It retains evidence, closures, reservation releases, one-shot admission and durable late/second callback handling. Recovery can still show previously verified closures. Re-enable only by an approved explicit EXECUTE grant. Do not roll back data, delete audit history, restore reservations already released, reset started/revoked markers, or reopen closed orders. If rolling application code backward, block checkout at ingress for the entire rollback; old direct/voucher paths are not safe to resume.

## Local verification

`tests/test_failed_order_finalization.py` exercises HTTP permissions, DTO boundaries, schema/default dry-run, pre-hash guard, post-hash revocation, ACK/storage failure. `tests/test_failed_order_postgres.py` applies all 0001–0063 migrations plus 0064 to a dedicated disposable PostgreSQL 16 database and exercises immutable/idempotent closure, legacy unknown refusal, trusted attestation gating, durable callbacks, exact reservation accounting, ACLs and real competing connections. Its fixture drops/recreates public/auth/storage: **never use a shared or production TEST_DATABASE_URL**.
