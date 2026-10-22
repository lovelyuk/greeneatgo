// Admin UI themes (관리자 화면 테마). SYNTHETIC fixtures only; every nonlocal request is blocked.
import { test, expect } from '@playwright/test';
import { adminLogin } from './admin-fixture.mjs';

test.use({ viewport: { width: 1440, height: 900 }, timezoneId: 'Asia/Seoul' });

const bg = (locator) => locator.evaluate((el) => getComputedStyle(el).backgroundColor);
// Buttons animate colour for .15s; turn transitions off so reads see the final value.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => document.addEventListener('DOMContentLoaded', () => {
    const style = document.createElement('style');
    style.textContent = '*, *::before, *::after { transition: none !important; animation: none !important; }';
    document.head.append(style);
  }));
});

test('default theme keeps the current light design and hides Calm Dark extras', async ({ page, context }) => {
  await adminLogin(page, context, { role: 'merchant_admin', theme: 'default' });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'default');
  await expect(page.locator('html')).not.toHaveAttribute('data-skin', /.+/);
  expect(await bg(page.locator('body'))).toBe('rgb(250, 250, 250)');
  await expect(page.getByRole('combobox', { name: '화면 테마' })).toHaveValue('default');
  await expect(page.getByText('방금 들어온 결제')).toHaveCount(0);
  await expect(page.getByLabel('로그인 계정')).toHaveCount(0);
  await page.getByRole('navigation', { name: '식당 관리자 메뉴' }).getByRole('button', { name: '식당 관리', exact: true }).click();
  await expect(page.getByLabel('앱 미리보기')).toHaveCount(0);
  await page.getByRole('button', { name: '리뷰', exact: true }).click();
  await expect(page.getByLabel('별점 분포')).toHaveCount(0);
});

test('saved Calm Dark theme loads from /me with its extras; labels stay unchanged', async ({ page, context }) => {
  await adminLogin(page, context, { role: 'merchant_admin', theme: 'calm-dark' });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'calm-dark');
  await expect(page.locator('html')).toHaveAttribute('data-skin', 'ticket');
  expect(await bg(page.locator('body'))).toBe('rgb(10, 13, 20)');
  const nav = page.getByRole('navigation', { name: '식당 관리자 메뉴' });
  for (const label of ['대시보드', '실시간 매출', '업체 정보', '매출 정산', '증빙 내역', '식당 관리', '공급자 정보']) {
    await expect(nav.getByRole('button', { name: label, exact: true })).toBeVisible();
  }
  expect(await bg(nav.getByRole('button', { name: '대시보드', exact: true }))).toBe('rgb(244, 241, 233)');
  await expect(page.getByLabel('로그인 계정')).toContainText('합성 식당');
  await expect(page.getByRole('heading', { name: '방금 들어온 결제' })).toBeVisible();
  await expect(page.locator('.recent-payments-list li')).toHaveCount(5);
  await nav.getByRole('button', { name: '식당 관리', exact: true }).click();
  await expect(page.getByLabel('앱 미리보기')).toContainText('제육볶음');
  await page.getByRole('button', { name: '리뷰', exact: true }).click();
  await expect(page.getByLabel('별점 분포')).toContainText('5점');
});

test('switching theme saves it on the account, and a refused save rolls back', async ({ page, context }) => {
  const calls = await adminLogin(page, context, { role: 'company_admin', theme: 'default' });
  const picker = page.getByRole('combobox', { name: '화면 테마' });
  await picker.selectOption('calm-dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'calm-dark');
  await expect.poll(() => calls.filter((c) => c.method === 'PATCH' && c.path === '/me/preferences').map((c) => c.body)).toEqual([{ admin_theme: 'calm-dark' }]);
  await expect(page.getByLabel('로그인 계정')).toContainText('합성테크');

  await page.route('**/api-fixture/me/preferences', (route) => route.fulfill({ status: 409, json: { detail: { code: 'MIGRATION_REQUIRED', message: '0070_admin_ui_theme.sql 적용 후 테마를 저장할 수 있어요' } } }));
  await picker.selectOption('default');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'calm-dark');
  await expect(picker).toHaveValue('calm-dark');
  await expect(page.getByText('화면 테마를 저장하지 못했어요')).toBeVisible();
});

test('login screen follows the last theme used on this browser', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('greeneat.admin.lastTheme', 'calm-dark'));
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'calm-dark');
  await expect(page.getByRole('button', { name: '운영 시작하기', exact: true })).toBeVisible();
  await expect(page.locator('.brandmark img').first()).toHaveAttribute('src', '/brand/greeneat_logo_light.png');
});

test('/shop and /counter ignore the admin theme even when this browser last used Calm Dark', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('greeneat.admin.lastTheme', 'calm-dark'));
  for (const path of ['/shop', '/counter']) {
    await page.goto(path);
    await expect(page.locator('html')).not.toHaveAttribute('data-theme', /.+/);
    await expect(page.locator('html')).not.toHaveAttribute('data-skin', /.+/);
  }
});

