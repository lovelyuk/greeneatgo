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
  // No text field holds focus (a focused field opens the on-screen keyboard on TV boxes);
  // the scanner's keys are read from the document.
  await expect(page.locator('input, textarea')).toHaveCount(0);
  expect(await page.evaluate(() => ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName))).toBe(false);
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
  expect(await page.evaluate(() => ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName))).toBe(false);
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
  await expect(page.getByRole('heading', { name: 'QR은 스캐너에 대 주세요' })).toBeVisible();
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

test('counter kiosk: installable manifest, offline banner, hold-to-logout', async ({ page, context }) => {
  await base(page);
  await page.goto('/counter');
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute('href', '/counter/manifest.webmanifest');
  const manifest = await (await page.request.get('/counter/manifest.webmanifest')).json();
  expect(manifest).toMatchObject({ start_url: '/counter', scope: '/counter', display: 'fullscreen', orientation: 'landscape' });
  for (const icon of manifest.icons) expect((await page.request.get(icon.src)).status()).toBe(200);
  await page.getByLabel('이메일').fill('owner@example.invalid');
  await page.getByLabel('비밀번호').fill('mock-only-password');
  await page.getByRole('button', { name: '로그인' }).click();
  await expect(page.getByRole('status', { name: '인터넷 연결됨' })).toBeVisible();
  await context.setOffline(true);
  await expect(page.getByRole('alert').filter({ hasText: '인터넷 연결이 끊겼어요' })).toBeVisible();
  await expect(page.getByRole('status', { name: '인터넷 연결 끊김' })).toBeVisible();
  await context.setOffline(false);
  await expect(page.getByRole('alert').filter({ hasText: '인터넷 연결이 끊겼어요' })).toHaveCount(0);
  // A quick tap does not log out; holding does.
  const logout = page.getByRole('button', { name: '길게 눌러 로그아웃' });
  await logout.click();
  await page.waitForTimeout(300);
  await expect(page.getByRole('heading', { name: 'QR은 스캐너에 대 주세요' })).toBeVisible();
  expect(await page.evaluate(() => ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName))).toBe(false);
  const box = await logout.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down(); await page.waitForTimeout(1700); await page.mouse.up();
  await expect(page.getByRole('heading', { name: '식권 스캔 카운터' })).toBeVisible();
  await expect(page.getByLabel('비밀번호')).toBeVisible();
});

test('counter: kiosk paper receipt QR (24 hex) goes to the kiosk endpoint, second scan says already used', async ({ page }) => {
  await base(page);
  const R = '6ad6e86b3bea82fef79ff23b';
  const calls = [];
  await page.clock.install();
  await page.route('**/api-fixture/transactions/**', route => {
    const url = new URL(route.request().url());
    calls.push([url.pathname.replace('/api-fixture', ''), route.request().postDataJSON()]);
    return calls.length === 1
      ? route.fulfill({ json: { ok: true, data: { result: 'success', kind: 'kiosk_receipt', receipt_id: R } } })
      : route.fulfill({ status: 409, json: { detail: { code: 'KIOSK_RECEIPT_USED', message: 'x' } } });
  });
  await page.goto('/counter');
  await page.getByLabel('이메일').fill('owner@example.invalid');
  await page.getByLabel('비밀번호').fill('mock-only-password');
  await page.getByRole('button', { name: '로그인' }).click();
  await expect(page.getByRole('heading', { name: 'QR은 스캐너에 대 주세요' })).toBeVisible();
  await page.keyboard.type(R + '\n');
  await expect(page.getByRole('heading', { name: '키오스크 식권 사용 완료' })).toBeVisible();
  expect(calls[0]).toEqual(['/transactions/kiosk-receipt/redeem', { code: R }]);
  await expect(page.getByRole('list', { name: '최근 사용' })).toContainText('키오스크 영수증');
  // Still held at the scanner: re-reads are ignored without asking the server.
  await page.keyboard.type(R + '\n');
  await page.waitForTimeout(400);
  expect(calls.length).toBe(1);
  await expect(page.getByRole('heading', { name: '키오스크 식권 사용 완료' })).toBeVisible();
  // Scanned again after a real pause: the server answers and the warning shows.
  await page.clock.fastForward(11000);
  await page.keyboard.type(R + '\n');
  await expect(page.getByRole('heading', { name: '이미 사용된 영수증이에요' })).toBeVisible();
  expect(calls.length).toBe(2);
});

