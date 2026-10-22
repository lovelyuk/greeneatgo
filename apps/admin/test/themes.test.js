import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {
  ADMIN_THEMES, DEFAULT_THEME_ID, LAST_THEME_STORAGE_KEY, applyThemeToDocument, companyTableRows, dailyAverage,
  latestPayments, normalizeThemeId, ratingDistribution, readLastTheme, rememberLastTheme, themeById, themeHasExtras,
  ticketCalendar,
} from '../src/themes.js';

test('default theme is first and is the current design; calm-dark is registered with extras', () => {
  assert.equal(DEFAULT_THEME_ID, 'default');
  assert.equal(ADMIN_THEMES[0].id, 'default');
  assert.equal(ADMIN_THEMES[0].skin, null);
  assert.equal(themeHasExtras('default'), false);
  assert.equal(themeHasExtras('calm-dark'), true);
  assert.equal(new Set(ADMIN_THEMES.map((t) => t.id)).size, ADMIN_THEMES.length);
});

test('unknown theme ids fall back to default', () => {
  for (const value of [undefined, null, '', 'neon', 'CALM-DARK']) assert.equal(normalizeThemeId(value), 'default');
  assert.equal(normalizeThemeId('calm-dark'), 'calm-dark');
});

test('web registry and API allow-list list the same theme ids', async () => {
  const py = await readFile(new URL('../../../services/api/app/admin_themes.py', import.meta.url), 'utf8');
  const ids = [...py.matchAll(/"([a-z0-9-]+)"/g)].map((m) => m[1]).filter((id) => id !== 'merchant_admin' && !id.endsWith('_admin'));
  for (const theme of ADMIN_THEMES) assert.ok(ids.includes(theme.id) || theme.id === 'default', `API missing ${theme.id}`);
});

test('every non-default theme has its stylesheet and is imported', async () => {
  const main = await readFile(new URL('../src/main.jsx', import.meta.url), 'utf8');
  for (const theme of ADMIN_THEMES.filter((t) => t.id !== 'default')) {
    await readFile(new URL(`../src/themes/${theme.id}.css`, import.meta.url), 'utf8');
    assert.match(main, new RegExp(`import './themes/${theme.id}.css'`));
  }
});

