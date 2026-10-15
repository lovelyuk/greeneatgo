# Owner-requested local abandonment (development contract)

## Authority and schema

Apply the existing infra schema, then Supabase migrations **0064 → 0065 → 0066**. 0065 is integrated byte-identically from local manual-order-close commit `849fa4f`; its database-operator ACL and identity checks remain unchanged. No source migration is applied to a real service by this work.

0066 adds `payment_order_local_abandonments` and service-only `abandon_owned_payment_order(text,uuid,integer,boolean)`. This is **not** a `payment_order_closures` row, provider irreversible-finality attestation, refund, or admin review. New immutable receipt constants: source `owner_request`, scope `local_order`, outcome `abandoned`, provider_finality `unknown`, residual_late_approval_possible `true`. The requested_by actor is the authenticated customer/employee owner, not a synthetic administrator.

An additional closure-insert trigger prohibits converting a local abandonment into an existing verified closure through an older producer. Existing unrelated application/manual closure behavior and grants remain.

## HTTP contract

`POST /payments/orders/{order_id}/abandon`, where order_id is merchant ORDERNO (not the internal UUID), with Bearer owner token:

```json
{"amount":1100,"acknowledge_provider_uncertainty":true}
```

Only strict positive integer amount and strict JSON true are accepted; extra fields, including client user/admin/finality claims, are forbidden. Owner identity comes exclusively from existing token authentication/profile authorization. The service-only RPC repeats active owner role/status, exact order and amount checks inside its transaction. The endpoint reads the exact durable target back via owner recovery before returning success.

The envelope remains `{ "ok": true, "data": recoveryDTO, "error": null }`:

```json
{
  "order_id":"GE-synthetic",
  "user_id":"00000000-0000-4000-8000-000000000001",
  "amount":1100,
  "status":"canceled",
  "recovery_action":"locally_abandoned",
  "resumable":false,
  "checkout_url":null,
  "completion":null,
  "local_abandonment":{
    "id":"00000000-0000-4000-8000-000000000003",
    "source":"owner_request",
    "scope":"local_order",
    "outcome":"abandoned",
    "requested_by":"00000000-0000-4000-8000-000000000001",
    "requested_at":"2026-10-14T00:00:00+00:00",
    "provider_finality":"unknown",
    "residual_late_approval_possible":true
  }
}
```

`GET /payments/recovery?order_id=GE-synthetic&amount=1100` returns the same DTO. Once a late charge is recorded it instead returns `recovery_action: reconcile`, retaining the identical local_abandonment receipt, null completion/checkout URL and resumable false. No verified closure is emitted. The existing actual done-order recovery takes precedence and still produces a completed purchase.

`GET /payments/local-abandonments?limit=20` is a bounded authenticated owner history read for reload after the active checkout intent is retired. Limit defaults to 20, maximum 50, newest receipt first; envelope data is `{orders:[recoveryDTO,...]}`. It reads current discrepancies for every returned order, so a late charge cannot remain hidden behind a cached locally_abandoned classification. No tokens or provider payloads are included. This is recent local-abandonment history, not a paginated replacement for the existing full purchase history; individual exact-order recovery remains available.

Errors: missing/invalid authentication 401, disallowed owner role/status 403, unknown/non-owned order 404, amount mismatch 400, completed/resource/conflicting reservation history 409, ambiguous RPC/storage/readback failure 503 (existing recovery storage errors retain its prior 502 contract). Never retire intent on an error or bare canceled/failed status without a valid receipt.

## Atomic transition

1. Lock exact owned order, require strict explicit consent and positive exact amount.
2. Existing receipt replays without any resource release, but recomputes reconciliation when later payment history contradicts the local stop.
3. First request requires status ready and supported direct/voucher/subsidized pay type; no provider approval/key, fulfillment, issued voucher, refund request, point transaction, redemption, notification inbox, existing closure, or non-failure discrepancy.
4. Lock actual issued coupon and owner wallet; reject used/foreign coupon or underallocated/foreign point reservation. Preserve other orders' aggregate reservations.
5. Append immutable owner receipt, revoke local form admission, release only this order's reserved points/coupon once and set order canceled. Preserve `checkout_guard_epoch` (including legacy NULL) and `checkout_started_at` exactly. Do not revoke external forms or claim that they cannot approve later.
6. Both approval and abandonment lock the same order. Approval-first rejects abandonment; abandonment-first causes existing 0064 notification wrapper to durably quarantine each late/second approval without issuing assets or auto-refunding.
7. A fresh purchase is a new explicit quote/consent/order, never reopening the old form or retrying its hash. Released coupon can be reserved/consumed by the fresh order, while an old late approval cannot redeem it or spend its points.

## Normal checkout return / explicit cancellation (additive 0067)

After 0067, the same owner endpoint also accepts the distinct alternative:

```json
{"amount":1100,"explicit_checkout_cancel_intent":true}
```

