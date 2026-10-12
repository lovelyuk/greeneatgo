# Purchaser web parity and release gates

## Route and configuration

`/shop` (also `/shop/`) is a separate, lazy-loaded purchaser surface. The existing admin route, invite route and admin API role checks are unchanged. Purchaser UI admits only active `customer` and `employee` profiles; pending/suspended/inactive profiles cannot load the catalog. No-profile and rejected employee users can request customer registration; company membership uses the existing invitation endpoint and waits for server approval.

Only the existing public variables are used: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_BASE_URL`. Never supply a service-role key or Kiwoom secret to Vite. Supabase email/password sign-in and signup use the existing public client; signup verification links return to `/shop` (the origin/path must be allowlisted in Supabase). No auth or payment production operation was exercised for this implementation.

## Native/API parity implemented

- `/me` drives account status, available ticket balance, points, ticket-use/recent-payment/point histories; refresh reloads authoritative data. Logout invalidates in-flight requests and closes the client-owned checkout window.
- `/vouchers/products` drives ordinary versus subsidized eligibility, package quantity, paid/bonus counts, list price, discount, event-sale end and payment method. Package selection is the supported quantity model: no arbitrary cart quantity is invented or sent.
- `/coupons` supplies the merchant identity, reusable public coupons and owned issued coupons; `coupon_id` and `user_coupon_id` are mutually exclusive in the payload.
- `/vouchers/quote` supplies the displayed coupon/point/card split. Ordinary accounts always request zero points. Employee points are nonnegative safe integers; quote edits invalidate prior quotes. Product, merchant, purchase mode and whole-KRW price consistency are checked before exposing purchase.
- `/vouchers/purchase` and `/vouchers/purchase-subsidized` receive only `product_id`, `requested_point_amount` and the selected coupon identifier. Prices are recalculated by the server, never submitted by the client.
- Orders open only the exact configured API `/payments/checkout/{43-character URL-safe token}` endpoint. HTTP is allowed only for loopback development. Cross-origin, credential-bearing, encoded, queried, fragment-bearing, malformed and unknown provider URLs are blocked. The server—not this web app—owns Kiwoom's EUC-KR POST form and security fields. A popup is reserved synchronously before creating a card order, so a blocked popup cannot silently create an order.
- Purchase requests cap requested points at the accepted quote's point amount. Final server gross, coupon discount, point and card amounts are compared with the accepted quote before positive-card checkout; changed pricing blocks unapproved checkout. Point-only orders complete only from valid authenticated atomic fulfillment with matching `order_id`, `status: done`, exact zero card amount and matching issued count. Completion displays fulfillment-authoritative points spent; pricing or point metadata discrepancies remain truthfully completed with a prominent reconciliation warning and no repeat-purchase action. Missing/malformed fulfillment remains unresolved and blocks retries. Point-only orders never call the positive-amount-only `/payments/confirm` endpoint or open PG. Card/mixed flows complete only after `status: done`, matching order ID and exact positive amount from the owner-filtered confirmation endpoint. Redirects, query strings, postMessage and popup closure do not mark an order paid.
- Pending order identity/amount/mode/checkout-entry boundary persist in per-user sessionStorage, without auth tokens or checkout URLs. Duplicate clicks are locked. Unknown creation results are not automatically retried, including after reload. Manual reconciliation is required where the server cannot provide an order identifier.
- Subsidized reservation cancellation is offered only before the client enters checkout. Only server `released: true` or `status: canceled` confirms cancellation. Server refusal leaves the order pending. Once checkout begins, there is no automatic cancellation/release.
- Official sales-slip/cash-receipt links from server completion reuse the existing strict Kiwoom receipt allowlist. Untrusted receipt URLs are omitted.

## Deliberate fail-closed limitations

Existing `/terms.html` and `/privacy.html` contain unpublished placeholders. They are linked unchanged; no new business names, contact details, refund policy, expiry or provider claims are fabricated. Signup/customer registration are blocked for missing/unpublished documents. Purchase additionally requires the selected merchant name and populated business-registration/provider disclosure indicators in the existing terms source. **This is a conservative UI publication check, not legal certification:** operator/legal review must publish and verify actual merchant/provider facts before release. The current repo documents do not pass this gate.

The existing native/API contract has no multi-merchant purchaser catalog selector, per-unused-ticket expiry DTO or complete purchaser order-history endpoint. `/me` is the current parity surface; the UI explicitly says the omitted metadata is unavailable. Employee `/me` currently reports `voucher_balance: null`, which is shown as unavailable rather than fabricated. Backend contract additions are out of this UI-only scope.

The confirmation endpoint returns `PAYMENT_PENDING` for every non-done status, including provider cancellation/failure; therefore ordinary canceled/failed terminal status cannot be truthfully certified by this UI. It presents verification errors or cancellation intent while retaining pending authority. Ordinary cancellation has no supported endpoint. No native API/backend change or migration was made.

There is no server idempotency-key contract for voucher creation. The web UI prevents duplicate submission within the component/session and conservatively blocks ambiguous retries, but cannot promise cross-tab/device or server-side exactly-once creation. Checkout URL origin must match the configured API base; a differently configured `public_api_base_url` fails closed.

## Verification and reproduction

From `apps/admin`:

```sh
npm ci
npm test
NODE_OPTIONS=--max-old-space-size=4096 npm run build
npx playwright install chromium
PURCHASE_RECEIPTS="$TMPDIR/greeneat-purchase-receipts" npm run test:browser
```

Browser tests live in `browser/*.spec.mjs`, outside Node's discovered test filenames/directories. Playwright uses one worker, builds with explicitly fake public configuration then runs the actual emitted production assets through loopback Vite preview, blocks unmocked external traffic, asserts no uncaught page/popup runtime errors, and interacts with actual rendered React UI. Auth/API/provider forms are deterministic **mocked I/O**, not evidence of live Supabase, Kiwoom or a real payment. Desktop/mobile PNG screenshots are real Chromium captures of this mocked production-build integration and are saved outside the repository.

Acceptance includes signup/email verification, login error/role rejection, registration and membership states, catalog/package/coupon/points payloads, ordinary/card/mixed/point-only flow, pending/approved/error/cancel behavior, reload recovery, duplicate-submit and session-race protection, histories, receipt allowlisting, legal gates and admin/purchaser route isolation.

An early anchored Playwright grep selected no tests. Those RED logs are explicitly **invalid**. The affected production components/features were removed and rewritten in vertical cycles against the existing tests using corrected selectors; authoritative replacement receipts are named `redo-*`. No-tests results were not counted as RED. The originally valid foundation and safety-unit RED/GREEN receipts remain valid. See the external receipt manifest and checkpoint for exact runs.

Independent reviews identified and corrected the zero-amount confirm/API mismatch, changed browser verification from dev source to production build, and added explicit empty/load-failure states (`review-R1-*`, `review-R2-*`, `review-R3-*`). A further independent review found FINAL-L1 stale-quote point overspending; strict RED/GREEN corrections cap the submitted points and disclose authoritative completed-order discrepancies (`final-L1-*`). Fresh independent re-review approved all 15 changed files with hash binding: 91 admin tests and 45 production-build mocked browser tests passed, with build and diff checks successful. Approval applies to source correctness, not live payment or release certification. Work is preserved on detached HEAD only; main integration, push and deployment are not authorized.

The current Flutter initial login uses Firebase phone authentication, whereas this surface deliberately reuses the requested existing Supabase administrator-web public client. Existing phone-only account continuity and migration/linking are **not verified**; this is an authentication-parity release gate, not a claim that phone-login users can use email login. No Firebase config or account linking was invented.

Authoritative legal publication, configured-auth/account continuity validation and authorized real Kiwoom testing remain release gates. A reviewed detached commit may preserve the artifact; main integration, push, deploy, migration, production write and live payment are not included.
