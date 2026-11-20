// SYNTHETIC fixtures only. Every nonlocal request is blocked.
import { test, expect } from '@playwright/test';
test.use({ timezoneId: 'Asia/Seoul' });

const user = { id: '11111111-1111-4111-8111-111111111111', email: 'synthetic@example.invalid', aud: 'authenticated', role: 'authenticated' };
const SLIP = 'https://agent.kiwoompay.co.kr/common/PayInfoPrintDirectCard.jsp?DAOUTRX=SYNTH1&STATUS=A';
const orders = [
  { order_id: 'GE-V-synthetic-2', product_name: '합성 11장 식권', merchant_id: 'm1', merchant_name: '합성 한식뷔페', amount: 80000, status: 'done', pay_type: 'voucher', method: 'CARD', method_label: '카드', voucher_count: 11, approved_at: '2026-11-19T03:08:00+00:00', has_receipt: true },
  { order_id: 'GE-V-synthetic-1', product_name: '합성 1장 식권', merchant_id: 'm2', merchant_name: '합성 국수집', amount: 7500, status: 'refunded', pay_type: 'voucher', method: 'NAVERPAY', method_label: '네이버페이', voucher_count: 1, approved_at: '2026-11-18T03:08:00+00:00', has_receipt: true },
];
const receipt = (order, refund = null) => ({
  summary: order, slip_title: '카드 매출전표', refund,
  completion: {
    order_id: order.order_id, status: order.status, product_name: order.product_name, merchant_name: order.merchant_name, amount: order.amount,
    pricing: { point_amount: 0 }, payment: { method: order.method, method_label: order.method_label, approved_at: order.approved_at, issuer_name: '합성카드', masked_card_number: '5107-37**-****-8900', authorization_number: '30011223' },
    receipts: { sales_slip_url: SLIP, cash_receipt_url: null },
  },
  receipt: { lookup: { date: '2026-11-19', amount: order.amount, number: '30011223', number_type: 'approval' } },
});

async function setup(page, context, { failFirstReceipt = false } = {}) {
  const calls = [];
  let receiptCalls = 0;
  await context.route('**/*', route => new URL(route.request().url()).origin === 'http://127.0.0.1:4175' ? route.continue() : route.abort());
  await page.route('**/auth-fixture/auth/v1/**', route => route.fulfill({ json: { access_token: 'synthetic-only', refresh_token: 'synthetic-refresh', expires_in: 3600, token_type: 'bearer', user } }));
  await page.route('**/api-fixture/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/api-fixture', '');
    calls.push(path);
    if (path === '/payments/history') return route.fulfill({ json: { ok: true, data: { items: orders } } });
    if (path.startsWith('/payments/history/')) {
      receiptCalls++;
      if (failFirstReceipt && receiptCalls === 1) return route.fulfill({ status: 502, json: { detail: { code: 'SUPABASE_ERROR', message: '영수증을 불러오지 못했어요' } } });
      const order = orders.find(o => path.endsWith(o.order_id));
      return route.fulfill({ json: { ok: true, data: receipt(order, order.status === 'refunded' ? { status: 'completed', refund_amount: order.amount, point_amount: 0, completed_at: '2026-11-19T04:00:00+00:00' } : null) } });
    }
    const data = {
      '/me': { user_id: user.id, display_name: '합성 구매자', role: 'customer', status: 'active', account_type: 'voucher', voucher_balance: 3, point_balance: 0,
        voucher_use_history: [
          { id: 1, amount: 8000, kind: 'voucher_use', title: '식권 사용', merchant_name: '합성 한식뷔페', created_at: '2026-11-19T03:10:00+00:00' },
          { id: 2, amount: 7500, kind: 'voucher_use', title: '식권 사용', merchant_name: '합성 국수집', created_at: '2026-11-18T03:10:00+00:00' },
        ] },
      '/vouchers/products': { purchase_mode: 'voucher', items: [] },
    }[path];
    return route.fulfill({ json: { ok: true, data: data || {} } });
  });
  return calls;
}
async function openHistory(page) {
  await page.goto('/shop');
  await page.getByLabel('이메일', { exact: true }).fill('synthetic@example.invalid');
  await page.getByLabel('비밀번호', { exact: true }).fill('synthetic-password-only');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('navigation', { name: '구매자 탭' }).getByRole('button', { name: '내역', exact: true }).click();
  await expect(page.getByRole('heading', { name: '이용내역' })).toBeVisible();
}

test('내역: 구매 list opens the receipt again with slip link and lookup values', async ({ page, context }) => {
  const calls = await setup(page, context);
  await openHistory(page);
  // The bought list is not requested until its segment is opened.
  expect(calls.filter(p => p === '/payments/history')).toHaveLength(0);
  await page.getByRole('tab', { name: '구매' }).click();
  await expect(page.getByRole('button', { name: '합성 11장 식권 영수증 보기' })).toContainText('합성 한식뷔페');
  await expect(page.getByRole('button', { name: '합성 1장 식권 영수증 보기' })).toContainText('환불 완료');
  await page.getByRole('button', { name: '합성 11장 식권 영수증 보기' }).click();
  const dialog = page.getByRole('dialog', { name: '결제 영수증' });
  await expect(dialog).toContainText('80,000원');
  await expect(dialog).toContainText('합성카드 5107-37**-****-8900');
  await expect(dialog).toContainText('30011223');
  await expect(dialog.getByRole('link', { name: '카드 매출전표 보기' })).toHaveAttribute('href', SLIP);
  await expect(dialog.getByRole('link', { name: '카드 매출전표 보기' })).toHaveAttribute('target', '_blank');
  await expect(dialog).toContainText('매출전표는 키움페이 화면에 아래 값을 입력하면 열려요');
  await expect(dialog.getByRole('note')).toHaveCount(0);
  await dialog.getByRole('button', { name: '닫기' }).click();
  await expect(dialog).toHaveCount(0);
  expect(calls).toContain('/payments/history/GE-V-synthetic-2');
});

test('내역: restaurant chips narrow both lists, refunded order shows the refund, a failed receipt can be retried', async ({ page, context }) => {
  await setup(page, context, { failFirstReceipt: true });
  await openHistory(page);
  const chips = page.getByRole('group', { name: '식당 선택' });
  await expect(page.locator('.usage-row:visible')).toHaveCount(2);
  await chips.getByRole('button', { name: '합성 국수집' }).click();
  await expect(page.locator('.usage-row:visible')).toHaveCount(1);
  await expect(page.locator('.usage-summary:visible')).toContainText('1건');
  await page.getByRole('tab', { name: '구매' }).click();
  await expect(page.locator('.order-row:visible')).toHaveCount(2);
  await page.getByRole('group', { name: '식당 선택' }).getByRole('button', { name: '합성 국수집' }).click();
  await expect(page.locator('.order-row:visible')).toHaveCount(1);
  await page.getByRole('button', { name: '합성 1장 식권 영수증 보기' }).click();
  const dialog = page.getByRole('dialog', { name: '결제 영수증' });
  await expect(dialog.getByRole('alert')).toContainText('영수증을 불러오지 못했어요');
  await dialog.getByRole('button', { name: '다시 시도' }).click();
  await expect(dialog.getByRole('note')).toContainText('환불 완료된 결제예요');
  await expect(dialog.getByRole('note')).toContainText('7,500원');
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
});
