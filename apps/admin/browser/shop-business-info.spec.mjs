// /shop footer: 사업자 정보 required by the PG (키움페이) review. Mocked I/O only.
import { test, expect } from '@playwright/test';

test.use({ viewport: { width: 390, height: 844 } });

test('/shop shows business info under the legal links (logged out)', async ({ page, context }) => {
  await context.route('**/*', (route) => (new URL(route.request().url()).origin === 'http://127.0.0.1:4175' ? route.continue() : route.abort()));
  await page.goto('/shop');
  const info = page.getByRole('group', { name: '사업자 정보' }).or(page.getByLabel('사업자 정보'));
  await expect(info).toBeVisible();
  for (const text of ['상호 그린잇', '대표자 오안식', '사업자등록번호 601-85-17320', '통신판매업신고 2025-서울금천-1242',
    '주소 서울특별시 금천구 가산디지털1로 145, 3차동 지하1층 B108~B111호(가산동, 에이스하이엔드타워3차)',
    '이메일 greeneat0419@naver.com', '고객센터 1555-5952']) {
    await expect(info).toContainText(text);
  }
  await expect(info.getByRole('link', { name: 'greeneat0419@naver.com' })).toHaveAttribute('href', 'mailto:greeneat0419@naver.com');
  await expect(info.getByRole('link', { name: '1555-5952' })).toHaveAttribute('href', 'tel:15555952');
  // still below the three existing links
  const footer = page.locator('footer');
  await expect(footer.getByRole('link', { name: '이용약관' })).toBeVisible();
  const linkBox = await footer.getByRole('link', { name: '관리자 화면' }).boundingBox();
  const infoBox = await info.boundingBox();
  expect(infoBox.y).toBeGreaterThan(linkBox.y);
  if (process.env.SHOP_SHOT) await page.screenshot({ path: process.env.SHOP_SHOT, fullPage: true });
});
