import { test, expect } from '@playwright/test';
import { adminLogin, adminFixtureData } from './admin-fixture.mjs';

// 종사업장번호: a branch office of the same business number is its own company.
test('company admin saves a branch-office number with the company profile', async ({ page, context }) => {
  const calls = await adminLogin(page, context, { role: 'company_admin' });
  await page.getByRole('navigation', { name: '업체 관리자 메뉴' }).getByRole('button', { name: '회사 정보' }).click();
  const branch = page.getByLabel('종사업장번호');
  await expect(branch).toBeDisabled();
  await expect(branch).toHaveValue('');
  await page.getByRole('button', { name: '수정', exact: true }).click();
  await branch.fill('12');                                   // not four digits: the browser blocks the save
  await page.getByRole('button', { name: '저장', exact: true }).click();
  expect(calls.filter((call) => call.method === 'PATCH' && call.path === '/me/company')).toHaveLength(0);
  await branch.fill('0001');
  await page.getByRole('button', { name: '저장', exact: true }).click();
  await expect.poll(() => calls.filter((call) => call.method === 'PATCH' && call.path === '/me/company').length).toBe(1);
  const body = calls.find((call) => call.method === 'PATCH' && call.path === '/me/company').body;
  expect(body.sub_biz_no).toBe('0001');
  expect(body.biz_reg_no).toBe('123-45-67890');
});

test('restaurant company list tells branch offices apart and offers the first invitation', async ({ page, context }) => {
  const base = adminFixtureData('merchant_admin')['/admin/merchant/companies'].items[0];
  const company = (id, extra) => ({ ...base, id: `link-${id}`, company_id: `company-${id}`, invite: null,
    company: { ...base.company, id: `company-${id}`, name: '(주)합성게임', biz_reg_no: '114-81-93597', ...extra } });
  const calls = await adminLogin(page, context, { overrides: { '/admin/merchant/companies': { items: [
    company('a', { sub_biz_no: null }), company('b', { sub_biz_no: '0001' }), company('c', { sub_biz_no: '0006', contact_email: null }),
  ] } } });
  await page.getByRole('navigation', { name: '식당 관리자 메뉴' }).getByRole('button', { name: '업체 정보' }).click();
  const rows = page.locator('.company-list-page tbody tr');
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText('114-81-93597');
  await expect(rows.nth(0)).not.toContainText('종사업장');
  await expect(rows.nth(1)).toContainText('114-81-93597 (종사업장 0001)');
  await expect(rows.nth(2)).toContainText('114-81-93597 (종사업장 0006)');
  expect(calls.filter((call) => call.method === 'POST')).toHaveLength(0);
});