for (const darkTheme of ['calm-dark', 'forest-stubs']) test(`${darkTheme} leaves no light leftover surfaces on admin screens`, async ({ page, context }) => {
  test.setTimeout(60000);
  await adminLogin(page, context, { role: 'merchant_admin', theme: darkTheme });
  const nav = page.getByRole('navigation', { name: '식당 관리자 메뉴' });
  const screens = [['대시보드'], ['실시간 매출'], ['업체 정보'], ['매출 정산'], ['증빙 내역'], ['식당 관리', '판매 상품'], ['식당 관리', '쿠폰 관리'],
    ['식당 관리', '알림'], ['식당 관리', '리뷰'], ['식당 관리', '배너 광고 설정'], ['공급자 정보']];
  for (const [section, tab] of screens) {
    await nav.getByRole('button', { name: section, exact: true }).click();
    if (tab) await page.getByRole('button', { name: tab, exact: true }).click();
    const light = await page.evaluate(() => [...document.querySelectorAll('.merchant-content *, .merchant-tabs *')].filter((el) => {
      if (['INPUT', 'IMG', 'svg'].includes(el.tagName) || el.closest('.day-stub')) return false; // day stubs are paper tickets
      const r = el.getBoundingClientRect(); if (r.width < 8 || r.height < 8) return false;
      const m = getComputedStyle(el).backgroundColor.match(/rgba?\(([^)]+)\)/); if (!m) return false;
      const [R, G, B, A = 1] = m[1].split(',').map(Number);
      if (A < 0.5 || (R === 244 && G === 241 && B === 233)) return false; // paper ticket is intentional
      return (0.2126 * R + 0.7152 * G + 0.0722 * B) / 255 > 0.6;
    }).map((el) => `${el.tagName}.${el.className}`));
    expect(light, `${section}${tab ? `/${tab}` : ''}`).toEqual([]);
  }
});

test('Forest Day Stubs: 06 layout with a tabbed card — 식권 달력 first, 기간별 매출 second', async ({ page, context }) => {
  await adminLogin(page, context, { role: 'merchant_admin', theme: 'forest-stubs' });
  await expect(page.locator('html')).toHaveAttribute('data-dashboard', 'forest');
  const tabs = page.getByRole('tablist', { name: '기간 보기' });
  await expect(tabs.getByRole('tab')).toHaveText(['식권 달력', '기간별 매출']);
  await expect(tabs.getByRole('tab', { name: '식권 달력' })).toHaveAttribute('aria-selected', 'true');
  const calendar = page.getByRole('grid', { name: '식권 달력' });
  await expect(calendar).toBeVisible();
  await expect(calendar.locator('.day-stub.today')).toHaveCount(1);
  await expect(calendar.locator('.day-stub.best')).toHaveCount(1);
  await expect(calendar.locator('.day-stub.sold').first()).toContainText('건');
  expect(await bg(calendar.locator('.day-stub.sold').first())).toBe('rgb(244, 241, 233)');
  await expect(page.getByText('방금 들어온 결제')).toHaveCount(0); // Calm Dark-only extra
  await expect(page.getByLabel('로그인 계정')).toHaveCount(0);
  await tabs.getByRole('tab', { name: '기간별 매출' }).click();
  await expect(calendar).toHaveCount(0);
  await expect(page.getByRole('img', { name: '기간별 매출' })).toBeVisible();
  await expect(page.getByText('단위: 원 · 일별')).toBeVisible();
  await expect(page.getByRole('heading', { name: '거래처별 매출 합계' })).toBeVisible();
});

test('Forest: deep forest sidebar, cream page, tabs 기간별 매출 | 기간별 수량', async ({ page, context }) => {
  await adminLogin(page, context, { role: 'merchant_admin', theme: 'forest' });
  expect(await bg(page.locator('body'))).toBe('rgb(244, 242, 236)');
  expect(await bg(page.getByRole('navigation', { name: '식당 관리자 메뉴' }))).toBe('rgb(24, 48, 31)');
  const tabs = page.getByRole('tablist', { name: '기간 보기' });
  await expect(tabs.getByRole('tab')).toHaveText(['기간별 매출', '기간별 수량']);
  await tabs.getByRole('tab', { name: '기간별 수량' }).click();
  await expect(page.getByRole('img', { name: '기간별 수량' })).toBeVisible();
  await expect(page.getByRole('grid', { name: '식권 달력' })).toHaveCount(0);
});

test('Compact Table: number strip + one company table with count, amount and share', async ({ page, context }) => {
  await adminLogin(page, context, { role: 'merchant_admin', theme: 'compact' });
  await expect(page.locator('html')).toHaveAttribute('data-dashboard', 'compact');
  const chips = page.getByLabel('요약 숫자');
  for (const label of ['총 매출', '총 수량', '중식', '석식', '하루 평균']) await expect(chips.getByText(label, { exact: true })).toBeVisible();
  await expect(chips).toContainText('₩');
  await expect(page.getByRole('img', { name: '기간별 매출 그래프' })).toBeVisible();
  const table = page.locator('.compact-company-table');
  await expect(table.locator('thead th')).toHaveText(['순위', '거래처', '수량', '매출', '매출 비중']);
  await expect(table.locator('tbody tr').first()).toContainText('합성테크');
  await expect(table.locator('tbody tr').first()).toContainText('225건');
  await expect(table.locator('tbody tr').first()).toContainText('51.8%');
  await expect(page.getByRole('tablist', { name: '기간 보기' })).toHaveCount(0);
});

for (const theme of ['forest-stubs', 'forest', 'compact']) test(`company admin dashboard renders in the ${theme} layout`, async ({ page, context }) => {
  await adminLogin(page, context, { role: 'company_admin', theme });
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
  await expect(page.getByText('총 이용액', { exact: true }).first()).toBeVisible();
  if (theme === 'forest-stubs') await expect(page.getByRole('grid', { name: '식권 달력' })).toBeVisible();
  if (theme === 'compact') await expect(page.locator('.compact-company-table thead th').nth(1)).toHaveText('구분');
});
