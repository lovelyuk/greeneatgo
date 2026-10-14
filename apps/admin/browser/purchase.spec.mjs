// Deterministic mocked I/O ONLY. No real auth, merchant or Kiwoom calls.
import { test, expect } from "@playwright/test";
import { writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, join } from "node:path";
const runtimeErrors = new WeakMap();
test.beforeEach(async ({ context, page }) => {
  const errors = [];
  runtimeErrors.set(page, errors);
  page.on("pageerror", error => errors.push(error.message));
  context.on("page", popup => popup.on("pageerror", error => errors.push(error.message)));
  // Every external request is blocked unless a specific mocked route overrides it.
  await context.route("**/*", (route) =>
    new URL(route.request().url()).origin === "http://127.0.0.1:4175"
      ? route.continue()
      : route.abort(),
  );
});
test.afterEach(async ({ page }) => {
  expect(runtimeErrors.get(page), "uncaught browser or checkout runtime errors").toEqual([]);
});
async function fixture(page, profile = { role: "customer", status: "active" }) {
  const calls = [];
  const user = {
    id: "11111111-1111-4111-8111-111111111111",
    email: "fixture@example.invalid",
    aud: "authenticated",
    role: "authenticated",
    email_confirmed_at: "2026-01-01T00:00:00Z",
  };
  await page.route("**/auth-fixture/auth/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/logout")) return route.fulfill({ status: 204 });
    await route.fulfill({
      json: path.endsWith("/user")
        ? user
        : {
            access_token: "fixture-access",
            refresh_token: "fixture-refresh",
            expires_in: 3600,
            token_type: "bearer",
            user,
          },
    });
  });
  await page.route("**/api-fixture/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(
      "/api-fixture",
      "",
    );
    calls.push({ path, body: route.request().postDataJSON() });
    let data = {};
    if (path === "/me")
      data = {
        user_id: user.id,
        display_name: "테스트 구매자",
        voucher_balance: 3,
        point_balance: 2000,
        account_type: profile.role === "employee" ? "ledger" : "voucher",
        voucher_use_history: [],
        point_transactions: [],
        recent_transactions: [],
        ...profile,
      };
    if (path === "/vouchers/products")
      data = { purchase_mode: "voucher", items: [] };
    if (path === "/coupons")
      data = {
        merchant: { id: "merchant-fixture", name: "테스트 식당" },
        items: [],
        issued: [],
      };
    await route.fulfill({ json: { ok: true, data } });
  });
  return calls;
}
async function restoredRecovery(page) {
  const calls = await fixture(page);
  await catalogFixture(page);
  await page.addInitScript(() => sessionStorage.setItem(
    "greeneat-purchase-pending:11111111-1111-4111-8111-111111111111",
    JSON.stringify({ order_id: "GE-V-recovery-fixture", amount: 72000, mode: "voucher", checkout_started: true }),
  ));
  return calls;
}
const recoveryReady = {
  order_id: "GE-V-recovery-fixture", amount: 72000, status: "ready", recovery_action: "resume",
  checkout_url: `http://127.0.0.1:4175/api-fixture/payments/checkout/${"r".repeat(43)}`,
};
test("recovery restored ordinary order never exposes reopen or enters checkout", async ({ page, context }) => {
  const calls = await restoredRecovery(page);
  let recoveries = 0, entered = 0;
  await page.route("**/api-fixture/payments/recovery?**", route => {
    recoveries++;
    const url = new URL(route.request().url());
    expect(route.request().method()).toBe("GET");
    expect(url.searchParams.get("order_id")).toBe(recoveryReady.order_id);
    expect(url.searchParams.get("amount")).toBe("72000");
    return route.fulfill({ json: { ok: true, data: { ...recoveryReady, recovery_action: "reconcile", checkout_url: null, resumable: false } } });
  });
  await context.route(recoveryReady.checkout_url, route => { entered++; return route.fulfill({ body: "MOCK ONLY" }); });
  await login(page);
  await expect(page.getByRole("button", { name: "기존 결제창 다시 열기" })).toHaveCount(0);
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
  await expect(page.getByRole("alert")).toContainText("관리자에게 거래 확인");
  expect(recoveries).toBe(1); expect(entered).toBe(0);
  expect(context.pages()).toHaveLength(1);
  expect(calls.some(call => call.path.includes("/purchase"))).toBe(false);
});
test('profile GET failure ends loading and retries only profile read', async ({ page }) => {
  const calls = await fixture(page);
  let reads = 0;
  await page.route('**/api-fixture/me', route => {
    reads++;
    return route.fulfill({ status: 503, json: { detail: { message: 'synthetic profile unavailable' } } });
  });
  await login(page);
  await expect(page.getByRole('alert')).toContainText('synthetic profile unavailable');
  await expect(page.getByText('계정 확인 중…', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '계정 다시 확인' }).click();
  await expect.poll(() => reads).toBe(2);
  expect(calls.some(call => call.body)).toBe(false);
});
test('profile mismatched owner fails closed before purchase dashboard', async ({ page }) => {
  await fixture(page, { role: 'customer', status: 'active', user_id: '22222222-2222-4222-8222-222222222222' });
  await login(page);
  await expect(page.getByRole('alert')).toContainText('계정 소유자');
  await expect(page.getByRole('navigation', { name: '구매자 탭' })).toHaveCount(0);
});
function producer(command, payload) {
  return JSON.parse(execFileSync(process.env.FINALIZE_FIXTURE_PYTHON,
    ['browser/finalization-producer.py', command, ...(payload ? [JSON.stringify(payload)] : [])],
    { encoding: 'utf8', env: { ...process.env, ENV: 'test', SUPABASE_URL: 'https://fixture.invalid',
      SUPABASE_ANON_KEY: 'synthetic', SUPABASE_SERVICE_ROLE_KEY: 'synthetic' } }));
}
test('real router PG closure lifecycle retains audit and explicit purchase creates new ID after reload', async ({ page, context }) => {
  test.skip(!process.env.FINALIZE_FIXTURE_PYTHON || !process.env.FINALIZE_TEST_DATABASE_URL, 'requires isolated local PostgreSQL producer adapter');
  const seed = producer('init');
  await fixture(page); await publishedLegal(page);
  await page.addInitScript(seed => {
    if (!sessionStorage.getItem('synthetic-closure-reload')) sessionStorage.setItem(`greeneat-purchase-pending:${seed.owner}`,
      JSON.stringify({ order_id: seed.order_id, amount: seed.amount, mode: 'voucher', checkout_started: true }));
  }, seed);
  await page.route('**/api-fixture/coupons', route => route.fulfill({ json: { ok: true, data: {
    merchant: { id: '33333333-3333-4333-8333-333333333333', name: 'Synthetic merchant' }, items: [], issued: [] } } }));
  const writes = [], recoveries = [];
  for (const glob of ['**/api-fixture/vouchers/products', '**/api-fixture/vouchers/quote', '**/api-fixture/vouchers/purchase', '**/api-fixture/payments/recovery?**'])
    await page.route(glob, route => {
      const url = new URL(route.request().url());
      const path = url.pathname.replace('/api-fixture', '') + url.search;
      const result = producer('request', { method: route.request().method(), path, body: route.request().postDataJSON() });
      if (route.request().method() === 'POST') writes.push({ path, ...result });
      if (path.startsWith('/payments/recovery?')) recoveries.push(result);
      return route.fulfill({ status: result.status, json: result.json });
    });
  await context.route('**/api-fixture/payments/checkout/**', route => route.fulfill({ body: 'SYNTHETIC ONLY: provider entry deliberately not executed' }));
  await login(page);
  await page.getByRole('button', { name: 'Synthetic ticket 선택' }).click();
  await page.getByRole('button', { name: '견적 확인', exact: true }).click();
  await expect(page.getByText('최종 결제', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '저장된 주문 상태 확인' }).click();
  await expect(page.getByRole('alert')).toContainText('관리자에게 거래 확인');
  const body = { user_id: seed.owner, amount: seed.amount, outcome: 'failed', source_sha256: 'b'.repeat(64),
    source_reference: 'synthetic restricted evidence document', attempts: [{ transaction_id: 'synthetic-attempt', outcome: 'failed' }],
    authority: 'trusted_provider_irreversible_closure', complete_attempt_coverage: true, irreversible_no_future_approval: true,
    provider_closure_reference: 'synthetic irreversible all-attempts attestation', dry_run: true };
  const path = `/admin/platform/payment-orders/${seed.internal_id}/review`;
  const dry = producer('request', { method: 'POST', token: 'fixture-operator', path, body });
  expect(dry.status).toBe(200); expect(dry.json.data.closed).toBe(false); expect(dry.json.data.eligible).toBe(true);
  const applied = producer('request', { method: 'POST', token: 'fixture-operator', path, body: { ...body, dry_run: false } });
  expect(applied.status).toBe(200); expect(applied.json.data.closed).toBe(true);
  await page.getByRole('button', { name: '저장된 주문 상태 확인' }).click();
  await expect(page.getByRole('heading', { name: '결제 종료 확인' })).toBeVisible();
  await expect(page.getByText('최종 결제', { exact: true })).toHaveCount(0);
  expect(await page.evaluate(owner => sessionStorage.getItem(`greeneat-purchase-pending:${owner}`), seed.owner)).toBe(null);
  expect(writes.filter(w => w.path === '/vouchers/purchase')).toHaveLength(0);
  // Remove the seed initializer before reload: a real pending intent is not reinserted.
  await page.evaluate(() => { sessionStorage.setItem('synthetic-closure-reload', 'yes'); });
  await page.getByRole('button', { name: '새 견적으로 구매 준비' }).click();
  await expect(page.getByRole('button', { name: '구매하기', exact: true })).toHaveCount(0);
  await page.reload();
  await page.getByRole('navigation').getByRole('button', { name: '구매', exact: true }).click();
  await page.getByRole('button', { name: 'Synthetic ticket 선택' }).click();
  await page.getByRole('button', { name: '견적 확인', exact: true }).click();
  await expect(page.getByLabel('구매 조건 확인')).not.toBeChecked();
  await page.getByLabel('구매 조건 확인').check();
  await page.getByRole('button', { name: '구매하기', exact: true }).click();
  await expect.poll(() => writes.filter(w => w.path === '/vouchers/purchase').length).toBe(1);
  const fresh = writes.find(w => w.path === '/vouchers/purchase').json.data;
  expect(fresh.order_id).not.toBe(seed.order_id);
  const audit = producer('audit');
  expect(audit.closures).toHaveLength(1); expect(audit.reviews.count).toBe(1);
  expect(audit.orders).toHaveLength(2);
  expect(audit.orders.find(o => o.order_id === seed.order_id).status).toBe('failed');
  expect(audit.orders.find(o => o.order_id === fresh.order_id).status).toBe('ready');
  expect(recoveries.map(r => r.json.data.recovery_action)).toEqual(['reconcile', 'closed']);
  if (process.env.PURCHASE_RECEIPTS) writeFileSync(join(process.env.PURCHASE_RECEIPTS, 'frontend-router-pg-proof.json'),
    JSON.stringify({ synthetic_only: true, seed, dry, applied, recoveries, fresh_order_id: fresh.order_id, audit,
      provider_executed: false, source: 'real FastAPI routers and migrated PostgreSQL RPC' }, null, 2));
});
const verifiedClosure = {
  ...recoveryReady, user_id: '11111111-1111-4111-8111-111111111111', status: 'canceled',
  recovery_action: 'closed', resumable: false, checkout_url: null, completion: null,
  closure: { id: '33333333-3333-4333-8333-333333333333', evidence_sha256: 'a'.repeat(64),
    scope: 'order', finality: 'verified', outcome: 'canceled', closed_at: '2026-10-14T10:00:00+09:00' },
};
test('verified closed recovery releases only matching intent and requires fresh quote', async ({ page, context }) => {
  const calls = await restoredRecovery(page);
  await page.route('**/api-fixture/payments/recovery?**', route => route.fulfill({ json: { ok: true, data: verifiedClosure } }));
  await login(page);
  await page.evaluate(() => sessionStorage.setItem('greeneat-purchase-pending:other-owner', 'keep-other-owner'));
  await page.getByRole('button', { name: '저장된 주문 상태 확인' }).click();
  await expect(page.getByRole('heading', { name: '결제 종료 확인' })).toBeVisible();
  expect(await page.evaluate(key => sessionStorage.getItem(key), 'greeneat-purchase-pending:11111111-1111-4111-8111-111111111111')).toBe(null);
  expect(await page.evaluate(() => sessionStorage.getItem('greeneat-purchase-pending:other-owner'))).toBe('keep-other-owner');
  await page.getByRole('button', { name: '새 견적으로 구매 준비' }).click();
  await expect(page.getByRole('button', { name: '구매하기', exact: true })).toHaveCount(0);
  expect(calls.some(call => call.path.includes('/purchase'))).toBe(false);
  expect(context.pages()).toHaveLength(1);
});
for (const failure of ['owner', 'missing-owner', 'id', 'hash', 'scope', 'finality', 'outcome', 'timestamp', 'resumable', 'url', 'completion'])
  test(`closed recovery rejects malformed ${failure}`, async ({ page, context }) => {
    const calls = await restoredRecovery(page);
    const data = structuredClone(verifiedClosure);
    if (failure === 'owner') data.user_id = 'other-owner';
    if (failure === 'missing-owner') delete data.user_id;
    if (failure === 'id') data.closure.id = 'not-uuid';
    if (failure === 'hash') data.closure.evidence_sha256 = 'A'.repeat(64);
    if (failure === 'scope') data.closure.scope = 'attempt';
    if (failure === 'finality') data.closure.finality = 'unknown';
    if (failure === 'outcome') data.closure.outcome = 'failed';
    if (failure === 'timestamp') data.closure.closed_at = '2026-02-30T00:00:00Z';
    if (failure === 'resumable') delete data.resumable;
    if (failure === 'url') data.checkout_url = 'https://fixture.invalid';
    if (failure === 'completion') data.completion = {};
    await page.route('**/api-fixture/payments/recovery?**', route => route.fulfill({ json: { ok: true, data } }));
    await login(page);
    await page.getByRole('button', { name: '저장된 주문 상태 확인' }).click();
    await expect(page.getByRole('alert')).toContainText('저장된 주문을 유지');
    await expect(page.getByRole('heading', { name: '진행 중인 결제' })).toBeVisible();
    expect(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).order_id, recoveryStorageKey)).toBe(recoveryReady.order_id);
    expect(calls.some(c => c.path.includes('/purchase'))).toBe(false); expect(context.pages()).toHaveLength(1);
  });
