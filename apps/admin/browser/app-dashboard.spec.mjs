// SYNTHETIC fixtures only. Every nonlocal request is blocked.
import { test, expect } from '@playwright/test';
import { join } from 'node:path';
const receipts = process.env.PURCHASE_RECEIPTS;
test.use({ timezoneId: 'Asia/Seoul' });
async function setup(page, context) {
  const calls = [], errors = [];
  await page.addInitScript(() => document.addEventListener('DOMContentLoaded', () => {
    const style = document.createElement('style');
    style.textContent = '.purchase-app *, .purchase-app *::before, .purchase-app *::after { transition: none !important; animation: none !important; }';
    document.head.append(style);
  }));
  page.on('pageerror', e => errors.push(e.message));
  await context.route('**/*', route => new URL(route.request().url()).origin === 'http://127.0.0.1:4175' ? route.continue() : route.abort());
  const user = { id: '11111111-1111-4111-8111-111111111111', email: 'synthetic@example.invalid', aud: 'authenticated', role: 'authenticated' };
  await page.route('**/auth-fixture/auth/v1/**', route => route.fulfill({ json: { access_token: 'synthetic-only', refresh_token: 'synthetic-refresh', expires_in: 3600, token_type: 'bearer', user } }));
  await page.route('**/api-fixture/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/api-fixture', '');
    calls.push({ path, body: route.request().postDataJSON() });
    const data = {
      '/me': { user_id: user.id, display_name: '합성 구매자', phone: '01000000000', role: 'customer', status: 'active', account_type: 'voucher', voucher_balance: 12, point_balance: 2500, voucher_month_used_count: 2, voucher_month_used_amount: 16000, voucher_use_history: [{ id: 'synthetic-use', kind: 'voucher_use', voucher_id: 'synthetic-voucher', title: '점심 식권', merchant_name: '합성 식당', amount: 8000, created_at: '2026-01-02T03:00:00Z' }], recent_transactions: [{ id: 'synthetic-ignored', title: '우선순위 제외', amount: 999 }] },
      '/coupons': { merchant: { id: 'synthetic-merchant', name: '합성 식당' }, items: [{ id: 'synthetic-coupon', name: '합성 할인', discount_type: 'fixed', discount_value: 1000 }], issued: [] },
      '/daily-menu': { today_menu: { title: '합성 오늘 메뉴', menu_text: '합성 메뉴 · 사진 없음', image_url: null } },
      '/vouchers/products': { purchase_mode: 'voucher', items: [{ id: 'synthetic-product', name: '합성 10+1 식권', voucher_count: 10, bonus_count: 1, sale_price: 72000, unit_price: 8000, discount_rate: 10, is_event: true }] },
      '/vouchers/quote': { merchant_id: 'synthetic-merchant', merchant_name: '합성 식당', product_id: 'synthetic-product', purchase_mode: 'voucher', gross_amount: 72000, coupon_discount_amount: 0, point_amount: 0, payment_amount: 72000 },
      '/announcements': { items: [{ id: 'synthetic-notice', title: '합성 공지', content: '합성 공지 본문' }] },
      '/reviews': { items: [{ id: 'synthetic-review', rating: 5, content: '합성 리뷰 본문' }] },
    }[path];
    return route.fulfill({ json: { ok: true, data: data || {} } });
  });
  return { calls, errors };
}
async function login(page) {
  await page.goto('/shop');
  await page.getByLabel('이메일', { exact: true }).fill('synthetic@example.invalid');
  await page.getByLabel('비밀번호', { exact: true }).fill('synthetic-password-only');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('navigation', { name: '구매자 탭' })).toBeVisible();
}
test('inactive purchaser can sign out without admin navigation', async ({ page, context }) => {
  await setup(page, context);
  await page.route('**/api-fixture/me', route => route.fulfill({ json: { ok: true, data: { role: 'customer', status: 'suspended' } } }));
  await page.route('**/auth-fixture/auth/v1/logout', route => route.fulfill({ status: 204 }));
  await page.goto('/shop');
  await page.getByLabel('이메일', { exact: true }).fill('synthetic@example.invalid');
  await page.getByLabel('비밀번호', { exact: true }).fill('synthetic-password-only');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('suspended');
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeVisible();
});
test('product selection opens discount stage directly and back returns to catalog', async ({ page, context }) => {
  await setup(page, context); await login(page);
  await page.getByRole('navigation').getByRole('button', { name: '구매', exact: true }).click();
  await page.getByRole('button', { name: '합성 10+1 식권 선택' }).click();
  await expect(page.getByRole('heading', { name: '할인 선택', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '합성 10+1 식권 선택' })).toHaveCount(0);
  await page.getByRole('button', { name: '상품 다시 선택', exact: true }).click();
  await expect(page.getByRole('button', { name: '합성 10+1 식권 선택' })).toBeVisible();
});
test('navy email login explicitly differs from native phone auth', async ({ page, context }) => {
  await setup(page, context); await page.goto('/shop');
  await expect(page.getByText('웹 전용 이메일 로그인')).toBeVisible();
  await expect(page.getByText('앱의 휴대폰 인증과 다른 로그인 방식이에요.')).toBeVisible();
  await expect(page.locator('.purchase-login img')).toHaveAttribute('src', '/brand/greeneat_logo_light.png');
  expect(await page.locator('.purchase-app').evaluate(e => getComputedStyle(e).backgroundColor)).toBe('rgb(14, 28, 43)');
});
test('native five tabs, real shortcuts and history precedence', async ({ page, context }) => {
  const { calls, errors } = await setup(page, context); await login(page);
  const nav = page.getByRole('navigation', { name: '구매자 탭' });
  await expect(nav.getByRole('button')).toHaveText(['홈', '구매', 'QR', '내역', '내정보']);
  await expect(nav.getByRole('button', { name: '홈', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByText('합성 오늘 메뉴')).toBeVisible();
  await page.getByRole('button', { name: '쿠폰함', exact: true }).click();
  await expect(page.getByText('합성 할인')).toBeVisible();
  await page.getByRole('button', { name: '홈으로', exact: true }).click();
  await page.getByRole('button', { name: '공지사항', exact: true }).click();
  await expect(page.getByText('합성 공지 본문')).toBeVisible();
  await page.getByRole('button', { name: '홈으로', exact: true }).click();
  await page.getByRole('button', { name: '리뷰', exact: true }).click();
  await expect(page.getByText('합성 리뷰 본문')).toBeVisible();
  await nav.getByRole('button', { name: '내역', exact: true }).click();
  await expect(page.getByRole('heading', { name: '이용내역' })).toBeVisible();
  await expect(page.getByText('우선순위 제외')).toHaveCount(0);
  await nav.getByRole('button', { name: '내정보', exact: true }).click();
  await expect(page.getByText('이메일 (웹)')).toBeVisible();
  expect(calls.some(c => c.path.includes('/purchase') || c.path.includes('/banners'))).toBe(false);
  expect(errors).toEqual([]);
});
test('manual QR payment retries same intent after ambiguous failure, only server success completes', async ({ page, context }) => {
  await setup(page, context); let bodies = [];
  await page.route('**/api-fixture/transactions/scan', route => {
    bodies.push(route.request().postDataJSON());
    return bodies.length === 1 ? route.abort('failed') : route.fulfill({ json: { result: 'success', pay_type: 'voucher', remaining: 11, transaction: { id: 'synthetic-scan', amount: 8000 } } });
  });
  await login(page);
  await page.getByRole('navigation').getByRole('button', { name: 'QR', exact: true }).click();
  await page.getByLabel('매장 QR 내용').fill('QR-SYNTHETIC');
  await page.getByRole('button', { name: 'QR 결제 확인', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('같은 요청');
  await page.getByRole('button', { name: '같은 요청으로 다시 확인', exact: true }).click();
  await expect(page.getByRole('heading', { name: '사용 완료' })).toBeVisible();
  expect(bodies).toHaveLength(2); expect(bodies[1]).toEqual(bodies[0]);
});
test('synthetic fixture screenshots and zero overflow at all requested widths and tabs', async ({ page, context }) => {
  const { errors } = await setup(page, context);
  await page.clock.install({ time: new Date('2026-01-04T03:00:00Z') });
  for (const width of [320, 360, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 }); await page.goto('/shop');
    await expect(page.getByLabel('이메일', { exact: true })).toBeVisible();
    await expect(page.getByText('웹 전용 이메일 로그인')).toBeVisible();
    await page.locator('.purchase-login img').evaluate(img => img.decode());
    await page.evaluate(() => document.fonts.ready);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (receipts) await page.screenshot({ path: join(receipts, `synthetic-login-${width}.png`), fullPage: true, animations: 'disabled' });
  }
  await login(page);
  for (const width of [320, 360, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const tab of ['홈', '구매', 'QR', '내역', '내정보']) {
      await page.getByRole('navigation').getByRole('button', { name: tab, exact: true }).click();
      await expect(page.getByRole('navigation').getByRole('button', { name: tab, exact: true })).toHaveAttribute('aria-current', 'page');
      const selected = page.getByRole('navigation').getByRole('button', { name: tab, exact: true });
      await expect(selected).toHaveCSS('color', 'rgb(91, 135, 255)');
      for (const other of ['홈', '구매', 'QR', '내역', '내정보'].filter(label => label !== tab))
        await expect(page.getByRole('navigation').getByRole('button', { name: other, exact: true })).toHaveCSS('color', 'rgb(138, 147, 166)');
      await page.evaluate(() => document.fonts.ready);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width} ${tab}`).toBe(true);
      if (receipts) await page.screenshot({ path: join(receipts, `synthetic-${width}-${tab}.png`), fullPage: true, animations: 'disabled' });
    }
    await page.getByRole('navigation').getByRole('button', { name: '구매', exact: true }).click();
    await page.getByRole('button', { name: '합성 10+1 식권 선택' }).click();
    await expect(page.locator('.purchase-quote')).toBeVisible();
    await expect(page.getByText('최종 결제 72,000원')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width} checkout`).toBe(true);
    if (receipts) await page.screenshot({ path: join(receipts, `synthetic-checkout-${width}.png`), fullPage: true, animations: 'disabled' });
    if (receipts) {
      await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
      const action = page.locator('.catalog-checkout > .purchase-card > button');
      const actionBox = await action.boundingBox(), navBox = await page.getByRole('navigation').boundingBox();
      expect(actionBox.y + actionBox.height, `${width} checkout action above tabs`).toBeLessThan(navBox.y);
      await page.screenshot({ path: join(receipts, `synthetic-checkout-action-${width}.png`), animations: 'disabled' });
      await page.evaluate(() => scrollTo(0, 0));
    }
    await page.getByRole('button', { name: '상품 다시 선택', exact: true }).click();
    await page.getByRole('navigation').getByRole('button', { name: '홈', exact: true }).click();
    await page.getByRole('button', { name: '쿠폰함', exact: true }).click();
    await expect(page.getByText('합성 할인')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width} coupons`).toBe(true);
    if (receipts) await page.screenshot({ path: join(receipts, `synthetic-coupons-${width}.png`), fullPage: true, animations: 'disabled' });
    await page.getByRole('button', { name: '홈으로', exact: true }).click();
  }
  expect(errors).toEqual([]);
});

for (const rejection of [
  { name: 'INVALID_QR', status: 400, json: { detail: { code: 'INVALID_QR', message: 'QR을 다시 스캔해 주세요' } } },
  { name: 'request validation', status: 422, json: { detail: [{ type: 'string_too_long', loc: ['body', 'qr_data'], msg: 'String should have at most 500 characters' }] } },
]) test(`trusted ${rejection.name} permits correction and clears saved intent on reload`, async ({ page, context }) => {
  await setup(page, context); const bodies = [];
  await page.route('**/api-fixture/transactions/scan', route => {
    bodies.push(route.request().postDataJSON());
    return bodies.length === 1 ? route.fulfill(rejection) : route.fulfill({ json: { result: 'success', pay_type: 'voucher', remaining: 11, transaction: { id: 'synthetic-consume' } } });
  });
  await login(page); await page.getByRole('navigation').getByRole('button', { name: 'QR', exact: true }).click();
  await page.getByLabel('매장 QR 내용').fill('wrong-qr'); await page.getByRole('button', { name: 'QR 결제 확인', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible(); await expect(page.getByLabel('매장 QR 내용')).toBeEnabled();
  expect(await page.evaluate(() => sessionStorage.getItem('greeneat-scan-pending:11111111-1111-4111-8111-111111111111'))).toBeNull();
  await page.reload(); await page.getByRole('navigation').getByRole('button', { name: 'QR', exact: true }).click();
  await expect(page.getByLabel('매장 QR 내용')).toBeEnabled();
  await page.getByLabel('매장 QR 내용').fill('corrected-qr'); await page.getByRole('button', { name: 'QR 결제 확인', exact: true }).click();
  await expect(page.getByRole('heading', { name: '사용 완료' })).toBeVisible();
  expect(bodies[1].qr_data).toBe('corrected-qr'); expect(bodies[1].idempotency_key).not.toBe(bodies[0].idempotency_key);
});
for (const response of [
  { name: 'unexpected 400', status: 400, json: { detail: { code: 'UNEXPECTED', message: '확인 필요' } } },
  { name: 'malformed validation', status: 422, json: { detail: [{ unexpected: true }] } },
  { name: 'malformed success', json: { result: 'success', pay_type: 'voucher' } },
  { name: 'empty transaction', json: { result: 'success', pay_type: 'voucher', remaining: 11, transaction: {} } },
  { name: 'wrong remaining type', json: { result: 'success', pay_type: 'voucher', remaining: '11', transaction: { id: 'synthetic-consume' } } },
  { name: 'malformed JSON', contentType: 'application/json', body: '{' },
  { name: 'untrusted INVALID_QR success status', json: { ok: false, error: { code: 'INVALID_QR' } } },
  { name: 'post-consumption auth error', status: 401, json: { detail: { code: 'UNAUTHENTICATED' } } },
]) test(`uncertain ${response.name} retains exact intent after reload`, async ({ page, context }) => {
  await setup(page, context); const bodies = [];
  await page.route('**/api-fixture/transactions/scan', route => { bodies.push(route.request().postDataJSON()); return route.fulfill(response); });
  await login(page); await page.getByRole('navigation').getByRole('button', { name: 'QR', exact: true }).click();
  await page.getByLabel('매장 QR 내용').fill('synthetic-qr'); await page.getByRole('button', { name: 'QR 결제 확인', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible(); await expect(page.getByLabel('매장 QR 내용')).toBeDisabled();
  await page.reload(); await page.getByRole('navigation').getByRole('button', { name: 'QR', exact: true }).click();
  await expect(page.getByLabel('매장 QR 내용')).toHaveValue('synthetic-qr');
  await page.getByRole('button', { name: '같은 요청으로 다시 확인', exact: true }).click(); await expect.poll(() => bodies.length).toBe(2);
  expect(bodies[1]).toEqual(bodies[0]);
});
test('scan storage write failure never sends consuming request', async ({ page, context }) => {
  const { calls } = await setup(page, context); await login(page);
  await page.evaluate(() => { const original = Storage.prototype.setItem; Storage.prototype.setItem = function(k,v) { if (k.startsWith('greeneat-scan-pending:')) throw new Error('synthetic storage unavailable'); return original.call(this,k,v); }; });
  await page.getByRole('navigation').getByRole('button', { name: 'QR', exact: true }).click();
  await page.getByLabel('매장 QR 내용').fill('synthetic-qr'); await page.getByRole('button', { name: 'QR 결제 확인', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible(); expect(calls.filter(c => c.path === '/transactions/scan')).toHaveLength(0);
});
test('voucher use history renders source count and meal date, not currency', async ({ page, context }) => {
  await setup(page, context); await login(page); await page.getByRole('navigation').getByRole('button', { name: '내역', exact: true }).click();
  await expect(page.locator('.usage-amount:visible')).toHaveText('−1장'); await expect(page.locator('.usage-row:visible p')).toContainText('중식 · 1월 2일 12:00');
});
test('scan safe rejection storage removal failure keeps intent and blocks new request', async ({ page, context }) => {
  await setup(page, context); const bodies = [];
  await page.route('**/api-fixture/transactions/scan', route => { bodies.push(route.request().postDataJSON()); return route.fulfill({ status: 400, json: { detail: { code: 'INVALID_QR' } } }); });
  await login(page);
  await page.evaluate(() => { const original = Storage.prototype.removeItem; Storage.prototype.removeItem = function(k) { if (k.startsWith('greeneat-scan-pending:')) throw new Error('synthetic remove failure'); return original.call(this,k); }; });
  await page.getByRole('navigation').getByRole('button', { name: 'QR', exact: true }).click();
  await page.getByLabel('매장 QR 내용').fill('synthetic-qr'); await page.getByRole('button', { name: 'QR 결제 확인', exact: true }).click();
  await expect(page.getByText('저장된 QR 요청을 확인할 수 없어요. 관리자에게 거래 확인을 요청해 주세요.')).toBeVisible();
  expect(bodies).toHaveLength(1);
  expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem('greeneat-scan-pending:11111111-1111-4111-8111-111111111111')))).toEqual(bodies[0]);
});
test('late scan response after logout cannot clear another account or first saved intent', async ({ page, context }) => {
  await setup(page, context); let held, body;
  await page.route('**/api-fixture/transactions/scan', route => { held = route; body = route.request().postDataJSON(); });
  await page.route('**/auth-fixture/auth/v1/logout', route => route.fulfill({ status: 204 }));
  await login(page); await page.getByRole('navigation').getByRole('button', { name: 'QR', exact: true }).click();
  await page.getByLabel('매장 QR 내용').fill('first-account-qr'); await page.getByRole('button', { name: 'QR 결제 확인', exact: true }).click();
  await expect.poll(() => !!held).toBe(true);
  await page.getByRole('navigation').getByRole('button', { name: '내정보', exact: true }).click();
  const signedOut = page.waitForResponse(response => response.url().includes('/auth/v1/logout'));
  await page.getByRole('button', { name: '로그아웃', exact: true }).click(); await signedOut;
  await expect.poll(() => page.evaluate(() => Object.keys(localStorage).every(k => !k.endsWith('auth-token')))).toBe(true);
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeVisible();
  const user = { id: '22222222-2222-4222-8222-222222222222', email: 'synthetic@example.invalid', aud: 'authenticated', role: 'authenticated' };
  await page.route('**/auth-fixture/auth/v1/token**', route => route.fulfill({ json: { access_token: 'second-synthetic', refresh_token: 'second-refresh', expires_in: 3600, token_type: 'bearer', user } }));
  await page.route('**/api-fixture/me', route => route.fulfill({ json: { ok: true, data: { user_id: user.id, role: 'customer', status: 'active', account_type: 'voucher', display_name: '다른 합성 구매자' } } }));
  await login(page); await page.getByRole('navigation').getByRole('button', { name: 'QR', exact: true }).click();
  await held.fulfill({ status: 400, json: { detail: { code: 'INVALID_QR' } } });
  await expect(page.getByLabel('매장 QR 내용')).toBeEnabled(); await expect(page.getByLabel('매장 QR 내용')).toHaveValue('');
  expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem('greeneat-scan-pending:11111111-1111-4111-8111-111111111111')))).toEqual(body);
  expect(await page.evaluate(() => sessionStorage.getItem('greeneat-scan-pending:22222222-2222-4222-8222-222222222222'))).toBeNull();
});
test('nonvoucher currency and voucher_id count use real history fields', async ({ page, context }) => {
  await setup(page, context);
  await page.route('**/api-fixture/me', route => route.fulfill({ json: { ok: true, data: { user_id: '11111111-1111-4111-8111-111111111111', role: 'customer', status: 'active', account_type: 'voucher', voucher_use_history: [], recent_transactions: [
    { id: 'direct', kind: 'payment', amount: 9000, title: '상품 결제', merchant_name: '합성 식당', created_at: '2026-01-02T09:30:00Z' },
    { id: 'id-only', voucher_id: 'synthetic-voucher', amount: 8000, title: '식권 사용', created_at: '2026-01-02T03:00:00Z' },
  ] } } }));
  await login(page); await page.getByRole('navigation').getByRole('button', { name: '내역', exact: true }).click();
  await expect(page.locator('.usage-amount:visible')).toHaveText(['−9,000원', '−1장']);
  await expect(page.locator('.usage-row:visible p')).toHaveText(['석식 · 1월 2일 18:30', '중식 · 1월 2일 12:00']);
  await expect(page.locator('.usage-day:visible')).toHaveText('1월 2일 (금)');
});
test('quote and consent survive native tab switch without making order', async ({ page, context }) => {
  const { calls } = await setup(page, context); await login(page);
  const nav = page.getByRole('navigation'); await nav.getByRole('button', { name: '구매', exact: true }).click();
  await page.getByRole('button', { name: '합성 10+1 식권 선택' }).click(); await expect(page.locator('.purchase-quote')).toBeVisible();
  await expect(page.getByText('최종 결제 72,000원')).toBeVisible();
  await page.getByLabel('구매 조건 확인').check();
  await nav.getByRole('button', { name: '홈', exact: true }).click(); await nav.getByRole('button', { name: '구매', exact: true }).click();
  await expect(page.getByText('최종 결제 72,000원')).toBeVisible();
  await expect(page.getByLabel('구매 조건 확인')).toBeChecked();
  expect(calls.filter(c => c.path.endsWith('/purchase'))).toHaveLength(0);
});
for (const pay_type of ['voucher', 'subsidized', 'ledger']) test(`real scan ${pay_type} root contract completes and clears intent`, async ({ page, context }) => {
  await setup(page, context);
  await page.route('**/api-fixture/transactions/scan', route => route.fulfill({ json: { result: 'success', pay_type, remaining: pay_type === 'ledger' ? null : 11, transaction: { id: 'synthetic-consume', amount: 8000 } } }));
  await login(page); await page.getByRole('navigation').getByRole('button', { name: 'QR', exact: true }).click();
  await page.getByLabel('매장 QR 내용').fill('synthetic-qr'); await page.getByRole('button', { name: 'QR 결제 확인', exact: true }).click();
  await expect(page.getByRole('heading', { name: '사용 완료' })).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem('greeneat-scan-pending:11111111-1111-4111-8111-111111111111'))).toBeNull();
});
test('registration endpoint refusal shows actual error without fabricating profile', async ({ page, context }) => {
  await setup(page, context); let calls = 0;
  await page.route('**/api-fixture/me', route => route.fulfill({ json: { ok: true, data: { status: 'no_profile' } } }));
  await page.route('**/api-fixture/consumer/register', route => { calls++; return route.fulfill({ status: 502, json: { detail: { code: 'SUPABASE_ERROR', message: '일반 사용자 등록 중 오류가 발생했어요' } } }); });
  await page.goto('/shop'); await page.getByLabel('이메일', { exact: true }).fill('synthetic@example.invalid'); await page.getByLabel('비밀번호', { exact: true }).fill('synthetic-password-only'); await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByLabel('이름', { exact: true }).fill('합성 구매자'); await page.getByLabel('휴대폰 번호').fill('01000000000');
  await page.getByLabel('약관 및 개인정보 처리방침 확인').check(); await page.getByRole('button', { name: '일반 구매자로 등록', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('일반 사용자 등록 중 오류가 발생했어요');
  await expect(page.getByRole('button', { name: '일반 구매자로 등록', exact: true })).toBeEnabled();
  await expect(page.getByRole('navigation')).toHaveCount(0); expect(calls).toBe(1);
});
test('catalog back returns home without consuming request'  , async ({ page, context }) => {
  const { calls } = await setup(page, context); await login(page);
  await page.getByRole('navigation').getByRole('button', { name: '구매', exact: true }).click(); await page.getByRole('button', { name: '홈으로', exact: true }).click();
  await expect(page.getByRole('navigation').getByRole('button', { name: '홈', exact: true })).toHaveAttribute('aria-current', 'page');
  expect(calls.filter(c => c.path.endsWith('/purchase') || c.path.endsWith('/scan'))).toHaveLength(0);
});
test('native profile notification and invite group states are truthful and not enabled' , async ({ page, context }) => {
  await setup(page, context); await login(page); await page.getByRole('navigation').getByRole('button', { name: '내정보', exact: true }).click();
  await expect(page.getByRole('button', { name: /결제 알림/ })).toBeDisabled(); await expect(page.getByRole('button', { name: /초대코드 입력/ })).toBeDisabled();
});
