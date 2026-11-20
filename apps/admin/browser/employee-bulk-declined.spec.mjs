import { test, expect } from '@playwright/test';
import { adminLogin } from './admin-fixture.mjs';

// A bulk-registered member was asked in the app and refused: the company admin
// sees it on the employee list and can offer the company again.
const INVITE = 'bulk:6f1c2d3e-4a5b-4c6d-8e7f-0a1b2c3d4e5f';

test('company admin sees a declined bulk invite and re-invites', async ({ page, context }) => {
  const calls = await adminLogin(page, context, {
    role: 'company_admin',
    overrides: {
      '/admin/employees': { items: [
        { id: 'e-1', display_name: '김하늘', employee_no: 'E001', phone: '01000000001', department: '개발팀', status: 'active', monthly_limit: 200000, month_used: 0, point_balance: 0 },
        { id: INVITE, is_staged: true, status: 'declined', declined_at: '2026-11-21T01:00:00+00:00', display_name: '박거절', employee_no: 'E002', phone: '01000000002', department: '영업팀', monthly_limit: 200000, month_used: 0 },
        { id: 'bulk:7f1c2d3e-4a5b-4c6d-8e7f-0a1b2c3d4e5f', is_staged: true, status: 'invited', display_name: '이대기', employee_no: 'E003', phone: '01000000003', department: null, monthly_limit: 200000, month_used: 0 },
      ] },
    },
  });
  await page.getByRole('navigation', { name: '업체 관리자 메뉴' }).getByRole("button", { name: "사원 관리" }).click();
  const declined = page.getByRole('row', { name: /박거절/ });
  await expect(declined.getByText('직원 거절', { exact: true })).toBeVisible();
  await expect(declined.getByText('직원이 전환을 거절했어요 (2026. 11. 21.)')).toBeVisible();
  const waiting = page.getByRole('row', { name: /이대기/ });
  await expect(waiting.getByText('초대대기', { exact: true })).toBeVisible();
  await expect(waiting.getByText('최초 가입 대기')).toBeVisible();
  await expect(waiting.getByRole('button', { name: '다시 초대' })).toHaveCount(0);
  await expect(page.getByRole('row', { name: /김하늘/ }).getByRole('button', { name: '다시 초대' })).toHaveCount(0);
  await declined.getByRole('button', { name: '다시 초대' }).click();
  await expect(page.getByText('박거절님을 다시 초대했어요. 앱을 열면 전환 여부를 다시 물어봐요.')).toBeVisible();
  expect(calls.filter(c => c.method === 'POST').map(c => c.path)).toEqual([`/admin/employees/bulk-invites/${encodeURIComponent(INVITE)}/reinvite`]);
});
