// 실시간 매출 → 영수증: Kiwoom receipt pages refuse to be framed (X-Frame-Options: SAMEORIGIN),
// so the modal shows our own payment record and offers the official page in a new window
// (with the values Kiwoom asks for) instead of a blank iframe.
// SYNTHETIC fixtures only; every nonlocal request is blocked.
import { test, expect } from '@playwright/test';
import { adminLogin } from './admin-fixture.mjs';

test.use({ viewport: { width: 1440, height: 900 }, timezoneId: 'Asia/Seoul' });

const RECEIPT_URL = 'https://agent.kiwoompay.co.kr/common/PayInfoPrintDirectCard.jsp?DAOUTRX=SYNTHETIC0001&STATUS=A';
const RECEIPT = {
  product_name: '합성 식권', merchant_name: '합성식당', amount: 100, status: 'done', method: 'CARD', method_label: '카드',
  issuer_name: '합성카드', masked_card_number: '****-****-****-1234', bank_name: null,
  authorization_number: '12345678', order_number: 'GE-SYN-1', approved_at: '2026-11-11T07:41:39+00:00',
  lookup: { date: '2026-11-11', amount: 100, number: '12345678', number_type: 'approval' },
};
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
  await page.route('**/api-fixture/admin/merchant/payment-history/receipts/**', (route) => route.fulfill({ json: { ok: true, data: { title: '카드 매출전표', url: RECEIPT_URL, source: 'payment', receipt: RECEIPT } } }));
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
  // Our own record is visible at once, without leaving the admin.
  const sheet = dialog.getByRole('region', { name: '결제 내역' });
  await expect(sheet).toContainText('100원');
  await expect(sheet).toContainText('합성카드 ****-****-****-1234');
  await expect(sheet).toContainText('2026.11.11 16:41');
  await expect(sheet).toContainText('601-85-17320');
  // The three values Kiwoom's slip page asks for, each with a copy button.
  const lookup = dialog.locator('.receipt-lookup li');
  await expect(lookup).toHaveCount(3);
  await expect(lookup.nth(0)).toContainText('2026-11-11');
  await expect(lookup.nth(2)).toContainText('승인번호');
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await dialog.getByRole('button', { name: '승인번호 복사' }).click();
  await expect(dialog.getByRole('button', { name: '승인번호 복사' })).toHaveText('복사됨');
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('12345678');
  await expect(link).toBeInViewport({ ratio: 1 }); // whole modal fits at 900px height, no clipped button
  if (theme === 'calm-dark') await expect(sheet.locator('.receipt-sheet-amount strong')).not.toHaveCSS('color', 'rgb(0, 0, 0)');
  if (process.env.RECEIPT_SHOT) await dialog.screenshot({ path: `${process.env.RECEIPT_SHOT}-${theme}.png` });
});
