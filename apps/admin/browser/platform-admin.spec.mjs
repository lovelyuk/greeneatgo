// Platform admin screen (astryx pilot). SYNTHETIC fixtures only; every nonlocal request is blocked.
import { test, expect } from '@playwright/test';
import { adminLogin } from './admin-fixture.mjs';

test.use({ viewport: { width: 1280, height: 900 }, timezoneId: 'Asia/Seoul' });

const merchants = { items: [
  { id: 'm-1', name: '합성 식당', owner_phone: '0212345678', category: '한식', avg_price: 8000, status: 'active', created_at: '2026-11-01T00:00:00Z' },
  { id: 'm-2', name: '가온 분식', owner_phone: null, category: null, avg_price: null, status: 'paused', created_at: '2026-10-01T00:00:00Z' },
] };

async function login(page, context, theme = 'default') {
  const calls = await adminLogin(page, context, { role: 'platform_admin', theme, overrides: { '/admin/platform/merchants': merchants } });
  await page.route('**/api-fixture/admin/platform/merchants/m-1/invite', (route) => {
    calls.push({ method: 'POST', path: '/admin/platform/merchants/m-1/invite', body: route.request().postDataJSON() });
    return route.fulfill({ json: { ok: true, data: { token: 'synthetic-invite-token', delivery: 'manual' } } });
  });
  return calls;
}

test('platform admin sees the astryx screen with merchants, stats and account', async ({ page, context }) => {
  await login(page, context);
  await expect(page.locator('#platform-admin')).toBeVisible();
  await expect(page.getByRole('navigation', { name: '식당 관리자 메뉴' })).toHaveCount(0);
  await expect(page.getByText('돈토')).toHaveCount(0);
  const table = page.getByRole('table');
  await expect(table.getByText('합성 식당', { exact: true })).toBeVisible();
  await expect(table.getByText('운영 중', { exact: true })).toBeVisible();
  await expect(table.getByText('중지', { exact: true })).toBeVisible();
  await expect(page.getByText('admin@example.invalid')).toBeVisible();
  await page.screenshot({ path: process.env.PLATFORM_SHOT || 'test-results/platform-admin.png', fullPage: true });
});

test('registering a merchant posts the trimmed payload', async ({ page, context }) => {
  const calls = await login(page, context);
  const register = page.getByRole('button', { name: '식당 등록', exact: true });
  await expect(register).toBeDisabled();
  await page.getByRole('textbox', { name: /식당명/ }).fill('  새 식당 ');
  await page.getByRole('textbox', { name: /평균가/ }).fill('8,500');
  await register.click();
  await expect.poll(() => calls.filter((c) => c.method === 'POST' && c.path === '/admin/platform/merchants').map((c) => c.body))
    .toEqual([{ name: '새 식당', owner_phone: null, category: null, avg_price: 8500 }]);
  await expect(page.getByText('새 식당 식당을 등록했어요.')).toBeVisible();
});

test('inviting an owner shows a copyable invite link', async ({ page, context }) => {
  const calls = await login(page, context);
  await page.getByRole('textbox', { name: '합성 식당 초대 연락처' }).fill('01011112222');
  await page.getByRole('button', { name: '초대 링크 만들기' }).first().click();
  await expect.poll(() => calls.filter((c) => c.path.endsWith('/m-1/invite')).map((c) => c.body)).toEqual([{ phone: '01011112222' }]);
  await expect(page.getByRole('textbox', { name: '초대 링크' })).toHaveValue('http://127.0.0.1:4175/?invite=synthetic-invite-token');
});

test('legacy admin skins do not restyle the astryx screen', async ({ page, context }) => {
  await login(page, context, 'calm-dark');
  const button = page.getByRole('button', { name: '식당 등록', exact: true });
  const style = await button.evaluate((el) => { const s = getComputedStyle(el); return { radius: s.borderRadius, weight: s.fontWeight }; });
  expect(style.radius).not.toBe('17px');
  expect(style.weight).not.toBe('950');
  const input = page.getByRole('textbox', { name: /식당명/ });
  expect(await input.evaluate((el) => getComputedStyle(el).borderRadius)).not.toBe('18px');
});
