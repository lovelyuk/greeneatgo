import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  BANNER_PLACEMENTS,
  apiItems,
  bannerCtr,
  bannerFormFromItem,
  bannerListQuery,
  bannerStatsContract,
  bannerStatus,
  imageRatioStatus,
  isHttpsUrl,
  localDateTimeToUtcIso,
  normalizeBannerPayload,
  utcIsoToLocalDateTime,
} from '../src/partnerBanner.js';

const source = readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8');
const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');

test('apiFetch-unwrapped lists and FINAL placement identifiers are handled', () => {
  assert.deepEqual(apiItems([{ id: 1 }]), [{ id: 1 }]);
  assert.deepEqual(apiItems({ items: [{ id: 2 }] }), [{ id: 2 }]);
  assert.deepEqual(Object.keys(BANNER_PLACEMENTS), ['home_bottom', 'event_page']);
  assert.equal(imageRatioStatus(1200, 400, 'home_bottom').matches, true);
  assert.equal(imageRatioStatus(1200, 600, 'event_page').matches, true);
  assert.equal(imageRatioStatus(1200, 500, 'home_bottom').matches, false);
});

test('datetime-local values round-trip between API UTC and browser local time', () => {
  const local = new Date(2030, 5, 1, 9, 37, 0, 0);
  const utcIso = local.toISOString();
  const localValue = utcIsoToLocalDateTime(utcIso);
  assert.equal(localValue, '2030-06-01T09:37');
  assert.equal(localDateTimeToUtcIso(localValue), utcIso);
  assert.equal(bannerFormFromItem({ starts_at: utcIso }).starts_at, localValue);
});

test('banner list filters use exact query names and stats use exact server fields', () => {
  assert.equal(
    bannerListQuery({ placement: 'event_page', state: 'ended', partnerId: 'partner-1' }),
    '/admin/banners?placement=event_page&state=ended&partner_id=partner-1',
  );
  const response = {
    items: [{ day: '2030-06-01', impressions: 100, clicks: 4, ctr: 4, granted_amount: 300, granted_count: 3 }],
    totals: { impressions: 100, clicks: 4, ctr: 4, granted_amount: 300, granted_count: 3 },
  };
  assert.deepEqual(bannerStatsContract(response), response);
  assert.equal(bannerCtr(response.items[0]), '4.00%');
});

test('point fixture normalizes to the exact FINAL request contract', () => {
  const request = normalizeBannerPayload({
    partner_id: 'partner-1',
    title: '  여름 배너  ',
    placement: 'home_bottom',
    image_url: ' https://cdn.example/banner.webp ',
    image_alt: ' 여름 이벤트 ',
    link_url: ' https://partner.example/event ',
    open_mode: 'external',
    starts_at: '2030-06-01T00:00:00.000Z',
    ends_at: '',
    reward_type: 'point',
    point_amount: '100',
    coupon_id: 'must-not-leak',
    coupon_valid_days: '30',
    grant_policy: 'unlimited',
    per_user_limit: '5',
    total_budget: '10000',
    sort_order: '3',
    is_active: true,
  });
  assert.deepEqual(request, {
    partner_id: 'partner-1',
    title: '여름 배너',
    placement: 'home_bottom',
    image_url: 'https://cdn.example/banner.webp',
    image_alt: '여름 이벤트',
    link_url: 'https://partner.example/event',
    open_mode: 'external',
    starts_at: '2030-06-01T00:00:00.000Z',
    ends_at: null,
    reward: {
      reward_type: 'point',
      point_amount: 100,
      coupon_id: null,
      coupon_valid_days: null,
      grant_policy: 'unlimited',
      per_user_limit: 5,
      total_budget: 10000,
    },
    sort_order: 3,
    is_active: true,
  });
});

test('coupon fixture and nested response round-trip without flattened legacy fields', () => {
  const response = {
    id: 'banner-1', partner_id: 'partner-1', partner: { id: 'partner-1', name: 'Partner' },
    title: 'Coupon', placement: 'event_page', image_url: 'https://cdn.example/c.webp',
    image_alt: 'coupon ad', link_url: 'https://partner.example/coupon', open_mode: 'webview',
    starts_at: null, ends_at: null, sort_order: 7, is_active: false,
    reward: { reward_type: 'coupon', point_amount: null, coupon_id: 'coupon-1', coupon_valid_days: 14, grant_policy: 'daily', per_user_limit: null, total_budget: null },
  };
  const form = bannerFormFromItem(response);
  assert.deepEqual(form, {
    partner_id: 'partner-1', title: 'Coupon', placement: 'event_page',
    image_url: 'https://cdn.example/c.webp', image_alt: 'coupon ad',
    link_url: 'https://partner.example/coupon', open_mode: 'webview', starts_at: '', ends_at: '',
    reward_type: 'coupon', point_amount: '', coupon_id: 'coupon-1', coupon_valid_days: 14,
    grant_policy: 'daily', per_user_limit: '', total_budget: '', sort_order: 7, is_active: false,
  });
  assert.deepEqual(normalizeBannerPayload(form).reward, response.reward);
});

