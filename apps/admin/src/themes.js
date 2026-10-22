// Admin web theme registry (관리자 화면 테마).
//
// To add a theme:
//   1. add an entry to ADMIN_THEMES below,
//   2. add its id to services/api/app/admin_themes.py (server allow-list),
//   3. add src/themes/<id>.css with the token block (copy a theme with the same skin),
//      and import it at the top of main.jsx.
// The database stores the id per account (app_users.admin_ui_theme) and only
// checks its format, so a new theme never needs a migration.
//
// Fields
//   skin       shared component styling in src/themes/skins.css (null = default design).
//              Themes with the same skin differ only in colour tokens.
//   dashboard  dashboard layout: 'classic' (default), 'forest' (06), 'compact' (12).
//   trendTabs  big dashboard card tabs, in order: 'calendar' (식권 달력), 'amount', 'count'.
//   navGroups  sidebar group titles (운영 / 업체·정산 / 식당 …).
//   account    sidebar account card.
//   extras     Calm Dark-only widgets (방금 들어온 결제, 별점 분포, 앱 미리보기).
//   chart      line colours for the trend charts.
//   logo       logo on the page background; sidebarLogo (optional) on the sidebar.

export const DEFAULT_THEME_ID = 'default';
export const LAST_THEME_STORAGE_KEY = 'greeneat.admin.lastTheme';

const LIGHT_LOGO = '/brand/greeneat_logo_light.png';
const DARK_LOGO = '/brand/greeneat_logo.png';

export const ADMIN_THEMES = Object.freeze([
  Object.freeze({
    id: 'default', label: '기본', description: '지금 쓰는 밝은 화면',
    skin: null, dashboard: 'classic', trendTabs: [], navGroups: false, account: false, extras: false,
    scheme: 'light', logo: DARK_LOGO, chart: { amount: '#2FB865', count: '#4C8BF5' },
  }),
  Object.freeze({
    id: 'calm-dark', label: 'Calm Dark', description: '어두운 바탕 · 식권 티켓 스타일',
    skin: 'ticket', dashboard: 'classic', trendTabs: [], navGroups: true, account: true, extras: true,
    scheme: 'dark', logo: LIGHT_LOGO, chart: { amount: '#5B87FF', count: '#5B87FF' },
  }),
  Object.freeze({
    id: 'forest-stubs', label: 'Forest Day Stubs', description: '06 배치 · 16-2 색 · 식권 달력',
    skin: 'ticket', dashboard: 'forest', trendTabs: ['calendar', 'amount'], navGroups: true, account: false, extras: false,
    scheme: 'dark', logo: LIGHT_LOGO, chart: { amount: '#5B87FF', count: '#5B87FF' },
  }),
  Object.freeze({
    id: 'forest', label: 'Forest', description: '깊은 숲색 메뉴 · 크림 바탕',
    skin: 'forest', dashboard: 'forest', trendTabs: ['amount', 'count'], navGroups: true, account: false, extras: false,
    scheme: 'light', logo: DARK_LOGO, sidebarLogo: LIGHT_LOGO, chart: { amount: '#2E6B3F', count: '#B5893B' },
  }),
  Object.freeze({
    id: 'compact', label: 'Compact Table', description: '흰 바탕 · 촘촘한 표 · 정보 많이',
    skin: 'compact', dashboard: 'compact', trendTabs: [], navGroups: false, account: false, extras: false,
    scheme: 'light', logo: DARK_LOGO, chart: { amount: '#2C5FFF', count: '#2C5FFF' },
  }),
]);

export function themeById(id) {
  return ADMIN_THEMES.find((theme) => theme.id === id) ?? ADMIN_THEMES[0];
}

export function normalizeThemeId(id) {
  return themeById(id).id;
}

export function themeHasExtras(id) {
  return themeById(id).extras === true;
}

/** Put the theme on <html>; the stylesheets key off these attributes. */
export function applyThemeToDocument(id, root = globalThis.document?.documentElement) {
  const theme = themeById(id);
  if (!root) return theme.id;
  root.dataset.theme = theme.id;
  if (theme.skin) root.dataset.skin = theme.skin; else delete root.dataset.skin;
  if (theme.dashboard && theme.dashboard !== 'classic') root.dataset.dashboard = theme.dashboard; else delete root.dataset.dashboard;
  root.style.colorScheme = theme.scheme;
  return theme.id;
}

/** Last theme on this browser: cosmetic only, for screens shown before login. */
export function readLastTheme(storage = globalThis.localStorage) {
  try { return normalizeThemeId(storage?.getItem(LAST_THEME_STORAGE_KEY)); } catch { return DEFAULT_THEME_ID; }
}

