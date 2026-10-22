// Shared synthetic fixture for admin (merchant/company) screens. No real data.
import { expect } from '@playwright/test';

export const MERCHANT_ID = '22222222-2222-4222-8222-222222222222';
export const COMPANY_ID = '33333333-3333-4333-8333-333333333333';

const today = new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });
const iso = (minutesAgo) => new Date(Date.now() - minutesAgo * 60000).toISOString();

function series() {
  const out = [];
  const end = new Date(`${today}T00:00:00+09:00`);
  for (let i = 13; i >= 0; i -= 1) {
    const d = new Date(end.getTime() - i * 86400000).toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });
    const weekend = [0, 6].includes(new Date(`${d}T12:00:00+09:00`).getDay());
    out.push({ date: d, amount: weekend ? 0 : 280000 + ((i * 37) % 9) * 21000, count: weekend ? 0 : 35 + ((i * 7) % 11) });
  }
  return out;
}

export function adminFixtureData(role, theme = 'default') {
  const merchant = role === 'merchant_admin';
  const me = {
    user_id: '11111111-1111-4111-8111-111111111111', email: 'admin@example.invalid',
    display_name: merchant ? '합성 식당관리자' : '합성 회사관리자', role, status: 'active',
    merchant_id: merchant ? MERCHANT_ID : null, company_id: merchant ? null : COMPANY_ID,
    admin_theme: theme, invite_code: merchant ? null : 'GE-ABC123',
    company: merchant ? null : { id: COMPANY_ID, name: '합성테크', biz_reg_no: '123-45-67890', representative_name: '김대표', status: 'active', contact_email: 'ops@example.invalid' },
    recent_transactions: [], voucher_use_history: [], point_transactions: [],
  };
  const s = series();
  const tx = Array.from({ length: 8 }, (_, i) => ({
    id: 900 + i, user_id: `u-${i}`, company_id: i % 3 ? COMPANY_ID : null, merchant_id: MERCHANT_ID,
    amount: -8000, kind: 'spend', tx_code: `TX${i}`, meal_window: i % 2 ? '석식' : '중식',
    product_name: '점심 뷔페', product_price: 8000, pay_type: i % 3 ? 'ledger' : 'voucher',
    created_at: iso(i * 7 + 1), employee_name: ['김하늘', '이도윤', '박서연', '최지우', '정민준', '강예린', '윤시우', '한지민'][i],
    company_name: i % 3 ? '합성테크' : '일반 고객', employee_no: `E00${i}`, department: '개발팀',
  }));
  return {
    '/me': me,
    '/admin/daily-menu': { merchant: { id: MERCHANT_ID, name: '합성 식당' }, today_menu: { id: 'menu-1', service_date: today, title: '오늘 뷔페 메뉴', menu_text: '제육볶음 · 잡채 · 미역국 · 샐러드', image_url: null, is_active: true }, menus: [{ id: 'menu-1', service_date: today, title: '오늘 뷔페 메뉴', menu_text: '제육볶음 · 잡채 · 미역국 · 샐러드', image_url: null, is_active: true }], service_date: today, migration_required: false },
    '/admin/merchant/companies': { items: [{ id: 'link-1', merchant_id: MERCHANT_ID, company_id: COMPANY_ID, status: 'active', settlement_cycle: 'month_end', unit_price: 8000, tax_type: 'taxable', subsidy_enabled: false, prepurchase_enabled: false, created_at: iso(60 * 24 * 40), company: { id: COMPANY_ID, name: '합성테크', biz_reg_no: '123-45-67890', status: 'active', contact_email: 'ops@example.invalid' }, invite: null, contract: { settlement_cycle: 'month_end', unit_price: 8000, cycle_label: '월말' }, contract_label: '월말 · 단가 8,000원' }] },
    '/admin/merchant/transactions': { items: tx, total_count: 128 },
    '/admin/merchant/qr': { merchant: { id: MERCHANT_ID, name: '합성 식당', biz_reg_no: '111-22-33333', representative_name: '홍사장', business_type: '음식점업', business_item: '한식', address: '서울시 합성구 1', owner_phone: '0212345678', tax_invoice_email: 'tax@example.invalid', bank_name: '합성은행', account_number: '000-000', account_holder: '홍사장', qr_token: 'QR-synthetic' }, qr_token: 'QR-synthetic', migration_required: false },
    '/admin/voucher-products': { items: [{ id: 'vp-1', name: '10+1 식권', voucher_count: 10, bonus_count: 1, unit_price: 8000, discount_rate: 10, sale_price: 72000, status: 'on_sale', display_order: 1, tax_type: 'taxable' }], migration_required: false },
    '/admin/coupons': { items: [{ id: 'cp-1', name: '첫 구매 1,000원', discount_type: 'fixed', discount_value: 1000, is_active: true, is_public: true }], migration_required: false },
    '/admin/notifications': { items: [] },
    '/admin/dashboard/summary': {
      total_amount: s.reduce((a, r) => a + r.amount, 0), total_amount_delta_pct: 12.4,
      total_count: s.reduce((a, r) => a + r.count, 0), total_count_delta_pct: -3.1,
      by_meal_type: [{ label: '중식', amount: 2400000, count: 300, ratio: 72 }, { label: '석식', amount: 900000, count: 117, ratio: 28 }],
      top_companies_by_amount: [{ rank: 1, name: '합성테크', amount: 1800000 }, { rank: 2, name: '가온상사', amount: 900000 }, { rank: 3, name: '일반 고객', amount: 600000 }],
      top_companies_by_count: [{ rank: 1, name: '합성테크', count: 225 }, { rank: 2, name: '가온상사', count: 112 }, { rank: 3, name: '일반 고객', count: 80 }],
      unit: 'day', series: s,
    },
    '/admin/join-requests': { items: [{ id: 'jr-1', company_id: COMPANY_ID, display_name: '신입사원', role: 'employee', status: 'pending', created_at: iso(30) }] },
    '/admin/settlements': { items: [], limit: 20, offset: 0, period_ym: today.slice(0, 7), single_merchant: true, summary: {} },
    '/admin/employees': { items: [{ id: 'e-1', display_name: '김하늘', employee_no: 'E001', phone: '01000000001', department: '개발팀', status: 'active', monthly_limit: 200000, month_used: 64000, point_balance: 5000 }, { id: 'e-2', display_name: '이도윤', employee_no: 'E002', phone: '01000000002', department: '영업팀', status: 'active', monthly_limit: 200000, month_used: 32000, point_balance: 0 }], migration_required: false, bulk_migration_required: false },
    '/admin/meal-policy': { enabled: true, lunch_start: '11:00', lunch_end: '14:00', dinner_start: '17:30', dinner_end: '20:30' },
    '/admin/announcements': { items: [{ id: 'an-1', title: '이번 주 휴무 안내', content: '금요일 석식은 쉽니다.', pinned: true, status: 'published', created_at: iso(600) }] },
    '/admin/reviews': { items: [5, 5, 4, 5, 3, 4, 5, 2].map((rating, i) => ({ id: `rv-${i}`, rating, content: ['맛있어요', '반찬이 다양해요', '국이 짰어요', '최고', '보통', '좋아요', '깔끔해요', '아쉬워요'][i], status: 'visible', author_name: '김*늘님', created_at: iso(i * 300), image_urls: [] })), average_rating: 4.1, review_count: 8 },
  };
}

