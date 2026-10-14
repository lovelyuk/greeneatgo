# PC official Kiwoom SDK frontend

## Supported presentations

- Positive desktop **TOTAL**: official fixed HTTPS `https://ssl-v2.kiwoompay.co.kr/sdk/v1/latest/kiwoompayEnc.js`, loaded once on purchase intent **before** creating an order. Shared load promise, bounded 15-second timeout; failure is cached without automatic retry. Quote/legal/account/unmount fences run again after preload. No popup or custom HTML payment iframe.
- Positive mobile: original synchronous `about:blank` popup before purchase, `opener=null`, exact existing `safeCheckoutUrl` validation and location replacement. No SDK script load. Official SDK UA regex plus Macintosh/MacIntel + multiple touch points iPad desktop-mode fallback, not viewport width. Presentation is captured per attempt; resizing never changes it.
- Positive desktop **BANK**: explicit Korean UI explanation; old popup path retained. The official SDK unconditionally forces TOTAL, so we do not call it for BANK or widen the requested method. `PurchaseCatalog.jsx` has one necessary prop wire from the selected product to checkout; the server still enforces stored method.
- Zero quoted payable amount: no SDK script/popup/frame/hash; existing atomic point-only fulfillment and discrepancy verification retained.

## One-shot and trust boundary

Pending/unknown intent is stored before purchase I/O; returned order is persisted before external admission. SDK entry sets `checkout_started` and stores it before one authenticated `POST /payments/checkout/{token}/sdk`. Token path comes only from the unchanged API-origin-bound `safeCheckoutUrl`; request contains no provider/order/amount override. SDK data must match stored order and amount, TYPE=P, PAYMETHOD=TOTAL, CPID8, opaque bounded hash, required fields, exact DEV/REAL mode. Failure after order creation/admission keeps the pending order; no retries, old-popup fallback, or reopen action.

`kiwoomSdk.js` calls the actual `f_setInit(mode, "FRAME")`, `f_setFrameSize`, and `f_payTotalLink`. The SDK creates its own frame/form/dimmer directly under the merchant document body, not inside a bridge iframe. Immediately after synchronous creation, its broad original message listener is removed and replaced with a wrapper. Only exact environment-specific SSL origin, `event.source === officialIframe.contentWindow`, and known SUCCESS/FAIL structural payloads may reach the captured original handler. Wrong environment, suffix/subdomain spoofing, wrong source, unknown/missing TYPE, malformed RESULTCODE, and contradictory TYPE/result combinations do nothing. No provider callback invokes `/confirm`, cancel, ticket issuance, or local approval: it only initiates an authenticated `/payments/recovery` read. Existing server completion/closure verification remains authoritative.

Closing uses `f_closeFrame`; listeners/focus/background inert state are cleaned up, pending remains. Official close button has an accessible name, modal dialog semantics, initial focus, merchant focus containment, Tab entry/exit and ESC on the merchant document. Logout/unmount and delayed callback/hash/script responses are generation fenced. Cross-origin provider keyboard events cannot be intercepted inside its document; provider-side ESC behavior remains unverified. The outer official frame is viewport-constrained, retaining the official form and frame; actual provider content reflow below its SDK's original 850px minimum is not certified by isolated mocks.

## Executable fixture verification

Run serially in `apps/admin`:

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm test
PURCHASE_RECEIPTS=/absolute/receipt/directory npm run test:browser
```

`browser/pc-sdk.spec.mjs` reads saved unmodified official source, fulfills only its fixed URL, and asserts SHA-256 `2e104d2178f8e447164e57f0a72e0b10c2b803a4597bb1f6c6d964fa7cf18e20`. Default saved fixture path is the task's reconciliation cache; portable runners can set `KIWOOM_SDK_FIXTURE_SOURCE` to a copy with that exact hash. External requests are aborted by the shared fixture. Provider `form.submit` I/O is intercepted **before transport**, while actual official SDK DOM/form/listener code executes. Screenshot frame contents are intentionally blank: these are outer modal/layout receipts, not real provider payment screens. API/auth responses and identifiers are synthetic. No actual provider submit/network, account, charge, SQL, deployment or native change was performed.

Legacy `purchase.spec.mjs` and `final-L1.spec.mjs` now explicitly use a mobile UA to preserve their original popup acceptance; new PC tests cover desktop-wide/narrow and mobile-wide/iPad-touch independently.

Receipt root: `/home/lovelyuk/.hermes/profiles/aebong/cache/long-tasks/greeneat-pc-sdk-frame-receipts/`.

- `frontend-unit-RED.log`: missing SDK module, real failing node test before implementation.
- `frontend-browser-RED.log`: desktop FRAME and preload-before-order tests both fail against baseline.
- `frontend-preload-quote-RED.log`: additional actual failing race test (purchase count 1 instead of 0), then quote/legal live fence fixed it.
- `frontend-unit-final-GREEN.log`: 145 passed, zero failed.
- `frontend-browser-full-final-GREEN.log`: 175 passed, one skipped; includes 31 PC SDK tests. Skip is pre-existing isolated PostgreSQL producer lifecycle gate requiring `FINALIZE_FIXTURE_PYTHON` and `FINALIZE_TEST_DATABASE_URL`; no DB runtime was started.
- `official-sdk-browser-trace.json`: exact source hash, actual SDK form fields/action/target, no provider transport, one purchase/hash.
- `pc-sdk-{desktop-narrow,desktop-1024,desktop-1440,mobile-360,mobile-390,mobile-wide,ipad-desktop-touch}.png`: viewport captures, animations/transitions disabled.

Parent owns independent review and final production-public-config build; browser suites deliberately build fixture config. Live authenticated Kiwoom/provider app-switch, CSP/cross-origin deployment E2E and real provider narrow-content accessibility remain unverified. Do not publish the fixture dist or claim mock integration proves a real charge.