for (const failure of ['getItem', 'removeItem', 'new-intent']) test(`closed recovery fails closed on storage ${failure}`, async ({ page }) => {
  await restoredRecovery(page);
  let release, requested;
  const started = new Promise(resolve => requested = resolve), barrier = new Promise(resolve => release = resolve);
  await page.route('**/api-fixture/payments/recovery?**', async route => { requested(); await barrier; await route.fulfill({ json: { ok: true, data: verifiedClosure } }); });
  await login(page); await page.getByRole('button', { name: '저장된 주문 상태 확인' }).click(); await started;
  await page.evaluate(({ failure, key }) => {
    if (failure === 'new-intent') sessionStorage.setItem(key, JSON.stringify({ order_id: 'GE-newer-intent', amount: 72000, mode: 'voucher' }));
    else { const original = Storage.prototype[failure]; Storage.prototype[failure] = function(key, ...args) {
      if (key.startsWith('greeneat-purchase-pending:')) throw new Error('synthetic storage unavailable');
      return original.call(this, key, ...args);
    }; }
  }, { failure, key: recoveryStorageKey });
  release();
  await expect(page.getByRole('alert')).toContainText(failure === 'removeItem' ? '지우지 못했어요' : '저장된 주문을 유지');
  await expect(page.getByRole('heading', { name: '진행 중인 결제' })).toBeVisible();
  await expect(page.getByRole('button', { name: '새 견적으로 구매 준비' })).toHaveCount(0);
});
for (const destination of ['logout', 'other-owner', 'ABA']) test(`closed recovery stale ${destination} cannot clear intent`, async ({ page }) => {
  await restoredRecovery(page);
  let release, requested;
  const started = new Promise(resolve => requested = resolve), barrier = new Promise(resolve => release = resolve);
  await page.route('**/api-fixture/payments/recovery?**', async route => { requested(); await barrier; await route.fulfill({ json: { ok: true, data: verifiedClosure } }); });
  await login(page); await page.getByRole('button', { name: '저장된 주문 상태 확인' }).click(); await started;
  const signOut = async () => {
    await page.getByRole('navigation').getByRole('button', { name: '내정보', exact: true }).click();
    await page.getByRole('button', { name: '로그아웃', exact: true }).click();
    await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeVisible();
    await expect.poll(() => page.evaluate(() => Object.keys(localStorage).filter(key => key.includes('auth-token')).length)).toBe(0);
  };
  const authenticate = async () => {
    await page.getByLabel('이메일', { exact: true }).fill('fixture@example.invalid');
    await page.getByLabel('비밀번호', { exact: true }).fill('mocked-password-only');
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    await expect(page.getByRole('navigation', { name: '구매자 탭' })).toBeVisible();
  };
  await signOut();
  if (destination !== 'logout') {
    const id = '22222222-2222-4222-8222-222222222222';
    await page.route('**/auth-fixture/auth/v1/**', route => new URL(route.request().url()).pathname.endsWith('/logout')
      ? route.fulfill({ status: 204 }) : route.fulfill({ json: { access_token: 'fixture-B', refresh_token: 'fixture-B-refresh', expires_in: 3600, token_type: 'bearer', user: { id, email: 'fixture@example.invalid', aud: 'authenticated', role: 'authenticated' } } }));
    await page.route('**/api-fixture/me', route => route.fulfill({ json: { ok: true, data: { user_id: id, role: 'customer', status: 'active', voucher_balance: 0 } } }));
    await authenticate();
    if (destination === 'ABA') {
      await signOut();
      await page.unroute('**/auth-fixture/auth/v1/**'); await page.unroute('**/api-fixture/me');
      await fixture(page); await authenticate();
    }
  }
  release();
  // A subsequent authenticated GET fences completion of the released response.
  if (destination !== 'logout') {
    await page.getByRole('navigation').getByRole('button', { name: '홈', exact: true }).click();
    await page.getByRole('button', { name: '새로고침', exact: true }).click();
    await expect(page.getByRole('button', { name: '새로고침', exact: true })).toBeEnabled();
  }
  await expect(page.getByRole('heading', { name: '결제 종료 확인' })).toHaveCount(0);
  expect(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).order_id, recoveryStorageKey)).toBe(recoveryReady.order_id);
});
const recoveryStorageKey = "greeneat-purchase-pending:11111111-1111-4111-8111-111111111111";
const recoveryCompletion = {
  order_id: recoveryReady.order_id, amount: 72000, status: "done", issued_count: 11,
  merchant_name: "테스트 식당", product_name: "복구한 식권",
  payment: { method: "CARD", method_label: "카드", approved_at: "2026-01-01T00:00:00Z" },
  receipts: { sales_slip_url: "https://agenttest.kiwoompay.co.kr/common/PayInfoPrintDirectCard.jsp?DAOUTRX=fixture&STATUS=A" },
};
test("recovery status works when window.open is forbidden", async ({ page }) => {
  const calls = await restoredRecovery(page);
  await page.route("**/api-fixture/payments/recovery?**", route => route.fulfill({ json: { ok: true, data: { ...recoveryReady, recovery_action: "reconcile", checkout_url: null } } }));
  await login(page);
  await page.evaluate(() => { window.open = () => { throw new Error("Recovery must not open PG"); }; });
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
  await expect(page.getByRole("alert")).toContainText("관리자에게 거래 확인");
  expect(calls.some(call => call.path.includes("purchase"))).toBe(false);
  expect(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).order_id, recoveryStorageKey)).toBe(recoveryReady.order_id);
});
for (const reopen of [false]) test(`recovery done exact completion via ${reopen ? "reopen" : "status"} shows server receipts`, async ({ page, context }) => {
  await restoredRecovery(page);
  await page.route("**/api-fixture/payments/recovery?**", route => route.fulfill({ json: { ok: true, data: { ...recoveryReady, status: "done", recovery_action: "complete", checkout_url: null, completion: recoveryCompletion } } }));
  await login(page);
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
  await expect(page.getByRole("heading", { name: "결제 완료" })).toBeVisible();
  await expect(page.getByText("복구한 식권", { exact: false })).toBeVisible();
  await expect(page.getByText("발급 식권 11장")).toBeVisible();
  await expect(page.getByRole("link", { name: "매출전표" })).toHaveAttribute("href", recoveryCompletion.receipts.sales_slip_url);
  expect(await page.evaluate(key => sessionStorage.getItem(key), recoveryStorageKey)).toBe(null);
  await expect.poll(() => context.pages().length).toBe(1);
});
for (const status of ["ready", "failed", "canceled", "refund_processing", "refunded", "unknown"]) test(`recovery reconcile ${status} never releases order or offers new purchase`, async ({ page, context }) => {
  const calls = await restoredRecovery(page);
  await page.route("**/api-fixture/payments/recovery?**", route => route.fulfill({ json: { ok: true, data: { ...recoveryReady, status, recovery_action: "reconcile", checkout_url: null } } }));
  await login(page);
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
  await expect(page.getByRole("alert")).toContainText("관리자에게 거래 확인");
  await expect(page.getByRole("heading", { name: "진행 중인 결제" })).toBeVisible();
  await expect(page.getByRole("button", { name: "구매하기", exact: true })).toHaveCount(0);
  expect(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).order_id, recoveryStorageKey)).toBe(recoveryReady.order_id);
  expect(calls.some(call => call.path.includes("/purchase"))).toBe(false);
  await expect.poll(() => context.pages().length).toBe(1);
});
for (const failure of ["401", "502", "404", "network", "malformed", "amount", "order", "unsafe-url", "resume", "resumable", "status-action", "done-order", "done-amount"]) test(`recovery error ${failure} keeps exact order locked`, async ({ page, context }) => {
  await restoredRecovery(page);
  await page.route("**/api-fixture/payments/recovery?**", route => {
    if (failure === "network") return route.abort("failed");
    if (["401", "502", "404"].includes(failure)) return route.fulfill({ status: Number(failure), json: { detail: { code: "FIXTURE_ERROR", message: "MOCK ONLY recovery unavailable" } } });
    let data = { ...recoveryReady };
    if (failure === "resumable") data = { ...data, recovery_action: "reconcile", checkout_url: null, resumable: true };
    if (failure === "malformed") data = null;
    if (failure === "amount") data.amount++;
    if (failure === "order") data.order_id = "GE-V-other-fixture";
    if (failure === "unsafe-url") data.checkout_url = "https://evil.invalid/pay";
    if (failure === "status-action") data.status = "canceled";
    if (failure.startsWith("done-")) data = { ...data, status: "done", recovery_action: "complete", checkout_url: null, completion: { ...recoveryCompletion, ...(failure === "done-order" ? { order_id: "GE-V-other-fixture" } : { amount: 1 }) } };
    return route.fulfill({ json: { ok: true, data } });
  });
  await login(page);
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
  await expect(page.getByRole("alert")).toContainText("저장된 주문을 유지");
  await expect(page.getByRole("heading", { name: "결제 완료" })).toHaveCount(0);
  expect(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).order_id, recoveryStorageKey)).toBe(recoveryReady.order_id);
  await expect.poll(() => context.pages().length).toBe(1);
});
test("recovery status ready gives pending guidance without automatic popup", async ({ page, context }) => {
  await restoredRecovery(page);
  await page.route("**/api-fixture/payments/recovery?**", route => route.fulfill({ json: { ok: true, data: { ...recoveryReady, recovery_action: "reconcile", checkout_url: null } } }));
  await login(page);
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
  await expect(page.getByRole("alert")).toContainText("관리자에게 거래 확인");
  expect(context.pages()).toHaveLength(1);
});
test("recovery duplicate click issues one bounded GET and zero popups", async ({ page, context }) => {
  await restoredRecovery(page);
  let count = 0;
  await page.route("**/api-fixture/payments/recovery?**", route => { count++; return route.fulfill({ json: { ok: true, data: { ...recoveryReady, recovery_action: "reconcile", checkout_url: null } } }); });
  await login(page);
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).evaluate(button => { button.click(); button.click(); });
  await expect(page.getByRole("alert")).toContainText("관리자에게 거래 확인");
  expect(count).toBe(1);
  await expect.poll(() => context.pages().length).toBe(1);
});
test("recovery late response after logout and new account cannot navigate, refresh or clear old lock", async ({ page, context }) => {
  await restoredRecovery(page);
  let release, requested;
  const started = new Promise(resolve => requested = resolve), barrier = new Promise(resolve => release = resolve);
  await page.route("**/api-fixture/payments/recovery?**", async route => { requested(); await barrier; await route.fulfill({ json: { ok: true, data: { ...recoveryReady, status: "done", recovery_action: "complete", checkout_url: null, completion: recoveryCompletion } } }); });
  await login(page);
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
  await started;
  await page.getByRole("navigation").getByRole("button", { name: "내정보", exact: true }).click();
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(page.getByRole("button", { name: "로그인", exact: true })).toBeVisible();
  // New account via saved-code auth fixtures, never live auth.
  const id = "22222222-2222-4222-8222-222222222222";
  const user = { id, email: "fixture@example.invalid", aud: "authenticated", role: "authenticated" };
  await page.route("**/auth-fixture/auth/v1/**", route => route.fulfill({ json: { access_token: "fixture-second", refresh_token: "fixture-second-refresh", expires_in: 3600, token_type: "bearer", user } }));
  let reads = 0;
  await page.route("**/api-fixture/me", route => { reads++; return route.fulfill({ json: { ok: true, data: { user_id: id, display_name: "다른 구매자", role: "customer", status: "active", voucher_balance: 0, point_balance: 0 } } }); });
  await login(page);
  await expect(page.getByRole("heading", { name: "진행 중인 결제" })).toHaveCount(0);
  release();
  // Fence: a new-account status read finishes after the old response is released.
  await page.getByRole("navigation").getByRole("button", { name: "홈", exact: true }).click();
  await page.getByRole("button", { name: "새로고침", exact: true }).click();
  await expect.poll(() => reads).toBe(2);
  expect(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).order_id, recoveryStorageKey)).toBe(recoveryReady.order_id);
  await expect(page.getByRole("heading", { name: "결제 완료" })).toHaveCount(0);
  await expect.poll(() => context.pages().length).toBe(1);
});
test("recovery storage write failure before purchase refuses order API", async ({ page, context }) => {
  const calls = await fixture(page);
  await publishedLegal(page); await catalogFixture(page); await quoteFixture(page);
  await selectQuote(page); await page.getByLabel("구매 조건 확인").check();
  await page.evaluate(() => { const original = Storage.prototype.setItem; Storage.prototype.setItem = function(key, value) { if (key.startsWith("greeneat-purchase-pending:")) throw new Error("MOCK storage write failure"); return original.call(this, key, value); }; });
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
  await expect(page.getByRole("heading", { name: "주문 상태 확인 필요" })).toBeVisible();
  expect(calls.some(call => call.path.includes("/purchase"))).toBe(false);
  await expect.poll(() => context.pages().length).toBe(1);
});
test("recovery known purchase order survives storage write failure and tab remount", async ({ page, context }) => {
  await fixture(page); await publishedLegal(page); await catalogFixture(page); await quoteFixture(page);
  let purchases = 0;
  await page.route("**/api-fixture/vouchers/purchase", route => { purchases++; return route.fulfill({ json: { ok: true, data: { order_id: recoveryReady.order_id, amount: 72000, product_id: product.id, gross_amount: 72000, coupon_discount_amount: 0, point_amount: 0, checkout_url: recoveryReady.checkout_url } } }); });
  await page.route("**/api-fixture/payments/recovery?**", route => route.fulfill({ json: { ok: true, data: { ...recoveryReady, status: "done", recovery_action: "complete", checkout_url: null, completion: recoveryCompletion } } }));
  await selectQuote(page); await page.getByLabel("구매 조건 확인").check();
  await page.evaluate(() => { const original = Storage.prototype.setItem; let writes = 0; Storage.prototype.setItem = function(key, value) { if (key.startsWith("greeneat-purchase-pending:") && ++writes > 1) throw new Error("MOCK storage write failure"); return original.call(this, key, value); }; });
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
  await expect(page.getByText(`주문 ${recoveryReady.order_id}`, { exact: true })).toBeVisible();
  await page.getByRole("navigation").getByRole("button", { name: "홈", exact: true }).click();
  await page.getByRole("navigation").getByRole("button", { name: "구매", exact: true }).click();
  await expect(page.getByText(`주문 ${recoveryReady.order_id}`, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
  await expect(page.getByRole("heading", { name: "결제 완료" })).toBeVisible();
  expect(purchases).toBe(1);
  await expect.poll(() => context.pages().length).toBe(1);
});
test("recovery completion survives storage removal failure but refuses next purchase", async ({ page }) => {
  await restoredRecovery(page);
  await page.route("**/api-fixture/payments/recovery?**", route => route.fulfill({ json: { ok: true, data: { ...recoveryReady, status: "done", recovery_action: "complete", checkout_url: null, completion: recoveryCompletion } } }));
  await login(page);
  await page.evaluate(() => { const original = Storage.prototype.removeItem; Storage.prototype.removeItem = function(key) { if (key.startsWith("greeneat-purchase-pending:")) throw new Error("MOCK storage removal failure"); return original.call(this, key); }; });
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
  await expect(page.getByRole("heading", { name: "결제 완료" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("저장된 주문을 지우지 못했어요");
  await expect(page.getByRole("button", { name: "다른 식권 구매" })).toHaveCount(0);
  expect(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).order_id, recoveryStorageKey)).toBe(recoveryReady.order_id);
});
test("recovery storage read failure remains blocked without order API", async ({ page }) => {
  const calls = await fixture(page); await catalogFixture(page);
  await page.addInitScript(() => { const original = Storage.prototype.getItem; Storage.prototype.getItem = function(key) { if (key.startsWith("greeneat-purchase-pending:")) throw new Error("MOCK read failure"); return original.call(this, key); }; });
  await login(page);
  await expect(page.getByRole("heading", { name: "주문 상태 확인 필요" })).toBeVisible();
  expect(calls.some(call => call.path.includes("purchase") || call.path.includes("recovery"))).toBe(false);
});
test("recovery stale purchase pricing stays blocked across tabs and reload", async ({ page, context }) => {
  await fixture(page); await publishedLegal(page); await catalogFixture(page); await quoteFixture(page);
  let entered = 0, purchases = 0, recoveryCalls = 0;
  await context.route("**/api-fixture/payments/checkout/**", route => { entered++; return route.fulfill({ body: "MOCK ONLY" }); });
  await page.route("**/api-fixture/vouchers/purchase", route => { purchases++; return route.fulfill({ json: { ok: true, data: { order_id: recoveryReady.order_id, product_id: product.id, amount: 73000, gross_amount: 73000, coupon_discount_amount: 0, point_amount: 0, checkout_url: recoveryReady.checkout_url } } }); });
  await page.route("**/api-fixture/payments/recovery?**", route => { recoveryCalls++; return route.fulfill({ json: { ok: true, data: { ...recoveryReady, amount: 73000 } } }); });
  await selectQuote(page); await page.getByLabel("구매 조건 확인").check();
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
  await expect(page.getByText(`주문 ${recoveryReady.order_id}`, { exact: true })).toBeVisible();
  await page.getByRole("navigation").getByRole("button", { name: "홈", exact: true }).click();
  await page.getByRole("navigation").getByRole("button", { name: "구매", exact: true }).click();
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "저장된 주문을 유지" })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "저장된 주문을 유지" })).toBeVisible();
  expect(entered).toBe(0); expect(recoveryCalls).toBe(2); expect(purchases).toBe(1);
  await expect.poll(() => context.pages().length).toBe(1);
});
for (const started of [false, undefined]) test(`recovery legacy unaccepted price ${started} cannot reopen amount-only order`, async ({ page, context }) => {
  const calls = await fixture(page);
  await catalogFixture(page);
  await page.addInitScript(({ key, saved }) => sessionStorage.setItem(key, JSON.stringify(saved)), {
    key: recoveryStorageKey,
    saved: { order_id: recoveryReady.order_id, amount: 72000, mode: "voucher", checkout_started: started },
  });
  let entered = 0, recoveries = 0;
  await page.route("**/api-fixture/payments/recovery?**", route => {
    recoveries++;
    return route.fulfill({ json: { ok: true, data: recoveryReady } });
  });
  await context.route(recoveryReady.checkout_url, route => { entered++; return route.fulfill({ body: "MOCK ONLY" }); });
  await login(page);
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
  await expect(page.getByRole("alert")).toContainText("저장된 주문을 유지");
  await expect(page.getByText(`주문 ${recoveryReady.order_id}`, { exact: true })).toBeVisible();
  expect(entered).toBe(0);
  expect(recoveries).toBe(1);
  expect(calls.some(call => call.path.includes("/purchase"))).toBe(false);
  expect(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).order_id, recoveryStorageKey)).toBe(recoveryReady.order_id);
  expect(context.pages()).toHaveLength(1);
});
test("recovery accepted pricing belongs to saved order, not a different selected product", async ({ page, context }) => {
  await fixture(page); await publishedLegal(page); await catalogFixture(page); await quoteFixture(page);
  await page.addInitScript(({ key, saved }) => sessionStorage.setItem(key, JSON.stringify(saved)), {
    key: recoveryStorageKey,
    saved: { order_id: recoveryReady.order_id, amount: 72000, mode: "voucher", checkout_started: true,
      product_id: "previous-product-fixture", resume_allowed: true,
      accepted_pricing: { product_id: "previous-product-fixture", payment_amount: 72000, gross_amount: 73000, coupon_discount_amount: 1000, point_amount: 0 },
      server_pricing: { payment_amount: 72000, gross_amount: 73000, coupon_discount_amount: 1000, point_amount: 0 } },
  });
  let entered = 0;
  await page.route("**/api-fixture/payments/recovery?**", route => route.fulfill({ json: { ok: true, data: recoveryReady } }));
  await context.route(recoveryReady.checkout_url, route => { entered++; return route.fulfill({ body: "MOCK ONLY" }); });
  await selectQuote(page);
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
  await expect(page.getByRole("alert")).toContainText("저장된 주문을 유지");
  expect(entered).toBe(0);
  const saved = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)), recoveryStorageKey);
  expect(saved.accepted_pricing.product_id).toBe("previous-product-fixture");
  expect(saved.accepted_pricing.coupon_discount_amount).toBe(1000);
});
test("recovery storage write failure refuses navigation but preserves known restored order", async ({ page, context }) => {
  await restoredRecovery(page);
  let entered = 0;
  await page.route("**/api-fixture/payments/recovery?**", route => route.fulfill({ json: { ok: true, data: recoveryReady } }));
  await context.route(recoveryReady.checkout_url, route => { entered++; return route.fulfill({ body: "MOCK ONLY" }); });
  await login(page);
  await page.evaluate(() => { const original = Storage.prototype.setItem; Storage.prototype.setItem = function(key, value) { if (key.startsWith("greeneat-purchase-pending:")) throw new Error("MOCK storage write failure"); return original.call(this, key, value); }; });
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
  await expect(page.getByRole("alert")).toContainText("저장된 주문을 유지");
  await expect(page.getByText(`주문 ${recoveryReady.order_id}`, { exact: true })).toBeVisible();
  expect(entered).toBe(0);
  await expect.poll(() => context.pages().length).toBe(1);
});
test("recovery never opens popup before delayed authenticated GET returns", async ({ page, context }) => {
  await restoredRecovery(page);
  let release, requested;
  const started = new Promise(resolve => requested = resolve), barrier = new Promise(resolve => release = resolve);
  await page.route("**/api-fixture/payments/recovery?**", async route => { requested(); await barrier; await route.fulfill({ json: { ok: true, data: { ...recoveryReady, recovery_action: "reconcile", checkout_url: null } } }); });
  await login(page);
  await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
  await started;
  expect(context.pages()).toHaveLength(1);
  await expect(page.getByRole("button", { name: "기존 결제창 다시 열기" })).toHaveCount(0);
  release();
  await expect(page.getByRole("alert")).toContainText("관리자에게 거래 확인");
  await expect.poll(() => context.pages().length).toBe(1);
});
async function publishedLegal(page) {
  await page.route("**/terms.html", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<h1>이용약관</h1><p>MOCK FIXTURE ONLY 시행일 2026.01.01 테스트 식당 사업자등록번호 000-00-00000 대표자 테스트 주소 테스트 연락처 fixture@example.invalid 결제대행 키움페이</p>",
    }),
  );
  await page.route("**/privacy.html", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<h1>개인정보 처리방침</h1><p>MOCK FIXTURE ONLY 개인정보 보호책임자 테스트 담당</p>",
    }),
  );
}
async function login(page, tab = "구매") {
  await page.goto("/shop");
  await page
    .getByLabel("이메일", { exact: true })
    .fill("fixture@example.invalid");
  await page
    .getByLabel("비밀번호", { exact: true })
    .fill("mocked-password-only");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  const nav = page.getByRole("navigation", { name: "구매자 탭" });
  if (await nav.waitFor({ state: "visible", timeout: 1000 }).then(() => true).catch(() => false))
    await nav.getByRole("button", { name: tab, exact: true }).click();
}
const product = {
  id: "package-fixture",
  name: "테스트 10+1 식권",
  voucher_count: 10,
  bonus_count: 1,
  total_count: 11,
  unit_price: 8000,
  discount_rate: 10,
  sale_price: 72000,
  kiwoom_pay_method: "TOTAL",
  is_event: true,
  event_end_at: "2026-12-31T00:00:00Z",
};
async function catalogFixture(page, mode = "voucher") {
  await page.route("**/api-fixture/vouchers/products", (route) =>
    route.fulfill({
      json: {
        ok: true,
        data: {
          purchase_mode: mode,
          items: [
            mode === "subsidized"
              ? {
                  ...product,
                  employee_pay_amount: 42000,
                  per_voucher_company_subsidy_amount: 2000,
                  per_voucher_restaurant_subsidy_amount: 1000,
                  total_company_subsidy_amount: 20000,
                  total_restaurant_subsidy_amount: 10000,
                }
              : product,
          ],
        },
      },
    }),
  );
  await page.route("**/api-fixture/coupons", (route) =>
    route.fulfill({
      json: {
        ok: true,
        data: {
          merchant: { id: "merchant-fixture", name: "테스트 식당" },
          items: [
            {
              id: "coupon-fixture",
              name: "테스트 할인",
              discount_type: "fixed",
              discount_value: 1000,
            },
          ],
          issued: [],
        },
      },
    }),
  );
}
async function quoteFixture(
  page,
  mode = "voucher",
  amount = 72000,
  pointAmount = 0,
  discount = 0,
) {
  await page.route("**/api-fixture/vouchers/quote", (route) =>
    route.fulfill({
      json: {
        ok: true,
        data: {
          merchant_id: "merchant-fixture",
          merchant_name: "테스트 식당",
          product_id: product.id,
          purchase_mode: mode,
          gross_amount: amount + pointAmount + discount,
          coupon_discount_amount: discount,
          point_amount: pointAmount,
          payment_amount: amount,
        },
      },
    }),
  );
}
async function selectQuote(page) {
  await login(page);
  await page.getByRole("button", { name: "테스트 10+1 식권 선택" }).click();
  await page.getByRole("button", { name: "견적 확인" }).click();
}
test("loaded empty purchaser catalog displays explicit empty state", async ({ page }) => {
  await fixture(page);
  await login(page);
  await expect(page.getByText("현재 판매 중인 식권 상품이 없어요.")).toBeVisible();
  await expect(page.getByText("상품 확인 중…")).toHaveCount(0);
});
test("failed catalog read shows recoverable error instead of indefinite loading", async ({ page }) => {
  await fixture(page);
  await page.route("**/api-fixture/vouchers/products", route => route.fulfill({ status: 503, json: { detail: { code: "UNAVAILABLE", message: "fixture catalog unavailable" } } }));
  await login(page);
  await expect(page.getByRole("alert")).toContainText("fixture catalog unavailable");
  await expect(page.getByText("상품 확인 중…")).toHaveCount(0);
  await page.getByRole("navigation").getByRole("button", { name: "홈", exact: true }).click();
  await expect(page.getByRole("button", { name: "새로고침", exact: true })).toBeEnabled();
});
test('admin route retains its login and does not load purchaser bundle until shop navigation', async ({ page }) => {
  await fixture(page); const purchaserRequests = []; page.on('request', request => { if (/\/assets\/PurchaseApp-[^/]+\.js$/.test(new URL(request.url()).pathname)) purchaserRequests.push(request.url()); });
  await page.goto('/'); await expect(page.getByRole('heading', { name: '관리자 로그인' })).toBeVisible(); expect(purchaserRequests).toHaveLength(0);
  await page.goto('/shop'); await expect(page.getByRole('heading', { name: '식권 구매' })).toBeVisible(); expect(purchaserRequests).toHaveLength(1);
});
test("mixed employee issued-coupon purchase follows API form and remains pending on confirm error until server approves", async ({
  page,
  context,
}) => {
  await fixture(page, {
    role: "employee",
    status: "active",
    company_id: "company-fixture",
  });
  await publishedLegal(page);
  await catalogFixture(page, "subsidized");
  await quoteFixture(page, "subsidized", 39000, 2000, 1000);
  await page.route("**/api-fixture/coupons", (route) =>
    route.fulfill({
      json: {
        ok: true,
        data: {
          merchant: { id: "merchant-fixture", name: "테스트 식당" },
          items: [],
          issued: [
            {
              id: "issued-fixture",
              coupon_id: "coupon-fixture",
              coupon_snapshot: { name: "테스트 보유쿠폰" },
              valid_until: "2026-12-31T00:00:00Z",
              status: "available",
            },
          ],
        },
      },
    }),
  );
  let purchased,
    confirmed,
    checkoutEntered = 0;
  const token = "m".repeat(43);
  await page.route(
    "**/api-fixture/vouchers/purchase-subsidized",
    async (route) => {
      purchased = route.request().postDataJSON();
      await route.fulfill({
        json: {
          ok: true,
          data: {
            order_id: "GE-S-mixed-fixture",
            product_id: product.id,
            amount: 39000,
            gross_amount: 42000,
            coupon_discount_amount: 1000,
            point_amount: 2000,
            checkout_url: `http://127.0.0.1:4175/api-fixture/payments/checkout/${token}`,
          },
        },
      });
    },
  );
  await context.route(`**/api-fixture/payments/checkout/${token}`, (route) => {
    checkoutEntered++;
    return route.fulfill({
      contentType: "text/html",
      body: "<h1>MOCK SERVER CHECKOUT ONLY</h1>",
    });
  });
  await page.route("**/api-fixture/payments/confirm", (route) =>
    route.fulfill({
      status: 502,
      json: {
        detail: {
          code: "SUPABASE_ERROR",
          message: "MOCK ONLY confirm failure",
        },
      },
    }),
  );
  await login(page);
  await page.getByRole("button", { name: "테스트 10+1 식권 선택" }).click();
  await page.getByLabel("사용 포인트").fill("2000");
  await page.getByLabel("할인 쿠폰").selectOption("issued:issued-fixture");
  await page.getByRole("button", { name: "견적 확인" }).click();
  await page.getByLabel("구매 조건 확인").check();
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
  await expect.poll(() => checkoutEntered).toBe(1);
  expect(purchased).toEqual({
    product_id: product.id,
    requested_point_amount: 2000,
    user_coupon_id: "issued-fixture",
  });
  await expect(
    page.getByRole("button", { name: "예약 취소 요청" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "승인 상태 확인" }).click();
  await expect(page.getByRole("alert")).toContainText("confirm failure");
  await expect(page.getByRole("heading", { name: "결제 완료" })).toHaveCount(0);
  await page.route("**/api-fixture/payments/confirm", async (route) => {
    confirmed = route.request().postDataJSON();
    await route.fulfill({
      json: {
        ok: true,
        data: {
          order_id: "GE-S-mixed-fixture",
          amount: 39000,
          status: "done",
          issued_count: 11,
          payment: { method: "CARD" },
          receipts: {},
        },
      },
    });
  });
  await page.getByRole("button", { name: "승인 상태 확인" }).click();
  await expect(page.getByRole("heading", { name: "결제 완료" })).toBeVisible();
  expect(confirmed).toEqual({ order_id: "GE-S-mixed-fixture", amount: 39000 });
});
test("cancel refusal preserves pending authority and cannot mark canceled", async ({
  page,
}) => {
  await fixture(page, {
    role: "employee",
    status: "active",
    company_id: "company-fixture",
  });
  await publishedLegal(page);
  await catalogFixture(page, "subsidized");
  await page.addInitScript(() =>
    sessionStorage.setItem(
      "greeneat-purchase-pending:11111111-1111-4111-8111-111111111111",
      JSON.stringify({
        order_id: "GE-S-refused-fixture",
        amount: 40000,
        mode: "subsidized",
        checkout_started: false,
      }),
    ),
  );
  await page.route(
    "**/api-fixture/vouchers/subsidized-orders/GE-S-refused-fixture/cancel",
    (route) =>
      route.fulfill({
        status: 409,
        json: {
          detail: {
            code: "CHECKOUT_ALREADY_STARTED",
            message: "MOCK ONLY checkout already started",
          },
        },
      }),
  );
  await login(page);
  await page.getByRole("button", { name: "예약 취소 요청" }).click();
  await expect(page.getByRole("alert")).toContainText("already started");
  await expect(
    page.getByRole("heading", { name: "결제 취소 확인" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "진행 중인 결제" }),
  ).toBeVisible();
});
test("logout during quote response prevents stale quote and purchaser UI from returning", async ({
  page,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  let release, requested;
  const started = new Promise((resolve) => {
    requested = resolve;
  });
  const barrier = new Promise((resolve) => {
    release = resolve;
  });
  await page.route("**/api-fixture/vouchers/quote", async (route) => {
    requested();
    await barrier;
    await route.fulfill({
      json: {
        ok: true,
        data: {
          merchant_id: "merchant-fixture",
          merchant_name: "테스트 식당",
          product_id: product.id,
          purchase_mode: "voucher",
          gross_amount: 72000,
          coupon_discount_amount: 0,
          point_amount: 0,
          payment_amount: 72000,
        },
      },
    });
  });
  await selectQuote(page);
  await started;
  await page.getByRole("navigation").getByRole("button", { name: "내정보", exact: true }).click();
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  release();
  await expect(
    page.getByRole("button", { name: "로그인", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("최종 결제 72,000원")).toHaveCount(0);
});
test("rejected employee may convert only via customer registration endpoint", async ({
  page,
}) => {
  const profile = { role: "employee", status: "rejected" };
  const calls = await fixture(page, profile);
  await publishedLegal(page);
  await page.route("**/api-fixture/consumer/register", async (route) => {
    calls.push({
      path: "/consumer/register",
      body: route.request().postDataJSON(),
    });
    Object.assign(profile, { role: "customer", status: "active" });
    await route.fulfill({ json: { ok: true, data: profile } });
  });
  await login(page);
  await page.getByLabel("이름", { exact: true }).fill("전환 고객");
  await page.getByLabel("휴대폰 번호").fill("01012345678");
  await page.getByLabel("약관 및 개인정보 처리방침 확인").check();
  await page.getByRole("button", { name: "일반 구매자로 등록" }).click();
  await expect(page.getByRole("region", { name: "내 지갑" })).toBeVisible();
  expect(calls.filter((c) => c.path === "/consumer/register")).toHaveLength(1);
});
test("negative employee points are rejected before quote API", async ({
  page,
}) => {
  const calls = await fixture(page, {
    role: "employee",
    status: "active",
    company_id: "company-fixture",
  });
  await catalogFixture(page, "subsidized");
  await login(page);
  await page.getByRole("button", { name: "테스트 10+1 식권 선택" }).click();
  await page.getByLabel("사용 포인트").fill("-1");
  await page.getByRole("button", { name: "견적 확인" }).click();
  await expect(page.getByRole("alert")).toContainText("0 이상의 정수");
  expect(calls.some((c) => c.path === "/vouchers/quote")).toBe(false);
});
test("desktop and mobile purchaser browser screenshots have no overflow or oversized checkbox", async ({
  page,
}, testInfo) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  await quoteFixture(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await selectQuote(page);
  const out = dirname(testInfo.project.outputDir);
  await page.screenshot({
    path: join(out, "purchaser-desktop-mocked.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: join(out, "purchaser-mobile-mocked.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  const box = await page.getByLabel("구매 조건 확인").boundingBox();
  expect(box.width).toBeLessThanOrEqual(28);
});
test("logout during order response never opens provider or applies old account result", async ({
  page,
  context,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  await quoteFixture(page);
  let release,
    requested,
    providerRequests = 0;
  const started = new Promise((resolve) => {
    requested = resolve;
  });
  const barrier = new Promise((resolve) => {
    release = resolve;
  });
  await page.route("**/api-fixture/vouchers/purchase", async (route) => {
    requested();
    await barrier;
    await route.fulfill({
      json: {
        ok: true,
        data: {
          order_id: "GE-V-stale-fixture",
          product_id: product.id,
          amount: 72000,
          checkout_url: `http://127.0.0.1:4175/api-fixture/payments/checkout/${"a".repeat(43)}`,
        },
      },
    });
  });
  await context.route("**/api-fixture/payments/checkout/**", (route) => {
    providerRequests++;
    return route.fulfill({ body: "MOCK ONLY" });
  });
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
  await started;
  await page.getByRole("navigation").getByRole("button", { name: "내정보", exact: true }).click();
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  release();
  await expect(
    page.getByRole("button", { name: "로그인", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "진행 중인 결제" }),
  ).toHaveCount(0);
  await expect.poll(() => context.pages().length).toBe(1);
  expect(providerRequests).toBe(0);
});
test("duplicate submit and refresh cannot create a second order and pending survives reload", async ({
  page,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  await quoteFixture(page);
  let purchases = 0;
  await page.route("**/api-fixture/vouchers/purchase", async (route) => {
    purchases++;
    await route.fulfill({
      json: {
        ok: true,
        data: {
          order_id: "GE-V-recover-fixture",
          product_id: product.id,
          amount: 72000,
          checkout_url: "https://evil.invalid/form",
        },
      },
    });
  });
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  await page
    .getByRole("button", { name: "구매하기", exact: true })
    .evaluate((button) => {
      button.click();
      button.click();
    });
  await expect(
    page.getByRole("heading", { name: "진행 중인 결제" }),
  ).toBeVisible();
  expect(purchases).toBe(1);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "진행 중인 결제" }),
  ).toBeVisible();
  await expect(page.getByText("주문 GE-V-recover-fixture")).toBeVisible();
  expect(purchases).toBe(1);
});
test("ambiguous order network error blocks automatic retry and survives reload", async ({
  page,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  await quoteFixture(page);
  let purchases = 0;
  await page.route("**/api-fixture/vouchers/purchase", (route) => {
    purchases++;
    return route.abort("failed");
  });
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "주문 상태 확인 필요" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "주문 상태 확인 필요" }),
  ).toBeVisible();
  expect(purchases).toBe(1);
});
test("actual published legal pages allow purchase despite unresolved disclosure", async ({
  page,
}) => {
  const calls = await fixture(page);
  await catalogFixture(page);
  await quoteFixture(page);
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  await expect(
    page.getByRole("button", { name: "구매하기", exact: true }),
  ).toBeEnabled();
  await expect(page.getByText("가입·구매를 진행할 수 없어요.", { exact: false })).toHaveCount(0);
  expect(calls.some((c) => c.path.includes("/purchase"))).toBe(false);
});
test("unavailable privacy document still disables purchase", async ({ page }) => {
  const calls = await fixture(page);
  await page.route("**/privacy.html", route => route.fulfill({ status: 503, body: "" }));
  await catalogFixture(page);
  await quoteFixture(page);
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  await expect(page.getByRole("button", { name: "구매하기", exact: true })).toBeDisabled();
  await expect(page.getByRole("alert")).toContainText("불러오지 못했어요");
  expect(calls.some(c => c.path.includes("/purchase"))).toBe(false);
});
test("published terms need not contain the selected merchant to allow purchase", async ({
  page,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await page.route("**/terms.html", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<h1>이용약관</h1><p>MOCK ONLY 시행일 2026.01.01 운영자와 사용자 계약 내용</p>",
    }),
  );
  await catalogFixture(page);
  await quoteFixture(page);
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  await expect(
    page.getByRole("button", { name: "구매하기", exact: true }),
  ).toBeEnabled();
});
for (const status of ["pending", "suspended", "inactive"])
  test(`employee ${status} is read-only and never loads purchaser catalog`, async ({
    page,
  }) => {
    const calls = await fixture(page, { role: "employee", status });
    await login(page);
    await expect(page.getByRole("alert")).toContainText(status);
    expect(calls.some((c) => c.path === "/vouchers/products")).toBe(false);
  });
test("auth rejection displays provider error without rendering wallet", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/auth-fixture/auth/v1/token**", (route) =>
    route.fulfill({
      status: 400,
      json: {
        error: "invalid_grant",
        error_description: "MOCK ONLY invalid credentials",
      },
    }),
  );
  await login(page);
  await expect(page.getByRole("alert")).toContainText("invalid credentials");
  await expect(page.getByRole("region", { name: "내 지갑" })).toHaveCount(0);
});
test("none purchase mode hides selectable packages for active noneligible employee", async ({
  page,
}) => {
  await fixture(page, {
    role: "employee",
    status: "active",
    company_id: "company-fixture",
  });
  await catalogFixture(page, "none");
  await login(page);
  await expect(
    page.getByText(
      "현재 구매 가능한 식권이 없어요. 회사 계약 및 계정 상태를 확인해 주세요.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "테스트 10+1 식권 선택" }),
  ).toHaveCount(0);
});
test("malformed quote amount blocks purchase and never displays a payable quote", async ({
  page,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  await quoteFixture(page, "voucher", -1);
  await selectQuote(page);
  await expect(page.getByRole("alert")).toContainText("견적 금액");
  await expect(
    page.getByRole("button", { name: "구매하기", exact: true }),
  ).toHaveCount(0);
});
test("card approval renders only authoritative receipt links and keeps malformed confirm pending", async ({
  page,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  await quoteFixture(page);
  let count = 0;
  await page.addInitScript(() =>
    sessionStorage.setItem(
      "greeneat-purchase-pending:11111111-1111-4111-8111-111111111111",
      JSON.stringify({
        order_id: "GE-V-receipt-fixture",
        amount: 72000,
        mode: "voucher",
        checkout_started: true,
      }),
    ),
  );
  await page.route("**/api-fixture/payments/confirm", async (route) => {
    count++;
    await route.fulfill({
      json: {
        ok: true,
        data: {
          order_id: count === 1 ? "wrong-order" : "GE-V-receipt-fixture",
          status: "done",
          amount: 72000,
          product_name: product.name,
          merchant_name: "테스트 식당",
          issued_count: 11,
          payment: {
            method: "CARD",
            method_label: "카드",
            approved_at: "2026-01-01T00:00:00Z",
          },
          receipts: {
            sales_slip_url:
              "https://agenttest.kiwoompay.co.kr/common/PayInfoPrintDirectCard.jsp?DAOUTRX=fixture&STATUS=A",
            cash_receipt_url: "https://evil.invalid/receipt",
          },
        },
      },
    });
  });
  await login(page);
  await page.getByRole("button", { name: "승인 상태 확인" }).click();
  await expect(page.getByRole("heading", { name: "결제 완료" })).toHaveCount(0);
  await page.getByRole("button", { name: "승인 상태 확인" }).click();
  await expect(page.getByRole("heading", { name: "결제 완료" })).toBeVisible();
  await expect(page.getByRole("link", { name: "매출전표" })).toHaveAttribute(
    "href",
    "https://agenttest.kiwoompay.co.kr/common/PayInfoPrintDirectCard.jsp?DAOUTRX=fixture&STATUS=A",
  );
  await expect(page.getByRole("link", { name: "현금영수증" })).toHaveCount(0);
});
test("native history prefers voucher use and does not invent ledger or point tabs", async ({
  page,
}) => {
  await fixture(page, {
    role: "customer",
    status: "active",
    voucher_use_history: [
      {
        id: "used-fixture",
        kind: "voucher_use",
        voucher_id: "synthetic-used-voucher",
        title: "점심 식권",
        merchant_name: "테스트 식당",
        amount: 8000,
        is_bonus: true,
        created_at: "2026-01-02T03:00:00Z",
      },
    ],
    recent_transactions: [
      {
        id: "payment-fixture",
        title: "카드 식사",
        merchant_name: "테스트 식당",
        amount: 9000,
        created_at: "2026-01-03T03:00:00Z",
      },
    ],
    point_transactions: [
      {
        id: "point-fixture",
        reason: "테스트 적립",
        type: "earn",
        amount: 500,
        balance_after: 2000,
        created_at: "2026-01-04T03:00:00Z",
      },
    ],
  });
  await login(page, '내역');
  await expect(page.getByRole('heading', { name: '이용내역' })).toBeVisible();
  await expect(page.locator('.usage-history:visible').getByText('테스트 식당 점심 식권', { exact: true })).toBeVisible();
  await expect(page.locator('.usage-history:visible .usage-row')).toContainText('보너스');
  await expect(page.getByText('카드 식사', { exact: true })).toHaveCount(0);
  await expect(page.getByText('테스트 적립', { exact: false })).toHaveCount(0);
});
test("employee invalid checkout is blocked and only server release confirms cancellation", async ({
  page,
}) => {
  await fixture(page, {
    role: "employee",
    status: "active",
    company_id: "company-fixture",
  });
  await publishedLegal(page);
  await catalogFixture(page, "subsidized");
  await quoteFixture(page, "subsidized", 40000, 2000);
  let canceled = 0;
  await page.route("**/api-fixture/vouchers/purchase-subsidized", (route) =>
    route.fulfill({
      json: {
        ok: true,
        data: {
          order_id: "GE-S-cancel-fixture",
          product_id: product.id,
          amount: 40000,
          checkout_url: "https://evil.invalid/form",
        },
      },
    }),
  );
  await page.route(
    "**/api-fixture/vouchers/subsidized-orders/GE-S-cancel-fixture/cancel",
    async (route) => {
      canceled++;
      await route.fulfill({
        json: { ok: true, data: { released: true, point_amount: 2000 } },
      });
    },
  );
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("결제창 URL");
  await expect(
    page.getByRole("heading", { name: "결제 취소 확인" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "예약 취소 요청" }).click();
  await expect(
    page.getByRole("heading", { name: "결제 취소 확인" }),
  ).toBeVisible();
  expect(canceled).toBe(1);
});
test("point-only employee order completes from authoritative issuance without forbidden zero-amount confirm", async ({
  page,
}) => {
  const profile = {
    role: "employee",
    status: "active",
    company_id: "company-fixture",
    point_balance: 42000,
    voucher_balance: 0,
  };
  await fixture(page, profile);
  await publishedLegal(page);
  await catalogFixture(page, "subsidized");
  await quoteFixture(page, "subsidized", 0, 42000);
  let orderBody, confirmBody;
  await page.route(
    "**/api-fixture/vouchers/purchase-subsidized",
    async (route) => {
      orderBody = route.request().postDataJSON();
      Object.assign(profile, { point_balance: 0, voucher_balance: 11 });
      await route.fulfill({
        json: {
          ok: true,
          data: {
            order_id: "GE-S-point-fixture",
            product_id: product.id,
            product_name: product.name,
            total_count: 11,
            amount: 0,
            gross_amount: 42000,
            coupon_discount_amount: 0,
            card_amount: 0,
            point_amount: 42000,
            point_only: true,
            checkout_url: null,
            fulfillment: { order_id: "GE-S-point-fixture", status: "done", issued_count: 11, card_amount: 0, point_amount: 42000 },
          },
        },
      });
    },
  );
  await page.route("**/api-fixture/payments/confirm", async (route) => {
    confirmBody = route.request().postDataJSON();
    await route.fulfill({ status: 422, json: { detail: [{ loc: ["body", "amount"], type: "greater_than", ctx: { gt: 0 } }] } });
  });
  await login(page);
  await page.getByRole("button", { name: "테스트 10+1 식권 선택" }).click();
  await page.getByLabel("사용 포인트").fill("42000");
  await page.getByRole("button", { name: "견적 확인" }).click();
  await page.getByLabel("구매 조건 확인").check();
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
  expect(orderBody).toEqual({
    product_id: product.id,
    requested_point_amount: 42000,
  });
  await expect(page.getByRole("heading", { name: "결제 완료" })).toBeVisible();
  await expect(page.getByText("발급 식권 11장")).toBeVisible();
  expect(confirmBody).toBeUndefined();
  await page.getByRole("navigation").getByRole("button", { name: "홈", exact: true }).click();
  await expect(page.getByText('보유 보조금 식권 11장 · 실제 결제 방식은 서버에서 확인해요.')).toBeVisible();
  await expect(page.locator(".ticket-wallet")).toContainText("0P");
  expect(page.context().pages()).toHaveLength(1);
});
for (const invalid of ["missing", "wrong-order", "wrong-count", "not-done"]) {
  test(`point-only ${invalid} fulfillment never fabricates completion or retries order`, async ({ page }) => {
    const calls = await fixture(page, { role: "employee", status: "active", point_balance: 42000 });
    await publishedLegal(page);
    await catalogFixture(page, "subsidized");
    await quoteFixture(page, "subsidized", 0, 42000);
    let purchases = 0;
    await page.route("**/api-fixture/vouchers/purchase-subsidized", route => {
      purchases++;
      const fulfillment = { order_id: "GE-S-invalid-point", status: "done", issued_count: 11, card_amount: 0, point_amount: 42000 };
      if (invalid === "wrong-order") fulfillment.order_id = "GE-S-another-order";
      if (invalid === "wrong-count") fulfillment.issued_count = 12;
      if (invalid === "not-done") fulfillment.status = "ready";
      return route.fulfill({ json: { ok: true, data: { order_id: "GE-S-invalid-point", product_id: product.id, product_name: product.name, total_count: 11, amount: 0, card_amount: 0, point_amount: 42000, point_only: true, checkout_url: null, fulfillment: invalid === "missing" ? null : fulfillment } } });
    });
    await login(page);
    await page.getByRole("button", { name: "테스트 10+1 식권 선택" }).click();
    await page.getByLabel("사용 포인트").fill("42000");
    await page.getByRole("button", { name: "견적 확인" }).click();
    await page.getByLabel("구매 조건 확인").check();
    await page.getByRole("button", { name: "구매하기", exact: true }).click();
    await expect(page.getByRole("heading", { name: "주문 상태 확인 필요" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "결제 완료" })).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("heading", { name: "주문 상태 확인 필요" })).toBeVisible();
    expect(purchases).toBe(1);
    expect(calls.some(c => c.path === "/payments/confirm")).toBe(false);
    expect(page.context().pages()).toHaveLength(1);
  });
}
test("restored zero-card order remains unresolved without forbidden confirm or cancel", async ({ page }) => {
  const calls = await fixture(page, { role: "employee", status: "active" });
  await page.addInitScript(() => sessionStorage.setItem("greeneat-purchase-pending:11111111-1111-4111-8111-111111111111", JSON.stringify({ order_id: "GE-S-zero-unresolved", amount: 0, mode: "subsidized", checkout_started: false })));
  await login(page);
  await expect(page.getByRole("heading", { name: "주문 상태 확인 필요" })).toBeVisible();
  await expect(page.getByRole("button", { name: "승인 상태 확인" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "예약 취소 요청" })).toHaveCount(0);
  expect(calls.some(c => c.path === "/payments/confirm")).toBe(false);
});
test("ordinary order opens exact API server form, callback and popup close cannot approve pending", async ({
  page,
  context,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  await quoteFixture(page);
  let orderBody,
    formPosted = false,
    confirms = 0;
  const token = "a".repeat(43);
  await page.route("**/api-fixture/vouchers/purchase", async (route) => {
    orderBody = route.request().postDataJSON();
    await route.fulfill({
      json: {
        ok: true,
        data: {
          order_id: "GE-V-fixture",
          amount: 72000,
          gross_amount: 72000,
          coupon_discount_amount: 0,
          point_amount: 0,
          product_id: product.id,
          checkout_url: `http://127.0.0.1:4175/api-fixture/payments/checkout/${token}`,
        },
      },
    });
  });
  await context.route(`**/api-fixture/payments/checkout/${token}`, (route) =>
    route.fulfill({
      contentType: "text/html",
      body: '<h1>MOCK SERVER CHECKOUT FORM</h1><form method="post" action="https://apitest.kiwoompay.co.kr/pay/linkEnc" accept-charset="EUC-KR"><input name="ORDERNO" value="GE-V-fixture"><input name="AMOUNT" value="72000"></form><script>document.querySelector("form").submit()</script>',
    }),
  );
  await context.route(
    "https://apitest.kiwoompay.co.kr/pay/linkEnc",
    async (route) => {
      formPosted =
        route.request().method() === "POST" &&
        route.request().postData().includes("ORDERNO=GE-V-fixture");
      await route.fulfill({
        contentType: "text/html",
        body: "<h1>MOCK PROVIDER ONLY</h1>",
      });
    },
  );
  await page.route("**/api-fixture/payments/confirm", async (route) => {
    confirms++;
    await route.fulfill({
      status: 409,
      json: { detail: { code: "PAYMENT_PENDING", message: "승인 대기 중" } },
    });
  });
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  const popupPromise = page.waitForEvent("popup");
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
  const popup = await popupPromise;
  await expect.poll(() => formPosted).toBe(true);
  expect(orderBody).toEqual({
    product_id: product.id,
    requested_point_amount: 0,
  });
  await popup.close();
  await page.evaluate(() =>
    window.postMessage(
      { type: "payment_success", order_id: "GE-V-fixture", status: "done" },
      "*",
    ),
  );
  await page.getByRole("button", { name: "승인 상태 확인" }).click();
  await expect(
    page.getByText("결제 승인 확인 중", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "결제 완료" })).toHaveCount(0);
  expect(confirms).toBe(1);
  await expect(
    page.getByRole("button", { name: "구매하기", exact: true }),
  ).toHaveCount(0);
});
test("eligible employee point quote preserves server split and invalidates quote on edits", async ({
  page,
}) => {
  await fixture(page, {
    role: "employee",
    status: "active",
    company_id: "company-fixture",
  });
  await publishedLegal(page);
  await catalogFixture(page, "subsidized");
  let quoted;
  await page.route("**/api-fixture/vouchers/quote", async (route) => {
    quoted = route.request().postDataJSON();
    await route.fulfill({
      json: {
        ok: true,
        data: {
          merchant_id: "merchant-fixture",
          merchant_name: "테스트 식당",
          product_id: product.id,
          purchase_mode: "subsidized",
          gross_amount: 42000,
          coupon_discount_amount: 0,
          point_amount: 2000,
          payment_amount: 40000,
        },
      },
    });
  });
  await login(page);
  await page.getByRole("button", { name: "테스트 10+1 식권 선택" }).click();
  await expect(page.getByText("회사 지원 합계 20,000원")).toBeVisible();
  await page.getByLabel("사용 포인트").fill("2000");
  await page.getByRole("button", { name: "견적 확인" }).click();
  expect(quoted).toEqual({
    product_id: product.id,
    requested_point_amount: 2000,
  });
  await expect(page.getByText("포인트 사용 2,000P")).toBeVisible();
  await expect(page.getByText("최종 결제 40,000원")).toBeVisible();
  await page.getByLabel("사용 포인트").fill("1000");
  await expect(page.getByText("최종 결제 40,000원")).toHaveCount(0);
});
test("ordinary package selection shows API terms and coupon quote without client quantity or points", async ({
  page,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  let quoted;
  await page.route("**/api-fixture/vouchers/quote", async (route) => {
    quoted = route.request().postDataJSON();
    await route.fulfill({
      json: {
        ok: true,
        data: {
          merchant_id: "merchant-fixture",
          merchant_name: "테스트 식당",
          product_id: product.id,
          purchase_mode: "voucher",
          gross_amount: 72000,
          coupon_discount_amount: 1000,
          point_amount: 0,
          payment_amount: 71000,
        },
      },
    });
  });
  await login(page);
  await page.getByRole("button", { name: "테스트 10+1 식권 선택" }).click();
  await expect(page.locator('.purchase-detail').getByText("유료 10장 + 보너스 1장")).toBeVisible();
  await expect(page.getByText("할인율 10%")).toBeVisible();
  await page.getByLabel("할인 쿠폰").selectOption("public:coupon-fixture");
  await page.getByRole("button", { name: "견적 확인" }).click();
  await expect(page.getByText("최종 결제 71,000원")).toBeVisible();
  expect(quoted).toEqual({
    product_id: product.id,
    requested_point_amount: 0,
    coupon_id: "coupon-fixture",
  });
  await expect(page.getByLabel("사용 포인트")).toHaveCount(0);
  await expect(
    page.locator(".purchase-quote").getByText("테스트 식당", { exact: true }),
  ).toBeVisible();
});
test("employee requests membership then sees pending server state without catalog", async ({
  page,
}) => {
  const profile = { status: "no_profile" };
  const calls = await fixture(page, profile);
  await publishedLegal(page);
  await page.route("**/api-fixture/join/request", async (route) => {
    calls.push({ path: "/join/request", body: route.request().postDataJSON() });
    Object.assign(profile, { role: "employee", status: "pending" });
    await route.fulfill({ json: { ok: true, data: profile } });
  });
  await login(page);
  await page.getByLabel("이름", { exact: true }).fill("직원");
  await page.getByLabel("휴대폰 번호").fill("01012345678");
  await page.getByLabel("회사 초대코드").fill("GE-FIXTURE");
  await page.getByLabel("약관 및 개인정보 처리방침 확인").check();
  await page.getByRole("button", { name: "회사 가입 신청" }).click();
  await expect(page.getByRole("alert")).toContainText("pending");
  expect(calls.find((c) => c.path === "/join/request").body).toEqual({
    invite_code: "GE-FIXTURE",
    display_name: "직원",
    phone: "01012345678",
  });
  expect(calls.some((c) => c.path === "/vouchers/products")).toBe(false);
});
test("signup with actual published documents requires consent and waits for email verification", async ({
  page,
}) => {
  const calls = await fixture(page);
  let signup;
  await page.route("**/auth-fixture/auth/v1/signup**", async (route) => {
    signup = route.request().postDataJSON();
    await route.fulfill({
      json: { user: { id: "new-fixture", email: signup.email }, session: null },
    });
  });
  await page.goto("/shop");
  await page.getByRole("button", { name: "회원가입", exact: true }).click();
  await page.getByLabel("이메일", { exact: true }).fill("new@example.invalid");
  await page
    .getByLabel("비밀번호", { exact: true })
    .fill("mocked-password-only");
  await expect(page.getByRole("button", { name: "가입 신청", exact: true })).toBeDisabled();
  await page.getByLabel("약관 및 개인정보 처리방침 확인").check();
  await page.getByRole("button", { name: "가입 신청", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("이메일 인증");
  expect(signup.email).toBe("new@example.invalid");
  expect(calls).toEqual([]);
});
test("new authenticated purchaser registers with normalized phone and server profile refresh", async ({
  page,
}) => {
  const profile = { status: "no_profile" };
  const calls = await fixture(page, profile);
  await publishedLegal(page);
  await page.route("**/api-fixture/consumer/register", async (route) => {
    calls.push({
      path: "/consumer/register",
      body: route.request().postDataJSON(),
    });
    Object.assign(profile, { role: "customer", status: "active" });
    await route.fulfill({ json: { ok: true, data: profile } });
  });
  await login(page);
  await page.getByLabel("이름", { exact: true }).fill(" 새 고객 ");
  await page.getByLabel("휴대폰 번호").fill("010-1234-5678");
  await page.getByLabel("약관 및 개인정보 처리방침 확인").check();
  await page.getByRole("button", { name: "일반 구매자로 등록" }).click();
  await expect(page.getByRole("region", { name: "내 지갑" })).toBeVisible();
  expect(calls.find((c) => c.path === "/consumer/register").body).toEqual({
    display_name: "새 고객",
    phone: "01012345678",
  });
});
test("purchaser rejects admin and pending employee instead of exposing a wallet", async ({
  page,
}) => {
  await fixture(page, { role: "merchant_admin", status: "active" });
  await login(page);
  await expect(page.getByRole("alert")).toContainText("구매자 계정이 아니에요");
  await expect(page.getByRole("region", { name: "내 지갑" })).toHaveCount(0);
});

test("purchaser sign-in renders its own wallet, refresh and logout", async ({
  page,
}) => {
  const calls = await fixture(page);
  await login(page);
  await expect(page.getByRole("heading", { name: "식권 구매" })).toBeVisible();
  await page.getByRole("navigation").getByRole("button", { name: "홈", exact: true }).click();
  await expect(page.locator(".ticket-balance")).toHaveText("3장");
  await page.getByRole("button", { name: "새로고침", exact: true }).click();
  await expect.poll(() => calls.filter((c) => c.path === "/me").length).toBe(2);
  await page.getByRole("navigation").getByRole("button", { name: "내정보", exact: true }).click();
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "로그인", exact: true }),
  ).toBeVisible();
});

for (const [label, saved] of [
  ["invalid-id", { order_id: " ../bad", amount: 72000, mode: "voucher" }],
  ["invalid-mode", { order_id: recoveryReady.order_id, amount: 72000, mode: "other" }],
  ["invalid-amount", { order_id: recoveryReady.order_id, amount: "72000", mode: "voucher" }],
  ["null-pricing", { order_id: recoveryReady.order_id, amount: 72000, mode: "voucher", resume_allowed: true, accepted_pricing: null }],
]) test(`recovery corrupt saved ${label} stays protected without exceptions`, async ({ page, context }) => {
  const calls = await fixture(page); await catalogFixture(page);
  const errors = []; page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(({ key, saved }) => sessionStorage.setItem(key, JSON.stringify(saved)), { key: recoveryStorageKey, saved });
  await page.route("**/api-fixture/payments/recovery?**", route => route.fulfill({ json: { ok: true, data: { ...recoveryReady, recovery_action: "reconcile", checkout_url: null, resumable: false } } }));
  await login(page);
  await expect(page.getByRole("button", { name: "기존 결제창 다시 열기" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "구매하기", exact: true })).toHaveCount(0);
  if (label === "null-pricing") {
    await page.getByRole("button", { name: "저장된 주문 상태 확인" }).click();
    await expect(page.getByRole("alert")).toContainText("관리자에게 거래 확인");
  } else {
    await expect(page.getByRole("heading", { name: "주문 상태 확인 필요" })).toBeVisible();
    expect(calls.some(call => call.path.includes("recovery"))).toBe(false);
  }
  expect(calls.some(call => call.path.includes("purchase"))).toBe(false);
  expect(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)), recoveryStorageKey)).toEqual(saved);
  expect(errors).toEqual([]); expect(context.pages()).toHaveLength(1);
});
