import { openRecovery } from './recovery-navigation.mjs';
// Production bundle, synthetic account/pricing I/O only. No provider transport.
import { test, expect } from '@playwright/test';
const product = { id: 'auto-product', name: '자동 견적 식권', voucher_count: 10, bonus_count: 1, unit_price: 8000, sale_price: 72000, employee_pay_amount: 42000, total_company_subsidy_amount: 20000, total_restaurant_subsidy_amount: 10000, kiwoom_pay_method: 'TOTAL' };
const A = '11111111-1111-4111-8111-111111111111', B = '22222222-2222-4222-8222-222222222222';
function price(body, extra = {}) {
  const points = Math.min(body.requested_point_amount, 2000), discount = body.coupon_id ? 1000 : body.user_coupon_id ? 2000 : 0;
  return { product_id: body.product_id, merchant_id: 'auto-merchant', merchant_name: '합성 식당', purchase_mode: 'subsidized', gross_amount: 42000, coupon_discount_amount: discount, point_amount: points, payment_amount: 42000 - points - discount, ...extra };
}
async function setup(page) {
  const state = { owner: A, quotes: [], writes: [], handler: null, errors: [] };
  page.on('pageerror', e => state.errors.push(e.message));
  await page.context().route('**/*', route => new URL(route.request().url()).origin === 'http://127.0.0.1:4175' ? route.continue() : route.abort());
  await page.route('**/auth-fixture/auth/v1/**', route => {
    if (new URL(route.request().url()).pathname.endsWith('/logout')) return route.fulfill({ status: 204 });
    const user = { id: state.owner, email: 'automatic@example.invalid', aud: 'authenticated', role: 'authenticated' };
    return route.fulfill({ json: new URL(route.request().url()).pathname.endsWith('/user') ? user : { user, access_token: `fixture-${state.owner}`, refresh_token: 'fixture-only-refresh', expires_in: 3600, token_type: 'bearer' } });
  });
  await page.route('**/api-fixture/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api-fixture', '');
    let data = {};
    if (path === '/me') data = { user_id: state.owner, role: 'employee', status: 'active', company_id: 'auto-company', account_type: 'ledger', display_name: '합성 직원', point_balance: 5000, voucher_balance: 0, recent_transactions: [] };
    if (path === '/vouchers/products') data = { purchase_mode: 'subsidized', items: [product, { ...product, id: 'auto-product-B', name: '다른 식권' }] };
    if (path === '/coupons') data = { merchant: { id: 'auto-merchant', name: '합성 식당' }, items: [{ id: 'auto-public', name: '공개 할인', discount_type: 'fixed', discount_value: 1000 }], issued: [{ id: 'auto-issued', coupon_snapshot: { name: '보유 할인', discount_type: 'fixed', discount_value: 2000 } }] };
    if (path === '/vouchers/quote') {
      const body = route.request().postDataJSON(); state.quotes.push(body);
      if (state.handler) return state.handler(route, body);
      data = price(body);
    } else if (route.request().method() === 'POST') state.writes.push({ path, body: route.request().postDataJSON() });
    return route.fulfill({ json: { ok: true, data } });
  });
  await login(page);
  return state;
}
async function login(page) {
  await page.goto('/shop');
  await page.getByLabel('이메일', { exact: true }).fill('automatic@example.invalid');
  await page.getByLabel('비밀번호', { exact: true }).fill('synthetic-password-only');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('navigation').getByRole('button', { name: '구매', exact: true }).click();
}
const choose = page => page.getByRole('button', { name: `${product.name} 선택` }).click();
const total = page => page.locator('.quote-total');
async function noPayable(page) {
  await expect(page.locator('.purchase-quote')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '구매하기', exact: true })).toHaveCount(0);
}
test('rapid points debounce once; valid-invalid-valid rejects invalid RPC and normalizes without feedback', async ({ page }) => {
  const s = await setup(page); await choose(page);
  await expect(total(page)).toHaveText('최종 결제 42,000원');
  const points = page.getByLabel('사용 포인트');
  await points.fill('5'); await points.fill('50'); await points.fill('500'); await points.fill('5000');
  await noPayable(page);
  await expect(total(page)).toHaveText('최종 결제 40,000원');
  expect(s.quotes.map(q => q.requested_point_amount)).toEqual([0, 5000]);
  await expect(points).toHaveValue('5000');
  for (const invalid of ['-1', '', '1.5', '1e3', '100000001', '9007199254740992']) {
    await points.fill(invalid); await noPayable(page); await expect(page.getByRole('alert')).toContainText('0 이상의 정수');
  }
  expect(s.quotes).toHaveLength(2);
  await points.fill('1000'); await expect(total(page)).toHaveText('최종 결제 41,000원');
  expect(s.quotes.map(q => q.requested_point_amount)).toEqual([0, 5000, 1000]);
  expect(s.writes).toEqual([]); expect(s.errors).toEqual([]);
});
test('overlapping point and coupon requests resolve newest first; stale success/error cannot replace current money', async ({ page }) => {
  const s = await setup(page), pending = [];
  s.handler = (route, body) => { pending.push({ route, body }); };
  await choose(page); await expect.poll(() => pending.length).toBe(1);
  await page.getByLabel('사용 포인트').fill('1000'); await expect.poll(() => pending.length).toBe(2);
  await page.getByRole('radio', { name: '공개 할인', exact: true }).check(); await expect.poll(() => pending.length).toBe(3);
  await page.getByRole('radio', { name: '보유 할인', exact: true }).check(); await expect.poll(() => pending.length).toBe(4);
  await noPayable(page); await expect(page.getByText('금액 확인 중…', { exact: true })).toBeVisible();
  await pending[3].route.fulfill({ json: { ok: true, data: price(pending[3].body) } });
  await expect(total(page)).toHaveText('최종 결제 39,000원');
  await pending[2].route.fulfill({ status: 409, json: { detail: { message: 'stale coupon refusal' } } });
  for (const i of [1, 0]) await pending[i].route.fulfill({ json: { ok: true, data: price(pending[i].body) } });
  await expect(total(page)).toHaveText('최종 결제 39,000원');
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(s.quotes.at(-1)).toEqual({ product_id: product.id, requested_point_amount: 1000, user_coupon_id: 'auto-issued' });
  expect(s.writes).toEqual([]);
});
test('product response race and return reset never resurrect old detail or automatically place order', async ({ page }) => {
  const s = await setup(page), pending = [];
  s.handler = (route, body) => { pending.push({ route, body }); };
  await choose(page); await expect.poll(() => pending.length).toBe(1);
  await page.getByRole('button', { name: '상품 다시 선택' }).click();
  await page.getByRole('button', { name: '다른 식권 선택' }).click(); await expect.poll(() => pending.length).toBe(2);
  await pending[1].route.fulfill({ json: { ok: true, data: price(pending[1].body, { gross_amount: 43000, payment_amount: 43000 }) } });
  await expect(total(page)).toHaveText('최종 결제 43,000원');
  await pending[0].route.fulfill({ json: { ok: true, data: price(pending[0].body) } });
  await expect(total(page)).toHaveText('최종 결제 43,000원');
  await page.getByRole('button', { name: '상품 다시 선택' }).click(); await noPayable(page);
  expect(s.quotes).toHaveLength(2); expect(s.writes).toEqual([]);
});
test('quote failure retries only pricing, preserves coupon, and wrong merchant remains unpayable', async ({ page }) => {
  const s = await setup(page); await choose(page); await expect(total(page)).toBeVisible();
  s.handler = route => route.fulfill({ status: 409, json: { detail: { message: 'coupon rejected' } } });
  await page.getByRole('radio', { name: '보유 할인', exact: true }).check();
  await expect(page.getByRole('alert')).toContainText('coupon rejected'); await noPayable(page);
  await expect(page.getByRole('radio', { name: '보유 할인', exact: true })).toBeChecked();
  s.handler = (route, body) => route.fulfill({ json: { ok: true, data: price(body, { merchant_id: 'wrong-merchant' }) } });
  await page.getByRole('button', { name: '금액 다시 확인', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('상품·식당'); await noPayable(page);
  s.handler = null;
  await page.getByRole('button', { name: '금액 다시 확인', exact: true }).click();
  await expect(total(page)).toHaveText('최종 결제 40,000원');
  expect(s.quotes.slice(1).every(q => q.user_coupon_id === 'auto-issued')).toBe(true);
  expect(s.quotes).toHaveLength(4); expect(s.writes).toEqual([]);
});
test('logout and different account discard old pending quote including late response', async ({ page }) => {
  const s = await setup(page), pending = [];
  s.handler = (route, body) => { pending.push({ route, body }); };
  await choose(page); await expect.poll(() => pending.length).toBe(1);
  await page.getByRole('navigation').getByRole('button', { name: '내정보', exact: true }).click();
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeVisible();
  s.owner = B; s.handler = null;
  await login(page); await choose(page); await expect(total(page)).toHaveText('최종 결제 42,000원');
  await pending[0].route.fulfill({ json: { ok: true, data: price(pending[0].body, { gross_amount: 99999, payment_amount: 99999 }) } });
  await expect(total(page)).toHaveText('최종 결제 42,000원');
  await expect(page.getByLabel('구매 조건 확인')).not.toBeChecked(); expect(s.writes).toEqual([]); expect(s.errors).toEqual([]);
});
test.describe('accepted normalized point authority', () => {
  test.use({ userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148' });
  test('purchase caps a dynamic balance-normalized quote without changing the requested input', async ({ page }) => {
    const s = await setup(page); await choose(page);
    await page.getByLabel('사용 포인트').fill('5000');
    await expect(total(page)).toHaveText('최종 결제 40,000원');
    await expect(page.getByLabel('사용 포인트')).toHaveValue('5000');
    await expect(page.locator('.purchase-quote')).toContainText('포인트 사용 2,000P');
    await page.getByLabel('구매 조건 확인').check();
    await page.getByRole('button', { name: '구매하기', exact: true }).click();
    await expect.poll(() => s.writes.length).toBe(1);
    expect(s.writes).toEqual([{ path: '/vouchers/purchase-subsidized', body: { product_id: product.id, requested_point_amount: 2000 } }]);
    await openRecovery(page);await expect(page.getByRole('heading', { name: '주문 상태 확인 필요' })).toBeVisible();
    expect(s.quotes.at(-1).requested_point_amount).toBe(5000);
    expect(s.errors).toEqual([]);
  });
});
test('quote timeout is bounded and error-only retry never creates an order', async ({ page }) => {
  const s = await setup(page); s.handler = () => {};
  await choose(page);
  await expect(page.getByRole('alert')).toBeVisible({ timeout: 13000 });
  await expect(page.getByText('금액 확인 중…', { exact: true })).toHaveCount(0);
  await noPayable(page);
  s.handler = null; await page.getByRole('button', { name: '금액 다시 확인', exact: true }).click();
  await expect(total(page)).toHaveText('최종 결제 42,000원'); expect(s.quotes).toHaveLength(2); expect(s.writes).toEqual([]);
});
