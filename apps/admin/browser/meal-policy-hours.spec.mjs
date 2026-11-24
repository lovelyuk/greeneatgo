import { test, expect } from '@playwright/test';
import { adminLogin } from './admin-fixture.mjs';

// Company admin sets the hours in which company-paid meals can be used.
test('company admin edits meal hours: lunch only, validation, saved body', async ({ page, context }) => {
  const calls = await adminLogin(page, context, { role: 'company_admin' });
  await page.getByRole('navigation', { name: '업체 관리자 메뉴' }).getByRole('button', { name: '사원 관리' }).click();
  const panel = page.getByRole('region', { name: '식대 사용시간 설정' });
  await expect(panel).toContainText('직원이 직접 구매한 식권은 시간 제한을 받지 않아요.');
  await expect(panel.getByText('시간 제한 사용 중')).toBeVisible();
  await expect(panel.getByLabel('사용시간 제한 켜기')).toBeChecked();
  await expect(panel.getByLabel('중식 시작')).toHaveValue('11:00');
  await expect(panel.getByLabel('석식 종료')).toHaveValue('20:30');

  // End before start is caught before saving.
  await panel.getByLabel('중식 시작').fill('15:00');
  await expect(panel.getByRole('alert')).toHaveText('중식 종료 시간은 시작 시간보다 늦어야 해요.');
  await expect(panel.getByRole('button', { name: '사용시간 저장' })).toBeDisabled();
  await panel.getByLabel('중식 시작').fill('11:30');
  await panel.getByLabel('중식 종료').fill('13:30');
  // Lunch only: dinner switched off, its inputs lock.
  await panel.getByLabel('석식 사용').uncheck();
  await expect(panel.getByLabel('석식 시작')).toBeDisabled();
  // Both off is not a valid restriction.
  await panel.getByLabel('중식 사용').uncheck();
  await expect(panel.getByRole('alert')).toHaveText('사용 시간대를 하나 이상 켜 주세요.');
  await panel.getByLabel('중식 사용').check();
  await panel.getByRole('button', { name: '사용시간 저장' }).click();
  await expect(page.getByText('식대 사용시간 제한을 저장했어요.')).toBeVisible();
  expect(calls.filter((call) => call.method === 'PUT' && call.path === '/admin/meal-policy').map((call) => call.body)).toEqual([
    { enabled: true, lunch_enabled: true, dinner_enabled: false, lunch_start: '11:30', lunch_end: '13:30', dinner_start: '17:30', dinner_end: '20:30', daily_count_limit: null },
  ]);
});

test('company admin sets how many company meals an employee may have per day', async ({ page, context }) => {
  const calls = await adminLogin(page, context, { role: 'company_admin' });
  await page.getByRole('navigation', { name: '업체 관리자 메뉴' }).getByRole('button', { name: '사원 관리' }).click();
  const panel = page.getByRole('region', { name: '식대 사용시간 설정' });
  const count = panel.getByLabel('하루 사용 횟수');
  await expect(count).toHaveValue('');                    // empty = no limit
  await expect(panel).toContainText('직원이 직접 구매한 식권은 세지 않아요.');
  await count.fill('0');
  await expect(panel.getByRole('alert')).toHaveText('하루 사용 횟수는 1~20 사이 숫자로 입력해 주세요. 제한이 없으면 비워 두세요.');
  await expect(panel.getByRole('button', { name: '사용시간 저장' })).toBeDisabled();
  await count.fill('21');
  await expect(panel.getByRole('button', { name: '사용시간 저장' })).toBeDisabled();
  await count.fill('2');
  await expect(panel.getByRole('alert')).toHaveCount(0);
  await panel.getByRole('button', { name: '사용시간 저장' }).click();
  await expect(page.getByText('식대 사용시간 제한을 저장했어요. 하루 사용 횟수는 2번이에요.')).toBeVisible();
  const saved = calls.filter((call) => call.method === 'PUT' && call.path === '/admin/meal-policy').map((call) => call.body);
  expect(saved.length).toBe(1);
  expect(saved[0].daily_count_limit).toBe(2);
  expect(saved[0].enabled).toBe(true);
});

test('turning the restriction off locks the hours and saves enabled=false', async ({ page, context }) => {
  const calls = await adminLogin(page, context, { role: 'company_admin' });
  await page.getByRole('navigation', { name: '업체 관리자 메뉴' }).getByRole('button', { name: '사원 관리' }).click();
  const panel = page.getByRole('region', { name: '식대 사용시간 설정' });
  await panel.getByLabel('사용시간 제한 켜기').uncheck();
  await expect(panel.getByLabel('중식 시작')).toBeDisabled();
  await expect(panel.getByText('지금은 언제든 회사 식대로 결제할 수 있어요.')).toBeVisible();
  await panel.getByRole('button', { name: '사용시간 저장' }).click();
  await expect(page.getByText('식대 사용시간 제한을 해제했어요.')).toBeVisible();
  expect(calls.find((call) => call.method === 'PUT' && call.path === '/admin/meal-policy').body.enabled).toBe(false);
});
