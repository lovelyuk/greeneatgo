import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
for (const width of [1440, 390, 320]) {
  for (const name of ['privacy', 'terms']) {
    test(`emitted ${name} ${width}px: exact artifact, no external CSS/fonts, no overflow`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      const external = [], errors = [];
      page.on('request', request => {
        if (new URL(request.url()).origin !== 'http://127.0.0.1:4175') external.push(request.url());
      });
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', route => new URL(route.request().url()).origin === 'http://127.0.0.1:4175' ? route.continue() : route.abort());
      const response = await page.goto(`/${name}.html`);
      expect(await response.text()).toBe(readFileSync(new URL(`../public/${name}.html`, import.meta.url), 'utf8'));
      await expect(page.locator('h1')).toHaveText(name === 'privacy' ? '개인정보 처리방침' : '이용약관');
      await page.evaluate(() => document.fonts.ready);
      expect(external).toEqual([]);
      expect(await page.locator('link[rel="stylesheet"]').count()).toBe(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(errors).toEqual([]);
      if (name === 'privacy') {
        await expect(page.getByRole('heading', { name: '확인된 주 처리지역 / 추가 고지 확인 중' })).toBeVisible();
        await expect(page.locator('.ph').first()).toContainText('클라우드/호스팅 사업자');
        await expect(page.locator('body')).toContainText('손슬기 / 과장');
      }
      await page.screenshot({ path: test.info().outputPath(`${name}-${width}.png`), fullPage: true });
    });
  }
}
test('emitted routes preserve admin and shop separation and unresolved signup gate', async ({ page }) => {
  await page.route('**/*', route => new URL(route.request().url()).origin === 'http://127.0.0.1:4175' ? route.continue() : route.abort());
  await page.goto('/');
  await expect(page.getByLabel('이메일', { exact: true })).toBeVisible();
  await page.goto('/shop');
  await expect(page.getByLabel('이메일', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '회원가입', exact: true }).click();
  await page.getByLabel('약관 및 개인정보 처리방침 확인').check();
  await expect(page.getByRole('button', { name: '가입 신청', exact: true })).toBeDisabled();
  await expect(page.locator('footer a[href="/terms.html"]')).toHaveCount(1);
  await expect(page.locator('footer a[href="/privacy.html"]')).toHaveCount(1);
});
