// Admin web theme registry (관리자 화면 테마).
//
// To add a theme:
//   1. add an entry to ADMIN_THEMES below,
//   2. add its id to services/api/app/admin_themes.py (server allow-list),
//   3. add src/themes/<id>.css with the token block (copy calm-dark.css).
// The database stores the id per account (app_users.admin_ui_theme) and only
// checks its format, so a new theme never needs a migration.
//
// `skin` selects shared component styling in src/themes/skins.css. Themes with
// the same skin differ only in colour tokens. `extras` turns on the extra
// widgets (방금 들어온 결제, 별점 분포, 앱 미리보기 …) that only exist in that design.

export const DEFAULT_THEME_ID = 'default';
export const LAST_THEME_STORAGE_KEY = 'greeneat.admin.lastTheme';

export const ADMIN_THEMES = Object.freeze([
  Object.freeze({
    id: 'default', label: '기본', description: '지금 쓰는 밝은 화면',
    skin: null, extras: false, scheme: 'light', logo: '/brand/greeneat_logo.png',
  }),
  Object.freeze({
    id: 'calm-dark', label: 'Calm Dark', description: '어두운 바탕 · 식권 티켓 스타일',
    skin: 'ticket', extras: true, scheme: 'dark', logo: '/brand/greeneat_logo_light.png',
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
