import { test, expect } from '@playwright/test';

// Member-QR flow: buyer shows a signed 81-digit QR, counter scanner types it + Enter.
const CODE = '81' + '0'.repeat(37) + '12345678' + '1'.repeat(34);
const user = { id: '11111111-1111-4111-8111-111111111111', email: 'fixture@example.invalid', aud: 'authenticated', role: 'authenticated' };

async function base(page) {
  await page.context().route('**/*', route => new URL(route.request().url()).origin === 'http://127.0.0.1:4175' ? route.continue() : route.abort());
  await page.route('**/auth-fixture/auth/v1/**', route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith('/user') ? user : { access_token: 'fixture-access', refresh_token: 'fixture-refresh', expires_in: 3600, token_type: 'bearer', user } }));
}

test('buyer QR tab shows a locally drawn member QR that turns into "used" when the balance drops', async ({ page }) => {
  await base(page);
  let balance = 5, issued = 0;
  await page.route('**/api-fixture/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api-fixture', '');
    if (path === '/transactions/member-qr') { issued++; return route.fulfill({ json: { ok: true, data: { code: CODE, expires_at: Math.floor(Date.now() / 1000) + 60, ttl: 60 } } }); }
    if (path === '/me') return route.fulfill({ json: { ok: true, data: { user_id: user.id, role: 'customer', status: 'active', display_name: '김구매', account_type: 'voucher', voucher_balance: balance, point_balance: 0, voucher_use_history: [], recent_transactions: [] } } });
    return route.fulfill({ json: { ok: true, data: path === '/vouchers/products' ? { purchase_mode: 'voucher', items: [] } : {} } });
  });
  await page.goto('/shop');
  await page.getByLabel('이메일', { exact: true }).fill('fixture@example.invalid');
  await page.getByLabel('비밀번호', { exact: true }).fill('mock-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('navigation', { name: '구매자 탭' }).getByRole('button', { name: 'QR', exact: true }).click();
  await expect(page.getByRole('tab', { name: '내 QR 보여주기' })).toHaveAttribute('aria-selected', 'true');
  const qr = page.getByRole('img', { name: '식권 사용 QR 코드' });
  await expect(qr.locator('svg')).toBeVisible();
  await expect(page.getByText(/초 후 새 QR로 바뀌어요/)).toBeVisible();
  expect(issued).toBe(1);
  // No third-party QR image service is contacted.
  expect(await page.evaluate(() => performance.getEntriesByType('resource').some(e => /qrserver|googleapis|chart/.test(e.name)))).toBe(false);
  balance = 4; // counter redeemed one voucher
  await expect(page.getByRole('status').filter({ hasText: '식권 1장 사용 완료' })).toBeVisible({ timeout: 8000 });
  await expect(page.getByText('남은 식권 4장')).toBeVisible();
  await page.getByRole('tab', { name: '매장 QR로 결제' }).click();
  await expect(page.getByLabel('매장 QR 내용')).toBeVisible();
});