test('theme stylesheets are scoped so the default design cannot change', async () => {
  for (const file of ['skins.css', 'layouts.css', ...ADMIN_THEMES.filter((t) => t.id !== 'default').map((t) => `${t.id}.css`)]) {
    const css = (await readFile(new URL(`../src/themes/${file}`, import.meta.url), 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '');
    const selectors = [...css.matchAll(/(^|})\s*([^{}@]+)\{/g)].map((m) => m[2].trim()).filter(Boolean);
    assert.ok(selectors.length > 0, file);
    for (const group of selectors) {
      for (const selector of group.split(',').map((s) => s.trim()).filter(Boolean)) {
        if (/^(from|to|\d+%)$/.test(selector)) continue;
        assert.match(selector, /^:root\[data-(theme|skin|dashboard)=/, `${file}: unscoped selector "${selector}"`);
      }
    }
  }
});

test('applyThemeToDocument sets theme, skin and color-scheme attributes', () => {
  const root = { dataset: {}, style: {} };
  assert.equal(applyThemeToDocument('calm-dark', root), 'calm-dark');
  assert.deepEqual({ ...root.dataset }, { theme: 'calm-dark', skin: 'ticket' });
  assert.equal(root.style.colorScheme, 'dark');
  applyThemeToDocument('forest-stubs', root);
  assert.deepEqual({ ...root.dataset }, { theme: 'forest-stubs', skin: 'ticket', dashboard: 'forest' });
  applyThemeToDocument('neon', root);
  assert.deepEqual({ ...root.dataset }, { theme: 'default' });
  assert.equal(root.style.colorScheme, 'light');
});

test('last theme memory tolerates broken storage', () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  assert.equal(readLastTheme(storage), 'default');
  rememberLastTheme('calm-dark', storage);
  assert.equal(store.get(LAST_THEME_STORAGE_KEY), 'calm-dark');
  assert.equal(readLastTheme(storage), 'calm-dark');
  const broken = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
  assert.equal(readLastTheme(broken), 'default');
  assert.doesNotThrow(() => rememberLastTheme('calm-dark', broken));
});

test('rating distribution counts visible reviews only, 5 to 1', () => {
  const rows = ratingDistribution([{ rating: 5 }, { rating: 5 }, { rating: 4 }, { rating: 1, status: 'hidden' }, { rating: 9 }]);
  assert.deepEqual(rows.map((r) => [r.star, r.count, r.ratio]), [[5, 2, 67], [4, 1, 33], [3, 0, 0], [2, 0, 0], [1, 0, 0]]);
  assert.deepEqual(ratingDistribution([]).map((r) => r.ratio), [0, 0, 0, 0, 0]);
});

test('latest payments drop refunds and sort newest first', () => {
  const rows = latestPayments([
    { id: 1, kind: 'spend', created_at: '2026-10-21T01:00:00Z' },
    { id: 2, kind: 'refund', created_at: '2026-10-21T03:00:00Z' },
    { id: 3, kind: 'payment', created_at: '2026-10-21T02:00:00Z' },
    { id: 4, kind: 'spend' },
  ], 5);
  assert.deepEqual(rows.map((r) => r.id), [3, 1]);
});

test('every theme declares a known skin, dashboard layout and tabs', async () => {
  const skins = await readFile(new URL('../src/themes/skins.css', import.meta.url), 'utf8');
  for (const theme of ADMIN_THEMES) {
    assert.ok(['classic', 'forest', 'compact'].includes(theme.dashboard), theme.id);
    for (const tab of theme.trendTabs) assert.ok(['calendar', 'amount', 'count'].includes(tab), `${theme.id}: ${tab}`);
    if (theme.skin) assert.match(skins, new RegExp(`:root\\[data-skin="${theme.skin}"\\]`), `${theme.id}: skin ${theme.skin} has no rules`);
    assert.ok(theme.chart?.amount && theme.chart?.count, theme.id);
  }
  assert.deepEqual(themeById('forest-stubs').trendTabs, ['calendar', 'amount']);
  assert.equal(themeById('forest').dashboard, 'forest');
  assert.equal(themeById('compact').dashboard, 'compact');
  for (const id of ['forest-stubs', 'forest', 'compact']) assert.equal(themeHasExtras(id), false, `${id}: Calm Dark extras stay Calm Dark only`);
});

test('ticket calendar: Monday-first weeks to month end, no-sale days, today, best day', () => {
  const series = [
    { date: '2026-10-01', amount: 70000, count: 10 },
    { date: '2026-10-02', amount: 140000, count: 20 },
    { date: '2026-10-05', amount: 35000, count: 5 },
  ];
  const { weeks, best } = ticketCalendar(series, '2026-10-01', '2026-10-05', '2026-10-05');
  assert.deepEqual(best, { date: '2026-10-02', count: 20 });
  const cells = weeks.flat();
  assert.equal(cells.length % 7, 0);
  assert.deepEqual(cells.slice(0, 3).map((c) => c.kind), ['blank', 'blank', 'blank']); // 10/1 is Thursday
  const byDate = Object.fromEntries(cells.filter((c) => c.date).map((c) => [c.date, c]));
  assert.equal(byDate['2026-10-01'].kind, 'sold');
  assert.equal(byDate['2026-10-02'].best, true);
  assert.equal(byDate['2026-10-03'].kind, 'none');
  assert.equal(byDate['2026-10-05'].kind, 'today');
  assert.equal(byDate['2026-10-06'].kind, 'rest');
  assert.equal(byDate['2026-10-31'].kind, 'rest');
  assert.equal(byDate['2026-10-04'].sunday, true);
  assert.equal(byDate['2026-10-01'].dow, '목');
});

test('ticket calendar refuses long or reversed periods instead of drawing hundreds of tickets', () => {
  assert.deepEqual(ticketCalendar([], '2026-01-01', '2026-06-30', '2026-06-30').weeks, []);
  assert.deepEqual(ticketCalendar([], '2026-10-05', '2026-10-01', '2026-10-05').weeks, []);
});

test('daily average counts only days with sales and only for daily series', () => {
  assert.deepEqual(dailyAverage([{ count: 10 }, { count: 0 }, { count: 21 }], 'day'), { average: 16, openDays: 2 });
  assert.equal(dailyAverage([{ count: 10 }], 'week'), null);
  assert.deepEqual(dailyAverage([], 'day'), { average: 0, openDays: 0 });
});

test('compact company rows join both rankings by name, sort by amount, compute share', () => {
  const rows = companyTableRows(
    [{ rank: 1, name: 'A', amount: 600 }, { rank: 2, name: 'B', amount: 300 }],
    [{ rank: 1, name: 'B', count: 40 }, { rank: 2, name: 'C', count: 7 }],
    1000,
  );
  assert.deepEqual(rows.map((r) => [r.rank, r.name, r.count, r.amount, r.share]), [[1, 'A', null, 600, 60], [2, 'B', 40, 300, 30], [3, 'C', 7, null, null]]);
  assert.deepEqual(companyTableRows([{ name: 'A', amount: 0 }], [], 0).map((r) => r.share), [null]);
});