/** Log in to the admin web with mocked auth + API. Returns recorded API calls. */
export async function adminLogin(page, context, { role = 'merchant_admin', theme = 'default', overrides = {} } = {}) {
  const calls = [];
  await context.route('**/*', (route) => (new URL(route.request().url()).origin === 'http://127.0.0.1:4175' ? route.continue() : route.abort()));
  const user = { id: '11111111-1111-4111-8111-111111111111', email: 'admin@example.invalid', aud: 'authenticated', role: 'authenticated' };
  await page.route('**/auth-fixture/auth/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/logout')) return route.fulfill({ status: 204 });
    return route.fulfill({ json: path.endsWith('/user') ? user : { access_token: 'synthetic-only', refresh_token: 'synthetic-refresh', expires_in: 3600, token_type: 'bearer', user } });
  });
  const data = { ...adminFixtureData(role, theme), ...overrides };
  await page.route('**/api-fixture/**', (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/api-fixture', '');
    const method = route.request().method();
    calls.push({ method, path, body: route.request().postDataJSON?.() ?? null });
    if (method === 'PATCH' && path === '/me/preferences') {
      const body = route.request().postDataJSON();
      return route.fulfill({ json: { ok: true, data: { admin_theme: body.admin_theme } } });
    }
    return route.fulfill({ json: { ok: true, data: data[path] ?? { items: [] } } });
  });
  await page.goto('/');
  await page.getByLabel('이메일', { exact: true }).fill('admin@example.invalid');
  await page.getByLabel('비밀번호', { exact: true }).fill('synthetic-password-only');
  await page.getByRole('button', { name: '운영 시작하기', exact: true }).click();
  const navName = role === 'merchant_admin' ? '식당 관리자 메뉴' : '업체 관리자 메뉴';
  await expect(page.getByRole('navigation', { name: navName })).toBeVisible();
  return calls;
}