test('HTTPS, states and CTR behavior match the management UI', () => {
  assert.equal(isHttpsUrl('https://example.com/ad'), true);
  assert.equal(isHttpsUrl('http://example.com/ad'), false);
  assert.equal(isHttpsUrl('not a url'), false);
  assert.deepEqual(bannerStatus({ state: 'live' }), { key: 'live', label: '노출중' });
  assert.equal(bannerStatus({ is_active: false }).key, 'inactive');
  assert.equal(bannerStatus({ is_active: true, starts_at: '2030-01-02T00:00:00Z' }, new Date('2030-01-01T00:00:00Z')).key, 'scheduled');
  assert.equal(bannerStatus({ is_active: true, ends_at: '2029-01-01T00:00:00Z' }, new Date('2030-01-01T00:00:00Z')).key, 'ended');
  assert.equal(bannerCtr({ impressions: 200, clicks: 5 }), '2.50%');
});

test('UI wiring uses FINAL endpoints, unwrapped contracts, nested list fields and restaurant management tabs', () => {
  assert.match(source, /\['partners', '제휴사'\]/);
  assert.match(source, /\['partner-banners', '배너 광고 설정'\]/);
  assert.match(source, /merchantContentSection === 'partners'/);
  assert.match(source, /merchantContentSection === 'partner-banners'/);
  assert.doesNotMatch(source, /\[\['partners', '제휴사', Building2\], \['partner-banners'/);
  assert.match(source, /apiFetch\('\/admin\/coupons\?issuable=true'/);
  assert.match(source, /apiFetch\('\/admin\/banners\/reorder'.*method: 'PATCH'.*items: next\.map.*sort_order:/s);
  assert.match(source, /data\.append\('partner_id', form\.partner_id\).*data\.append\('placement', form\.placement\).*data\.append\('image', file\)/s);
  assert.match(source, /uploaded\.image_url \?\? uploaded\.url/);
  assert.match(source, /setItems\(bannerData\.items\)/);
  assert.match(source, /item\.partner\.name/);
  assert.match(source, /item\.stats\.impressions/);
  assert.match(source, /item\.stats\.clicks/);
  assert.match(source, /item\.reward\?\.reward_type/);
  assert.match(source, /\/admin\/banners\/\$\{banner\.id\}\/stats\?from=\$\{range\.from\}&to=\$\{range\.to\}/);
  assert.match(source, /row\.day/);
  assert.match(source, /row\.granted_amount/);
  assert.match(source, /row\.granted_count/);
});

test('modal order and optional period match FINAL UX contract', () => {
  const editor = source.slice(source.indexOf('function BannerEditorModal'), source.indexOf('function BannerStatsModal'));
  const labels = ['제휴사<select', '배너 제목<input', '노출 위치<select', '배너 이미지<input', '대체 텍스트<input', '이동 URL (HTTPS)', '열기 방식', '노출 시작 일시 (선택)', '리워드 유형<select', '지급 정책<select', '사용자별 지급 한도', '총 포인트 예산', '활성화'];
  let previous = -1;
  for (const label of labels) {
    const index = editor.indexOf(label);
    assert.ok(index > previous, `${label} must appear in FINAL order`);
    previous = index;
  }
  assert.doesNotMatch(editor, /starts_at} required/);
  assert.doesNotMatch(editor, /ends_at}[^>]*required/);
  assert.match(editor, /disabled=\{busy \|\| !form\.partner_id\}/);
  assert.match(editor, /value="once"/);
  assert.match(editor, /value="daily"/);
  assert.match(editor, /value="unlimited"/);
});

test('partner management requires HTTPS site_url and supports exact profile states', () => {
  assert.match(source, /site_url: ''/);
  assert.match(source, /value=\{form\.site_url\} required pattern="https:\/\/\.\*"/);
  assert.match(source, /logo_url: ''/);
  assert.match(source, /contact_name: ''/);
  assert.match(source, /contact_email: ''/);
  assert.match(source, /contact_phone: ''/);
  assert.match(source, /memo: ''/);
  assert.match(source, /status: 'active'/);
  assert.match(source, /<option value="active">활성<\/option><option value="paused">일시중지<\/option><option value="ended">종료<\/option>/);
  const partnerScreen = source.slice(source.indexOf('const blankPartner'), source.indexOf('const blankBanner'));
  assert.doesNotMatch(partnerScreen, /inactive/);
  assert.match(source, /partner\.status === 'active' \|\| \(item && partner\.id === form\.partner_id\)/);
});

test('partner banner CSS is scoped and protects 360px layout', () => {
  assert.match(css, /\/\* Partner advertising management \*\//);
  assert.match(css, /\.partner-admin-page[^}]+min-width: 0/);
  assert.match(css, /\.banner-table-wrap[^}]+overflow-x: auto/);
  assert.match(css, /@media \(max-width: 560px\)[\s\S]+\.banner-modal-backdrop \{ padding: 8px; \}/);
  assert.match(css, /\.banner-editor-modal, \.banner-stats-modal \{ width: 100%/);
});