test('counter: a QR held at the scanner stays "used"; the next guest is served at once; a later re-scan warns', async ({ page }) => {
  await base(page);
  const OTHER = '81' + '0'.repeat(37) + '87654321' + '2'.repeat(34);
  const bodies = [];
  await page.route('**/api-fixture/transactions/member-qr/redeem', route => {
    const body = route.request().postDataJSON();
    const duplicate = bodies.some(b => b.code === body.code);
    bodies.push(body);
    return route.fulfill({ json: { ok: true, data: { result: 'success', duplicate, pay_type: 'voucher', member_name: body.code === CODE ? '김구매' : '이손님', remaining: 4, amount: 7000 } } });
  });
  await page.clock.install();
  await page.goto('/counter');
  await page.getByLabel('이메일').fill('owner@example.invalid');
  await page.getByLabel('비밀번호').fill('mock-only-password');
  await page.getByRole('button', { name: '로그인' }).click();
  await expect(page.getByRole('heading', { name: 'QR은 스캐너에 대 주세요' })).toBeVisible();
  await page.keyboard.type(CODE + '\n', { delay: 1 });
  await expect(page.getByRole('heading', { name: '식권 1장 사용 완료' })).toBeVisible();
  // Re-reads every few seconds for longer than the window: each one extends it.
  for (let i = 0; i < 4; i++) {
    await page.clock.fastForward(4000);
    await page.keyboard.type(CODE + '\n', { delay: 1 });
    await page.clock.fastForward(300);
    await expect(page.getByRole('heading', { name: '이미 사용 처리된 QR이에요' })).toHaveCount(0);
  }
  expect(bodies.length).toBe(1);
  await expect(page.getByRole('list', { name: '최근 사용' }).getByRole('listitem')).toHaveCount(1);
  // Another guest right behind is not held up.
  await page.keyboard.type(OTHER + '\n', { delay: 1 });
  await expect(page.locator('.counter-name')).toHaveText('이손님님');
  expect(bodies.length).toBe(2);
  // The first QR again after a real pause: asked, and reported as already used.
  await page.clock.fastForward(11000);
  await page.keyboard.type(CODE + '\n', { delay: 1 });
  await expect(page.getByRole('heading', { name: '이미 사용 처리된 QR이에요' })).toBeVisible();
  expect(bodies.length).toBe(3);
});

test('counter reads the scanner without a text field: no Enter suffix, focus on a button, IME-masked keys', async ({ page }) => {
  await base(page);
  const bodies = [];
  await page.route('**/api-fixture/transactions/member-qr/redeem', route => {
    bodies.push(route.request().postDataJSON());
    return route.fulfill({ json: { ok: true, data: { result: 'success', duplicate: false, pay_type: 'voucher', member_name: '김구매', remaining: 3, amount: 7000 } } });
  });
  await page.goto('/counter');
  await page.getByLabel('이메일').fill('owner@example.invalid');
  await page.getByLabel('비밀번호').fill('mock-only-password');
  await page.getByRole('button', { name: '로그인' }).click();
  await expect(page.getByRole('heading', { name: 'QR은 스캐너에 대 주세요' })).toBeVisible();
  // Nothing editable on the page, so no device can raise its on-screen keyboard.
  await expect(page.locator('input, textarea, [contenteditable]')).toHaveCount(0);
  // Scanner without an Enter suffix: the code is sent once typing stops.
  await page.keyboard.type(CODE, { delay: 1 });
  await expect(page.getByRole('heading', { name: '식권 1장 사용 완료' })).toBeVisible();
  expect(bodies).toEqual([{ code: CODE }]);
  // Focus parked on the logout button (a tap, or a TV remote) must not swallow the scan or log out.
  // (Different guests' codes: a repeat of the code just used is ignored for 10 s.)
  const SECOND = '81' + '0'.repeat(37) + '22222222' + '3'.repeat(34), THIRD = '81' + '0'.repeat(37) + '33333333' + '4'.repeat(34);
  await page.getByRole('button', { name: '길게 눌러 로그아웃' }).focus();
  await page.keyboard.type(SECOND + '\n', { delay: 1 });
  await expect.poll(() => bodies.length).toBe(2);
  await expect(page.getByLabel('이메일')).toHaveCount(0);
  await page.waitForTimeout(400); // let the second answer land; scans during a request are ignored by design
  // IME on: the browser reports key "Process"; the physical key code is used instead.
  await page.evaluate(code => {
    for (const d of code) document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Process', code: 'Digit' + d, bubbles: true }));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
  }, THIRD);
  await expect.poll(() => bodies.length).toBe(3);
  expect(bodies[2]).toEqual({ code: THIRD });
});
