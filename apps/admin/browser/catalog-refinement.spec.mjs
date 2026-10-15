// Synthetic fixtures against the production Vite bundle. All external I/O blocked.
import { test, expect } from '@playwright/test';
const product = { id: 'refinement-product', name: '테스트 10+1 식권', voucher_count: 10, bonus_count: 1, total_count: 11, unit_price: 8000, sale_price: 72000, discount_rate: 10, kiwoom_pay_method: 'BANK', is_event: true };
async function fixture(page, employee = false) {
  const quotes = [];
  await page.context().route('**/*', route => new URL(route.request().url()).origin === 'http://127.0.0.1:4175' ? route.continue() : route.abort());
  const user = { id: '11111111-1111-4111-8111-111111111111', email: 'fixture@example.invalid', aud: 'authenticated', role: 'authenticated' };
  await page.route('**/auth-fixture/auth/v1/**', route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith('/user') ? user : { access_token: 'fixture-access', refresh_token: 'fixture-refresh', expires_in: 3600, token_type: 'bearer', user } }));
  await page.route('**/api-fixture/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api-fixture', '');
    let data = {};
    if (path === '/me') data = { user_id: user.id, role: employee ? 'employee' : 'customer', status: 'active', display_name: '테스트 구매자', point_balance: 2000, voucher_balance: 3, account_type: employee ? 'ledger' : 'voucher', voucher_use_history: [], recent_transactions: [] };
    if (path === '/vouchers/products') data = { purchase_mode: employee ? 'subsidized' : 'voucher', items: [{ ...product, ...(employee ? { employee_pay_amount: 42000, total_company_subsidy_amount: 20000, total_restaurant_subsidy_amount: 10000 } : {}) }] };
    if (path === '/coupons') data = { merchant: { id: 'merchant-fixture', name: '테스트 식당' }, items: [{ id: 'public-fixture', name: '공개 할인', discount_type: 'fixed', discount_value: 1000 }], issued: [{ id: 'issued-fixture', coupon_snapshot: { name: '보유 할인', discount_type: 'percent', discount_value: '5' }, valid_until: '2026-12-31', status: 'available' }] };
    if (path === '/vouchers/quote') {
      const body = route.request().postDataJSON(); quotes.push(body);
      if (body.user_coupon_id) return route.fulfill({ status: 409, json: { detail: { code: 'COUPON_UNAVAILABLE', message: 'fixture coupon refusal' } } });
      const gross = employee ? 42000 : 72000, points = employee ? Math.min(body.requested_point_amount, 2000) : 0, discount = body.coupon_id ? 1000 : 0;
      data = { merchant_id: 'merchant-fixture', merchant_name: '테스트 식당', product_id: product.id, purchase_mode: employee ? 'subsidized' : 'voucher', gross_amount: gross, coupon_discount_amount: discount, point_amount: points, payment_amount: gross - points - discount };
    }
    return route.fulfill({ json: { ok: true, data } });
  });
  await page.goto('/shop');
  await page.getByLabel('이메일', { exact: true }).fill('fixture@example.invalid');
  await page.getByLabel('비밀번호', { exact: true }).fill('mock-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('navigation', { name: '구매자 탭' }).getByRole('button', { name: '구매', exact: true }).click();
  return quotes;
}
test('selecting a product automatically prices once without a confirmation button or order', async ({ page }, testInfo) => {
  const quotes = await fixture(page);
  const writes = [];
  page.on('request', r => { if (/\/purchase(?:-subsidized)?$|\/sdk|\/payments\//.test(r.url())) writes.push(r.url()); });
  await page.getByRole('button', { name: `${product.name} 선택` }).click();
  await expect(page.locator('.quote-total')).toHaveText('최종 결제 72,000원');
  await expect(page.getByRole('button', { name: '견적 확인', exact: true })).toHaveCount(0);
  expect(quotes).toEqual([{ product_id: product.id, requested_point_amount: 0 }]);
  expect(writes).toEqual([]);
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`automatic-quote-${width}.png`), fullPage: true, animations: 'disabled' });
  }
});
test('leaving purchase while price is pending discards hidden response and requires fresh pricing on return', async ({ page }) => {
  await fixture(page);
  const pending = [];
  await page.route('**/api-fixture/vouchers/quote', route => pending.push(route));
  await page.getByRole('button', { name: `${product.name} 선택` }).click();
  await expect.poll(() => pending.length).toBe(1);
  const nav = page.getByRole('navigation');
  await nav.getByRole('button', { name: '홈', exact: true }).click();
  await pending[0].fulfill({ json: { ok: true, data: { product_id: product.id, merchant_id: 'merchant-fixture', merchant_name: '테스트 식당', purchase_mode: 'voucher', gross_amount: 72000, point_amount: 0, coupon_discount_amount: 0, payment_amount: 72000 } } });
  await nav.getByRole('button', { name: '구매', exact: true }).click();
  await expect(page.locator('.purchase-quote')).toHaveCount(0);
  await expect.poll(() => pending.length).toBe(2);
  await page.getByRole('button', { name: '상품 다시 선택' }).click();
  await pending[1].fulfill({ json: { ok: true, data: { product_id: product.id, merchant_id: 'merchant-fixture', merchant_name: '테스트 식당', purchase_mode: 'voucher', gross_amount: 72000, point_amount: 0, coupon_discount_amount: 0, payment_amount: 72000 } } });
  await expect(page.locator('.purchase-quote')).toHaveCount(0);
});
test('native catalog ticket geometry and header count at every supported width', async ({ page }, testInfo) => {
  await fixture(page);
  const ticket = page.getByRole('button', { name: `${product.name} 선택` });
  await expect(page.locator('.catalog-count')).toHaveText('1종');
  await expect(ticket.locator('.product-rail')).toHaveText('TICKET');
  await expect(ticket).toContainText('11장 식권');
  await expect(ticket).toContainText('결제방법 계좌이체 전용 · 보너스 1장');
  for (const width of [320, 360, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(ticket).toHaveCSS('height', '154px');
    await expect(ticket.locator('.product-price')).toHaveCSS('font-size', '30px');
    const styles = await ticket.evaluate(el => ({ gradient: getComputedStyle(el).backgroundImage, notch: getComputedStyle(el, '::before').width, rail: getComputedStyle(el.querySelector('.product-rail')).width }));
    expect(styles.gradient).toContain('105, 72, 239'); expect(styles.notch).toBe('18px'); expect(styles.rail).toBe('60px');
    const sizes = await page.locator('.purchase-products').boundingBox(), box = await ticket.boundingBox(); expect(box.width).toBe(sizes.width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.setViewportSize({ width: 360, height: 900 });
  await page.screenshot({ path: testInfo.outputPath('catalog-360-synthetic.png'), fullPage: true, animations: 'disabled' });
});
test('radio tickets preserve public and issued identities; refusal never silently retries no-coupon', async ({ page }, testInfo) => {
  const quotes = await fixture(page);
  await page.getByRole('button', { name: `${product.name} 선택` }).click();
  await expect(page.getByRole('radio', { name: '쿠폰 사용 안 함' })).toBeChecked();
  await expect(page.locator('.selection-coupon-ticket.issued')).toHaveCSS('height', '192px');
  await expect(page.locator('.selection-coupon-ticket.issued')).toContainText('5%');
  await expect(page.locator('.selection-coupon-ticket:not(.issued)')).toHaveCSS('height', '154px');
  await expect(page.locator('.quote-total')).toHaveText('최종 결제 72,000원');
  expect(quotes).toHaveLength(1);
  await page.getByRole('radio', { name: '공개 할인', exact: true }).check();
  await expect(page.getByLabel('할인 쿠폰', { exact: true })).toHaveValue('public:public-fixture');
  await expect(page.locator('.purchase-quote .quote-total')).toHaveText('최종 결제 71,000원');
  expect(quotes).toEqual([{ product_id: product.id, requested_point_amount: 0 }, { product_id: product.id, requested_point_amount: 0, coupon_id: 'public-fixture' }]);
  await expect(page.getByRole('button', { name: '구매하기', exact: true })).toBeDisabled();
  await page.getByLabel('구매 조건 확인').check();
  await expect(page.getByRole('button', { name: '구매하기', exact: true })).toBeEnabled();
  for (const width of [320, 360, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.setViewportSize({ width: 360, height: 900 });
  await page.screenshot({ path: testInfo.outputPath('discount-360-synthetic.png'), fullPage: true, animations: 'disabled' });
  await page.getByLabel('할인 쿠폰', { exact: true }).selectOption('issued:issued-fixture');
  await expect(page.getByRole('radio', { name: '보유 할인', exact: true })).toBeChecked();
  await expect(page.locator('.purchase-quote')).toHaveCount(0);
  await expect(page.getByRole('alert')).toContainText('fixture coupon refusal');
  expect(quotes).toHaveLength(3); expect(quotes[2].user_coupon_id).toBe('issued-fixture'); expect(quotes[2].coupon_id).toBeUndefined();
  await expect(page.getByRole('radio', { name: '보유 할인', exact: true })).toBeChecked();
  await expect(page.getByRole('button', { name: '구매하기', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '상품 다시 선택' }).click();
  await expect(page.locator('.catalog-count')).toHaveText('1종');
});
test('employee point intent automatically prices; server bounds authoritative and edits invalidate compact quote', async ({ page }) => {
  const quotes = await fixture(page, true);
  await page.getByRole('button', { name: `${product.name} 선택` }).click();
  await expect(page.getByRole('button', { name: '최대', exact: true })).toHaveCount(0);
  await page.getByLabel('사용 포인트').fill('-1');
  await expect(page.getByRole('alert')).toContainText('0 이상의 정수'); expect(quotes).toHaveLength(0);
  await page.getByLabel('사용 포인트').fill('5000');
  await expect(page.locator('.quote-total')).toHaveText('최종 결제 40,000원');
  expect(quotes[0].requested_point_amount).toBe(5000);
  await expect(page.locator('.purchase-quote')).toContainText('포인트 사용 2,000P');
  await expect(page.locator('.quote-row').first()).toHaveCSS('display', 'flex');
  await expect(page.locator('.catalog-checkout button', { hasText: '구매하기' })).toHaveCSS('height', '54px');
  await page.getByLabel('사용 포인트').fill('1000'); await expect(page.locator('.purchase-quote')).toHaveCount(0); expect(quotes).toHaveLength(1);
});
test('home wallet metrics and action sizing use source values without 320px overflow', async ({ page }) => {
  await fixture(page);
  await page.getByRole('navigation').getByRole('button', { name: '홈', exact: true }).click();
  await expect(page.locator('.ticket-wallet strong').first()).toHaveCSS('font-size', '14px');
  await expect(page.locator('.ticket-bottom strong')).toHaveCSS('font-size', '14px');
  await expect(page.locator('.ticket-bottom button')).toHaveCSS('height', '48px');
  await page.setViewportSize({ width: 360, height: 900 });
  await expect(page.locator('.ticket-wallet strong').first()).toHaveCSS('font-size', '14px');
  await expect(page.locator('.ticket-wallet button')).toHaveCSS('width', '140px');
  await page.setViewportSize({ width: 320, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