test('counter: scanner keyboard input + Enter redeems once, shows result, ignores a repeat in-flight scan', async ({ page }) => {
  await base(page);
  const bodies = [];
  await page.route('**/api-fixture/transactions/member-qr/redeem', async route => {
    bodies.push(route.request().postDataJSON());
    await new Promise(r => setTimeout(r, 150));
    return route.fulfill({ json: { ok: true, data: { result: 'success', duplicate: bodies.length > 1, pay_type: 'voucher', member_name: '김구매', remaining: 4, amount: 7000 } } });
  });
  await page.goto('/counter');
  await page.getByLabel('이메일').fill('owner@example.invalid');
  await page.getByLabel('비밀번호').fill('mock-only-password');
  await page.getByRole('button', { name: '로그인' }).click();
  await expect(page.getByRole('heading', { name: 'QR은 스캐너에 대 주세요' })).toBeVisible();
  // Input stays focused without clicking; scanner types like a keyboard.
  await expect(page.locator('#counter-code')).toBeFocused();
  // Idle demo uses real app screenshots; all three load.
  for (const img of await page.locator('.counter-demo img').all()) expect(await img.evaluate(i => i.complete && i.naturalWidth > 0)).toBe(true);
  await page.keyboard.type(CODE + '\n', { delay: 1 });
  await page.keyboard.type(CODE + '\n', { delay: 1 }); // double read while first is in flight
  await expect(page.getByRole('heading', { name: '식권 1장 사용 완료' })).toBeVisible();
  await expect(page.locator('.counter-name')).toHaveText('김구매님');
  // Readable on the dark counter background (global admin h1 color must not leak in).
  await expect(page.getByRole('heading', { name: '식권 1장 사용 완료' })).toHaveCSS('color', 'rgb(255, 255, 255)');
  await expect(page.getByRole('list', { name: '최근 사용' })).toContainText('김구매님');
  await expect(page.getByText('남은 식권 4장').first()).toBeVisible();
  expect(bodies[0]).toEqual({ code: CODE });
  expect(bodies.length).toBe(1);
  await expect(page.getByRole('heading', { name: 'QR은 스캐너에 대 주세요' })).toBeVisible({ timeout: 6000 });
  await expect(page.locator('#counter-code')).toBeFocused();
});

test('counter shows clear errors: no voucher, expired, store QR scanned', async ({ page }) => {
  await base(page);
  const answers = [
    { status: 402, json: { detail: { code: 'NO_VOUCHER', message: '보유 식권이 없습니다' } } },
    { status: 400, json: { detail: { code: 'MEAL_QR_EXPIRED', message: 'x' } } },
  ];
  let calls = 0;
  await page.route('**/api-fixture/transactions/member-qr/redeem', route => route.fulfill(answers[calls++]));
  await page.goto('/counter');
  await page.getByLabel('이메일').fill('owner@example.invalid');
  await page.getByLabel('비밀번호').fill('mock-only-password');
  await page.getByRole('button', { name: '로그인' }).click();
  await page.locator('#counter-code').waitFor({ state: 'attached' });
  await page.keyboard.type(CODE + '\n');
  await expect(page.getByRole('heading', { name: '남은 식권이 없어요' })).toBeVisible();
  await page.keyboard.type(CODE + '\n');
  await expect(page.getByRole('heading', { name: 'QR 시간이 지났어요' })).toBeVisible();
  await page.keyboard.type('QR-DONTO\n'); // store QR: never sent
  await page.waitForTimeout(300);
  expect(calls).toBe(2);
});

test('zero vouchers: QR tab and home QR button open a purchase popup instead of the QR', async ({ page }) => {
  await base(page);
  let issued = 0;
  await page.route('**/api-fixture/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api-fixture', '');
    if (path === '/transactions/member-qr') { issued++; return route.fulfill({ json: { ok: true, data: { code: CODE, expires_at: Math.floor(Date.now() / 1000) + 60, ttl: 60 } } }); }
    if (path === '/me') return route.fulfill({ json: { ok: true, data: { user_id: user.id, role: 'customer', status: 'active', display_name: '김구매', account_type: 'voucher', voucher_balance: 0, point_balance: 0, voucher_use_history: [], recent_transactions: [] } } });
    return route.fulfill({ json: { ok: true, data: path === '/vouchers/products' ? { purchase_mode: 'voucher', items: [] } : {} } });
  });
  await page.goto('/shop');
  await page.getByLabel('이메일', { exact: true }).fill('fixture@example.invalid');
  await page.getByLabel('비밀번호', { exact: true }).fill('mock-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  const nav = page.getByRole('navigation', { name: '구매자 탭' });
  await nav.getByRole('button', { name: 'QR', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '식권이 없어요' });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole('heading', { name: '내 식권 QR' })).toHaveCount(0);
  expect(issued).toBe(0);
  await dialog.getByRole('button', { name: '닫기' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('.meal-ticket')).toBeVisible(); // still on 홈
  await page.locator('.ticket-qr').click(); // home card QR button is guarded too
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: '식권 구매하기' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(nav.getByRole('button', { name: '구매', exact: true })).toHaveAttribute('aria-current', 'page');
  expect(issued).toBe(0);
});
