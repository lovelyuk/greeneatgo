// 실시간 매출 → 영수증: Kiwoom receipt pages refuse to be framed (X-Frame-Options: SAMEORIGIN),
// so the modal must offer the official page in a new window instead of a blank iframe.
// SYNTHETIC fixtures only; every nonlocal request is blocked.
import { test, expect } from '@playwright/test';
import { adminLogin } from './admin-fixture.mjs';

test.use({ viewport: { width: 1440, height: 900 }, timezoneId: 'Asia/Seoul' });

const RECEIPT_URL = 'https://agent.kiwoompay.co.kr/common/PayInfoPrintDirectCard.jsp?DAOUTRX=SYNTHETIC0001&STATUS=A';
const payment = {
  id: 'order-1', product_name: '합성 식권', customer_name: '김하늘', amount: 100, point_amount: 0, payment_method: 'CARD',
  status: 'done', created_at: new Date().toISOString(), approved_at: new Date().toISOString(),
  receipt: { types: ['sales_slip'], source: 'payment', entry_kind: 'payment', entry_id: 'order-1' },
};
const history = {
  transaction: { total: 0, count: 0, detail_count: 0, series: [], items: [] },
  payment: { total: 100, gross_total: 100, refund_total: 0, count: 1, detail_count: 1, series: [], items: [payment] },
  series: [], rows: [payment], refunds: [],
  totals: { transaction_count: 0, transaction_amount: 0, payment_count: 1, payment_amount: 100, refund_count: 0, refund_amount: 0, net_payment_amount: 100 },
};

for (const theme of ['default', 'calm-dark']) test(`receipt modal opens the official Kiwoom page in a new window (${theme})`, async ({ page, context }) => {
  await adminLogin(page, context, { role: 'merchant_admin', theme, overrides: { '/admin/merchant/payment-history': history } });
  await page.route('**/api-fixture/admin/merchant/payment-history/receipts/**', (route) => route.fulfill({ json: { ok: true, data: { title: '카드 매출전표', url: RECEIPT_URL, source: 'payment' } } }));
  await page.getByRole('navigation', { name: '식당 관리자 메뉴' }).getByRole('button', { name: '실시간 매출', exact: true }).click();
  await page.getByRole('button', { name: /영수증 보기/ }).first().click();
  const dialog = page.getByRole('dialog', { name: '카드 매출전표' });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('iframe')).toHaveCount(0);
  const link = dialog.getByRole('link', { name: '카드 매출전표 새 창으로 열기' });
  await expect(link).toHaveAttribute('href', RECEIPT_URL);
  await expect(link).toHaveAttribute('target', '_blank');
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(link).toHaveCSS('color', 'rgb(255, 255, 255)');
  if (theme === 'calm-dark') await expect(dialog.locator('.receipt-modal-header')).toHaveCSS('background-color', 'rgb(19, 26, 42)');
  expect((await dialog.boundingBox()).height).toBeLessThan(420); // no leftover iframe-sized blank area
  if (process.env.RECEIPT_SHOT) await dialog.screenshot({ path: `${process.env.RECEIPT_SHOT}-${theme}.png` });
});