export function rememberLastTheme(id, storage = globalThis.localStorage) {
  try { storage?.setItem(LAST_THEME_STORAGE_KEY, normalizeThemeId(id)); } catch { /* private mode: ignore */ }
}

/** Review summary for the Calm Dark 별점 분포 widget. */
export function ratingDistribution(items) {
  const counts = [5, 4, 3, 2, 1].map((star) => ({ star, count: 0 }));
  let total = 0;
  for (const item of items ?? []) {
    if (item?.status && item.status !== 'visible') continue;
    const rating = Math.round(Number(item?.rating));
    const row = counts.find((entry) => entry.star === rating);
    if (!row) continue;
    row.count += 1; total += 1;
  }
  return counts.map((row) => ({ ...row, ratio: total ? Math.round((row.count * 100) / total) : 0 }));
}

/** Newest payments first, for the Calm Dark "방금 들어온 결제" widget. */
export function latestPayments(items, limit = 5) {
  return (items ?? [])
    .filter((item) => item?.created_at && !['refund', 'cancel'].includes(item.kind))
    .slice()
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
    .slice(0, limit);
}

/* ---------- dashboard helpers (pure; unit-tested) ---------- */

const DOW = ['일', '월', '화', '수', '목', '금', '토'];

function parseYmd(value) {
  const [y, m, d] = String(value).split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}
function ymd(date) { return date.toISOString().slice(0, 10); }

/**
 * 식권 달력: one ticket per day from `from` to the end of `to`'s month, padded to whole
 * Monday-first weeks. Needs a daily series (unit 'day'); days missing from the series
 * had no sales. Days after `to` are kind 'rest' (not in the period / not yet).
 */
export function ticketCalendar(series, from, to, today) {
  if (!from || !to || from > to) return { weeks: [], best: null };
  const byDate = new Map((series ?? []).map((row) => [row.date, row]));
  const start = parseYmd(from);
  const end = parseYmd(to);
  const monthEnd = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth() + 1, 0));
  const last = monthEnd > end ? monthEnd : end;
  const days = Math.round((last - start) / 86400000) + 1;
  if (days > 62) return { weeks: [], best: null };
  let best = null;
  for (const [date, row] of byDate) if (date >= from && date <= to && row.count > 0 && (!best || row.count > best.count)) best = { date, count: row.count };
  const cells = [];
  const lead = (start.getUTCDay() + 6) % 7; // Monday first
  for (let i = 0; i < lead; i += 1) cells.push({ kind: 'blank', key: `b${i}` });
  for (let i = 0; i < days; i += 1) {
    const date = ymd(new Date(start.getTime() + i * 86400000));
    const d = parseYmd(date);
    const base = { key: date, date, day: d.getUTCDate(), month: d.getUTCMonth() + 1, dow: DOW[d.getUTCDay()], sunday: d.getUTCDay() === 0 };
    if (date > to) { cells.push({ ...base, kind: 'rest' }); continue; }
    const row = byDate.get(date);
    const count = row?.count ?? 0;
    const amount = row?.amount ?? 0;
    const kind = date === today ? 'today' : count === 0 && amount === 0 ? 'none' : 'sold';
    cells.push({ ...base, kind, count, amount, best: Boolean(best && best.date === date) });
  }
  while (cells.length % 7) cells.push({ kind: 'blank', key: `e${cells.length}` });
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return { weeks, best };
}

/** 하루 평균 for the compact chips: average count over days that sold anything. */
export function dailyAverage(series, unit) {
  if (unit !== 'day') return null;
  const open = (series ?? []).filter((row) => row.count > 0);
  if (open.length === 0) return { average: 0, openDays: 0 };
  return { average: Math.round(open.reduce((sum, row) => sum + row.count, 0) / open.length), openDays: open.length };
}

/** Compact Table 거래처별 현황: join the amount and count rankings by name. */
export function companyTableRows(byAmount, byCount, totalAmount) {
  const rows = new Map();
  for (const row of byAmount ?? []) rows.set(row.name, { name: row.name, amount: row.amount, count: null });
  for (const row of byCount ?? []) {
    const existing = rows.get(row.name);
    if (existing) existing.count = row.count; else rows.set(row.name, { name: row.name, amount: null, count: row.count });
  }
  return [...rows.values()]
    .sort((a, b) => (b.amount ?? -Infinity) - (a.amount ?? -Infinity) || (b.count ?? 0) - (a.count ?? 0))
    .map((row, index) => ({ ...row, rank: index + 1, share: totalAmount > 0 && row.amount !== null ? Math.round((row.amount * 1000) / totalAmount) / 10 : null }));
}
