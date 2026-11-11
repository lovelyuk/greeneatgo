// Which URLs stay inside the app window and which go to the system browser.
// Pure functions so they can be unit-tested without Electron.
const APP_ORIGIN = 'https://greeneatgo.vercel.app';
const APP_URL = `${APP_ORIGIN}/`;

function parse(url) {
  try { return new URL(url); } catch { return null; }
}

/** Main window may only show the admin web itself. */
function isAppUrl(url) {
  const u = parse(url);
  return Boolean(u && u.origin === APP_ORIGIN);
}

/**
 * window.open() decisions.
 *  - same-origin / about:blank / blob: (receipts, PDF previews the admin opens) → new app window
 *  - http(s) elsewhere (e.g. legal links, partner banners) → default browser
 *  - anything else (file:, javascript:, custom schemes) → blocked
 */
function popupAction(url) {
  if (url === 'about:blank' || url === '') return 'window';
  const u = parse(url);
  if (!u) return 'deny';
  if (u.protocol === 'blob:') return u.origin === APP_ORIGIN || url.startsWith(`blob:${APP_ORIGIN}/`) ? 'window' : 'deny';
  if (u.origin === APP_ORIGIN) return 'window';
  if (u.protocol === 'https:' || u.protocol === 'http:' || u.protocol === 'mailto:' || u.protocol === 'tel:') return 'external';
  return 'deny';
}

module.exports = { APP_ORIGIN, APP_URL, isAppUrl, popupAction };
