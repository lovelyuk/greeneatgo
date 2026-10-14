# PC Kiwoom SDK backend contract

`POST /payments/checkout/{checkout_token}/sdk` (API deployment prefix unchanged).
Requires `Authorization: Bearer …`; active customer/employee must own the ready
order identified by the existing checkout token. No body is required; any body
values are ignored. This endpoint creates neither an order nor a payment approval.

Success is JSON with `Cache-Control: no-store`:

```json
{"ok":true,"data":{"sdk_mode":"DEV","fields":{"PAYMETHOD":"TOTAL","TYPE":"P","CPID":"TEST0001","ORDERNO":"FIXTURE_ORDER_1","PRODUCTTYPE":"2","AMOUNT":"1200","PRODUCTNAME":"식권 상품","PRODUCTCODE":"fixture-pr","USERID":"fixture-owner","RETURNURL":"https://merchant.example/p","HOMEURL":"https://merchant.example/p","FAILURL":"https://merchant.example/f","CLOSEURL":"https://merchant.example/c","APPURL":"fixture://","DIRECTRESULTFLAG":"Y","KIWOOM_ENC":"fixture-opaque-hash"}},"error":null}
```

This example is entirely synthetic. `data` contains only `sdk_mode` and `fields`.
Fields are constructed from the stored order/configuration, never request values
or raw provider responses. `ORDERNO` is preserved exactly and used identically in
the hash and form. Amount is a positive integer, at most 10 decimal digits.
CPID must be eight ASCII alphanumeric characters. Existing product/user field
sanitization and truncation are retained (50/10/30 characters). Hash is a nonblank,
non-whitespace string of at most 1000 characters, with no pipe/control characters.
Redirects retain existing origin-root `/p`, `/f`, `/c` contracts; URLs are bounded
to 100 characters. No keys/secrets or provider snapshot are returned.

Exact configured API base URL mapping (no normalization/default):

- `https://api.kiwoompay.co.kr` → `REAL`
- `https://apitest.kiwoompay.co.kr` → `DEV`
- Anything else → HTTP 503 `KIWOOMPAY_SDK_NOT_CONFIGURED`, before admission/hash.

Frontend merchant-root usage: initialize the official SDK with
`KiwoomPaySDK.f_setInit(data.sdk_mode, "FRAME")`, attach merchant-owned callbacks
to `data.fields`, then call `KiwoomPaySDK.f_payTotalLink(data.fields)`.
Do not treat a callback as authoritative approval; existing notification/confirm
logic remains authoritative. The SDK owns its iframe/form, EUC-KR submission,
and FRAME result URLs. Native/mobile GET HTML is unchanged (`TYPE=W`).

## BANK and single entry

The saved official script unconditionally sets `PAYMETHOD=TOTAL`. Thus desktop
BANK orders must select the existing explicit popup flow **before** requesting
this endpoint. BANK is HTTP 409 `SDK_PAYMENT_METHOD_UNSUPPORTED`, with no admission
or hash. Unknown methods get `INVALID_PAYMENT_METHOD`. Never convert BANK to TOTAL
or fallback after a started SDK attempt.

Tax classification, voucher availability, and DB-clock subsidized expiry checks
are retained. After validating the snapshot/configuration, the route invokes
`admit_payment_checkout`, requests a hash with `TYPE=P` / `PAYMETHOD=TOTAL`, then
invokes `assert_payment_checkout_active` before returning the fields. Both RPCs
retain the existing 0064 contract. Admission/repeat/post-hash rejection returns
HTTP 409 `ORDER_NOT_READY`. Hash failure returns bounded HTTP 502
`KIWOOMPAY_HASH_FAILED`; malformed hash returns `KIWOOMPAY_INVALID_RESPONSE`.
Admission is never undone on either failure; retries cannot issue another hash.
Direct/voucher/subsidized orders share the same one-shot boundary.

## Evidence

Sources read locally: `deeper-guide_totallink_sdk.txt` (TYPE/required/length and
SDK initialization contract) and `deeper-sdk-script.txt` (exact mode API origins,
CPID8, unconditional TOTAL, FRAME behavior). No new provider research/calls.

Receipt root:
`/home/lovelyuk/.hermes/profiles/aebong/cache/long-tasks/greeneat-pc-sdk-frame-receipts/`

- `backend-sdk-RED.log`: prior to route implementation, 52 failed / 1 passed.
- `backend-sdk-GREEN.log`: 53 passed.
- `backend-sdk-affected-GREEN.log`: initial combined run; 175 passed / 1 failed
  because an existing test loaded configuration without synthetic Supabase env.
- `backend-sdk-affected-fixture-GREEN.log`: 176 passed with synthetic `.invalid`
  Supabase URL and fixture keys; all provider/repository I/O mocked.

Runs were serial foreground in the existing cached backend Python environment;
no runtime/service spawn, DB/schema mutation, production files, or live charges.
