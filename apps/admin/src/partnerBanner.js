export const BANNER_PLACEMENTS = {
  home_bottom: { label: '홈 하단', width: 1200, height: 400, ratio: 3 },
  event_page: { label: '이벤트 페이지', width: 1200, height: 600, ratio: 2 },
};

export function apiItems(data) {
  return Array.isArray(data) ? data : (data?.items ?? []);
}

export function isHttpsUrl(value) {
  if (!value) return false;
  try { return new URL(value).protocol === 'https:'; } catch { return false; }
}

export function imageRatioStatus(width, height, placement) {
  const expected = BANNER_PLACEMENTS[placement]?.ratio ?? BANNER_PLACEMENTS.home_bottom.ratio;
  const actual = Number(width) / Number(height);
  return {
    expected,
    actual: Number.isFinite(actual) ? actual : 0,
    matches: Number.isFinite(actual) && Math.abs(actual - expected) <= 0.03,
  };
}

function numberOrNull(value) {
  return value === '' || value == null ? null : Number(value);
}

export function localDateTimeToUtcIso(value) {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString();
}

export function utcIsoToLocalDateTime(value) {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  const pad = (part) => String(part).padStart(2, '0');
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}T${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

export function bannerFormFromItem(item, fallbackPlacement = 'home_bottom') {
  const reward = item?.reward ?? {};
  return {
    partner_id: item?.partner_id ?? item?.partner?.id ?? '',
    title: item?.title ?? '',
    placement: item?.placement ?? fallbackPlacement,
    image_url: item?.image_url ?? '',
    image_alt: item?.image_alt ?? '',
    link_url: item?.link_url ?? '',
    open_mode: item?.open_mode ?? 'webview',
    starts_at: utcIsoToLocalDateTime(item?.starts_at),
    ends_at: utcIsoToLocalDateTime(item?.ends_at),
    reward_type: reward.reward_type ?? 'none',
    point_amount: reward.point_amount ?? '',
    coupon_id: reward.coupon_id ?? '',
    coupon_valid_days: reward.coupon_valid_days ?? '',
    grant_policy: reward.grant_policy ?? 'once',
    per_user_limit: reward.per_user_limit ?? '',
    total_budget: reward.total_budget ?? '',
    sort_order: item?.sort_order ?? 0,
    is_active: item?.is_active !== false,
  };
}

export function normalizeBannerPayload(form) {
  const rewardType = form.reward_type || 'none';
  const grantPolicy = form.grant_policy || 'once';
  return {
    partner_id: form.partner_id || null,
    title: String(form.title ?? '').trim(),
    placement: form.placement || 'home_bottom',
    image_url: String(form.image_url ?? '').trim(),
    image_alt: String(form.image_alt ?? '').trim(),
    link_url: String(form.link_url ?? '').trim(),
    open_mode: form.open_mode || 'webview',
    starts_at: localDateTimeToUtcIso(form.starts_at),
    ends_at: localDateTimeToUtcIso(form.ends_at),
    reward: {
      reward_type: rewardType,
      point_amount: rewardType === 'point' ? numberOrNull(form.point_amount) : null,
      coupon_id: rewardType === 'coupon' ? (form.coupon_id || null) : null,
      coupon_valid_days: rewardType === 'coupon' ? numberOrNull(form.coupon_valid_days) : null,
      grant_policy: grantPolicy,
      per_user_limit: rewardType !== 'none' && grantPolicy === 'unlimited' ? numberOrNull(form.per_user_limit) : null,
      total_budget: rewardType === 'point' ? numberOrNull(form.total_budget) : null,
    },
    sort_order: Number(form.sort_order ?? 0),
    is_active: form.is_active !== false,
  };
}

export function bannerStatus(item, now = new Date()) {
  if (item?.state && ['live', 'scheduled', 'ended', 'inactive'].includes(item.state)) {
    return { key: item.state, label: { live: '노출중', scheduled: '예약', ended: '종료', inactive: '중지' }[item.state] };
  }
  if (!item?.is_active) return { key: 'inactive', label: '중지' };
  const start = item.starts_at ? new Date(item.starts_at) : null;
  const end = item.ends_at ? new Date(item.ends_at) : null;
  if (start && start > now) return { key: 'scheduled', label: '예약' };
  if (end && end <= now) return { key: 'ended', label: '종료' };
  return { key: 'live', label: '노출중' };
}

export function bannerCtr(item) {
  if (item?.ctr != null) return `${Number(item.ctr).toFixed(2)}%`;
  const impressions = Number(item?.impressions ?? 0);
  const clicks = Number(item?.clicks ?? 0);
  return impressions > 0 ? `${((clicks / impressions) * 100).toFixed(2)}%` : '0.00%';
}

export function bannerListQuery({ placement, state, partnerId }) {
  const query = new URLSearchParams({ placement });
  if (state) query.set('state', state);
  if (partnerId) query.set('partner_id', partnerId);
  return `/admin/banners?${query}`;
}

export function bannerStatsContract(data) {
  return {
    items: Array.isArray(data?.items) ? data.items : [],
    totals: data?.totals ?? {
      impressions: 0,
      clicks: 0,
      ctr: 0,
      granted_amount: 0,
      granted_count: 0,
    },
  };
}
