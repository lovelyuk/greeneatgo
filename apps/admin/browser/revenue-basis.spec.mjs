import { test, expect } from '@playwright/test';
import { adminLogin, COMPANY_ID } from './admin-fixture.mjs';

// Restaurant dashboard: revenue on the paid/issued basis next to the usage basis,
// and a per-partner popup opened from the partner table or the ranking table.
test('restaurant dashboard shows both revenue bases and a partner detail popup', async ({ page, context }) => {
  const calls = await adminLogin(page, context, { role: 'merchant_admin' });
  const panel = page.getByRole('region', { name: '매출 기준별 현황' });
  await expect(panel.getByText('매출 (결제·발행 기준)')).toBeVisible();
  await expect(panel.getByText('₩3,870,000')).toBeVisible();
  await expect(panel.getByText('식권 결제 ₩1,280,000 − 환불 ₩80,000')).toBeVisible();
  // A company subsidy counts on the day the subsidized voucher is bought.
  await expect(panel.getByText('회사 보조금 ₩30,000 (30장 · 식권 구매일 기준)')).toBeVisible();
  await expect(panel.getByText('세금계산서 발행 ₩2,640,000 (2건)')).toBeVisible();
  await expect(panel.getByText('포인트 사용 ₩45,000은 제외 (회사 청구 시 매출)')).toBeVisible();
  await expect(panel.getByText('식사 제공 (사용 기준)')).toBeVisible();
  await expect(panel.getByText('₩3,300,000')).toBeVisible();
  await expect(panel.getByText('미청구 장부 금액')).toBeVisible();
  await expect(panel.getByText('₩1,760,000', { exact: true }).first()).toBeVisible();
  // The existing dashboard figures stay where they were.
  await expect(page.getByRole('heading', { name: '거래처별 매출 합계' })).toBeVisible();

  const row = panel.getByRole('row', { name: /가온상사/ });
  await expect(row).toContainText('₩1,030,000');
  await expect(row).toContainText('₩900,000 · 112끼');
  await expect(row).toContainText('₩440,000');
  await expect(panel.getByRole('row', { name: /개인 고객/ })).toContainText('-');

  await panel.getByRole('button', { name: '합성테크 세부 내역 보기' }).click();
  const dialog = page.getByRole('dialog', { name: '합성테크 매출 세부 내역' });
  await expect(dialog).toBeVisible();
  const summary = calls.filter((call) => call.path === '/admin/merchant/revenue/summary');
  expect(summary.length).toBeGreaterThan(0);
  expect(calls.filter((call) => call.path === '/admin/merchant/revenue/detail').length).toBe(1);
  const detailRequest = page.waitForRequest((request) => request.url().includes('/admin/merchant/revenue/detail'));
  await expect(dialog.getByText('결제 ₩0 − 환불 ₩0 + 세금계산서 ₩1,760,000')).toBeVisible();
  await expect(dialog.getByRole('row', { name: /세금계산서 발행/ })).toContainText('20261105-41000000-00000001');
  await dialog.getByRole('tab', { name: /날짜별 식사/ }).click();
  await expect(dialog.getByRole('row', { name: /2끼/ })).toContainText('1건');
  await dialog.getByRole('tab', { name: /식사 건 목록/ }).click();
  await expect(dialog.getByRole('row', { name: /박서연/ })).toContainText('영업팀');
  await expect(dialog.getByRole('row', { name: /취소/ })).toContainText('-₩8,800');
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  detailRequest.catch(() => {});

  // The ranking table's company name opens the same popup; the request names the party and the period.
  const request = page.waitForRequest((r) => r.url().includes('/admin/merchant/revenue/detail'));
  await page.getByRole('button', { name: '합성테크 세부 내역 보기' }).last().click();
  const url = new URL((await request).url());
  expect(url.searchParams.get('party')).toBe(COMPANY_ID);
  expect(url.searchParams.get('from')).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  await expect(page.getByRole('dialog', { name: '합성테크 매출 세부 내역' })).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: '닫기' }).click();
});

test('company dashboard has no restaurant revenue panel', async ({ page, context }) => {
  const calls = await adminLogin(page, context, { role: 'company_admin' });
  await expect(page.getByRole('region', { name: '매출 기준별 현황' })).toHaveCount(0);
  expect(calls.some((call) => call.path.startsWith('/admin/merchant/revenue'))).toBe(false);
});
