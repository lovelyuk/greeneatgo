import { test, expect } from '@playwright/test';
import { adminLogin } from './admin-fixture.mjs';

// Company admin adds employees one at a time and removes a not-yet-joined row.
const STAGED = 'bulk:7f1c2d3e-4a5b-4c6d-8e7f-0a1b2c3d4e5f';
const employees = { items: [
  { id: 'e-1', display_name: '김하늘', employee_no: 'E001', phone: '01000000001', department: '개발팀', status: 'active', monthly_limit: 200000, month_used: 0, point_balance: 0 },
  { id: STAGED, is_staged: true, status: 'invited', display_name: '이대기', employee_no: 'E003', phone: '01000000003', department: null, monthly_limit: 200000, month_used: 0 },
] };

async function open(page, context) {
  const calls = await adminLogin(page, context, { role: 'company_admin', overrides: { '/admin/employees': employees } });
  await page.getByRole('navigation', { name: '업체 관리자 메뉴' }).getByRole('button', { name: '사원 관리' }).click();
  return calls;
}

test('adds one employee, keeps the window open for the next, then saves and closes', async ({ page, context }) => {
  const calls = await open(page, context);
  await expect(page.getByRole('button', { name: '직원 일괄등록' })).toBeVisible();
  await page.getByRole('button', { name: '+ 직원 추가' }).click();
  const dialog = page.getByRole('dialog', { name: '직원 추가' });
  await expect(dialog.getByLabel('이름')).toBeFocused();

  // Missing name and a bad number are caught before any request.
  await dialog.getByRole('button', { name: '저장', exact: true }).click({ force: true });
  await dialog.getByLabel('이름').fill('김신입');
  await dialog.getByLabel('전화번호').fill('010-12');
  await dialog.getByRole('button', { name: '저장하고 계속 추가' }).click();
  await expect(dialog.getByRole('alert')).toHaveText('전화번호를 확인해 주세요. (예: 010-1234-5678)');
  expect(calls.filter((call) => call.method === 'POST')).toHaveLength(0);

  await dialog.getByLabel('전화번호').fill('010-3333-4444');
  await dialog.getByLabel(/^부서/).fill('영업팀');
  await dialog.getByRole('button', { name: '저장하고 계속 추가' }).click();
  await expect(dialog.getByRole('status')).toHaveText('1명 추가했어요: 김신입');
  await expect(dialog.getByLabel('이름')).toHaveValue('');
  await expect(dialog.getByLabel('이름')).toBeFocused();

  await dialog.getByLabel('이름').fill('박신입');
  await dialog.getByLabel('전화번호').fill('01055556666');
  await dialog.getByLabel(/^사번/).fill('E200');
  await dialog.getByRole('button', { name: '저장', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText('박신입님을 등록했어요. 앱에 가입하면 바로 연결돼요.')).toBeVisible();
  expect(calls.filter((call) => call.method === 'POST').map((call) => [call.path, call.body])).toEqual([
    ['/admin/employees/invites', { name: '김신입', phone: '01033334444', department: '영업팀', employee_no: null }],
    ['/admin/employees/invites', { name: '박신입', phone: '01055556666', department: null, employee_no: 'E200' }],
  ]);
});

test('a server refusal stays in the window with its reason', async ({ page, context }) => {
  await open(page, context);
  await page.route('**/api-fixture/admin/employees/invites', (route) => route.fulfill({
    status: 422, json: { detail: { code: 'EMPLOYEE_INVITE_INVALID', message: '이미 등록된 번호예요' } } }));
  await page.getByRole('button', { name: '+ 직원 추가' }).click();
  const dialog = page.getByRole('dialog', { name: '직원 추가' });
  await dialog.getByLabel('이름').fill('김중복');
  await dialog.getByLabel('전화번호').fill('01000000001');
  await dialog.getByRole('button', { name: '저장', exact: true }).click();
  await expect(dialog.getByRole('alert')).toHaveText('이미 등록된 번호예요');
  await expect(dialog.getByLabel('이름')).toHaveValue('김중복');
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
});

test('deletes a not-yet-joined row only after confirming; joined employees have no delete', async ({ page, context }) => {
  const calls = await open(page, context);
  const waiting = page.getByRole('row', { name: /이대기/ });
  await expect(page.getByRole('row', { name: /김하늘/ }).getByRole('button', { name: /삭제/ })).toHaveCount(0);
  page.once('dialog', (dialog) => dialog.dismiss());
  await waiting.getByRole('button', { name: '이대기 등록 삭제' }).click();
  expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(0);
  page.once('dialog', (dialog) => { expect(dialog.message()).toContain('이대기님의 등록을 삭제할까요?'); dialog.accept(); });
  await waiting.getByRole('button', { name: '이대기 등록 삭제' }).click();
  await expect(page.getByText('이대기님의 등록을 삭제했어요.')).toBeVisible();
  expect(calls.filter((call) => call.method === 'DELETE').map((call) => call.path)).toEqual([`/admin/employees/bulk-invites/${encodeURIComponent(STAGED)}`]);
});