For an authenticated owner normal ended-flow request, the alternative is `{"amount":1100,"checkout_return_ended":"sdk_frame_fail"}` or `"mobile_fail"`. These are the only accepted ended provenance values. Exactly one authorization mode is allowed: warning consent, explicit cancellation, or normal checkout return ended. Unknown FAIL must not be described as confirmed user cancellation. The official `/v1/20250423` FRAME SDK overwrites CLOSEURL and FAILURL to the identical `sdkFrameMessage?TYPE=FAIL`; the actual saved bridge emits TYPE only, no 9999. A strict provider origin, exact current iframe WindowProxy and live attempt generation match authorizes owner **local stop**, not a provider-finality claim. Mobile distinct CLOSEURL uses explicit cancellation; mobile FAIL uses ended/unknown reason. Pre-purchase disclosure explains automatic local-stop semantics.

The immutable row stores `acknowledge_provider_uncertainty=NULL` for either new mode (never a fabricated checkbox), plus `explicit_checkout_cancel_intent=true` only for actual distinct mobile CLOSE; otherwise false and the strict `checkout_return_ended` enum. New service-only `abandon_owned_payment_order_intent(text,uuid,integer,boolean,boolean,text default null)` preserves the prior five-argument call by default and shares the existing locked resource/history producer. The old four-argument function remains its compatibility wrapper. RLS/write grants/public financial receipt constants remain unchanged. Clients can request stopping only their own local order; these provenance values are client intent, not server-verified PG evidence.

The frontend must first perform a bounded authenticated recovery read. Completed orders use completion, only still-ready orders invoke local abandonment; reconciliation/errors retain the pending intent. Require exact owner/order/amount and a `locally_abandoned` receipt before resetting purchase. A lost write response requires recovery readback, never automatic hash/purchase retry.

Both checkout GET and SDK POST accept optional query `return_nonce` (exactly 32 lowercase hexadecimal characters, fresh cryptorandom 128-bit per attempt generation). With it, the configured `ADMIN_APP_URL` origin constructs `ORIGIN/payment-return#success.NONCE`, `#fail.NONCE` and **distinct** `#cancel.NONCE` for RETURNURL/HOMEURL, FAILURL, CLOSEURL. No client URL, token, order ID or financial values are reflected in the bridge URL. Invalid configured origin or provider URL exceeding 100 characters fails before admission. Omission preserves the old native/API return URLs unchanged.

The public static `/payment-return` route is explicitly rewritten by Vercel to `/payment-return/index.html`; local Vite dev/preview uses the same static artifact. The bridge removes its strict fragment from browser history, sends only kind/nonce/type over the nonce-specific same-origin BroadcastChannel, and closes without opener access, JWT, order IDs or API writes. The parent consumes a matching live-attempt nonce once. Persisted nonce subscriptions can be restored on reload. Success only requests authenticated server status; it never auto-abandons. Cancel/fail normal returns read status with a 10s bound; only ready/no-approval can invoke the idempotent owned local stop (also bounded). Exact durable local receipt plus matching saved intent and successful storage retirement clears quote, consent, selected product/coupon/points and pending intent, returning the original catalog without another checkbox/click. Unknown reason toast: `구매 진행이 종료됐어요`; distinct mobile CLOSE: `구매 진행을 취소했어요`. Window.closed/force-close/blur/bank-app switch, unsafe events, no-event, fetch/network errors stay on the existing manual uncertain warning/retry path. Read/write/storage failures retain intent with an actionable read retry; lost write response is recovered by reading the exact target first, never by retrying purchase/hash.

## Additional regression found by executable fresh-purchase test

The existing 0060 issued-coupon trigger consumed on `status=done`, then rejected normal same-order fulfillment's later `fulfilled_at` update (`USER_COUPON_CONSUME_CONFLICT`). `backend-green-3.log` is the genuine RED. 0066 replaces that function narrowly: an already-used coupon is accepted only for exact same order/user/merchant/catalog identity with a prior done/fulfilled transition. Foreign-order used coupons still fail atomically. Existing ACLs are revoked again explicitly. This correction is required for a real new coupon purchase after abandonment rather than only a status/resource fixture.

## Verification and limits

Synthetic local FastAPI tests plus real embedded PostgreSQL 16 exercise RED missing producer/route, immutable receipt, strict identity/consent, legacy epoch preservation, exact resource release/replay, financial blockers, approval races with deterministic winners, late/second charge quarantine, new distinct coupon order, and old/manual closure compatibility. GET ready recovery is now a strictly read-only, nonpayable status read: no expiry, wallet release, product eligibility or provider admission is performed. Payable checkout/confirmation retain their existing tax/product/expiry guards. Safe `/p`, `/f`, `/c` return pages carry no submitted fields/messages or payment authority, only close the script-opened popup; the parent only reads Window.closed and its own authenticated order. No provider API, real account, live DB, deployment, refund or commit was performed. External provider finality remains unknown by design.
