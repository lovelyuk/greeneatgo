import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

const configPath = new URL('../vercel.json', import.meta.url);
test('Vercel serves purchaser deep links without rewriting admin or static assets', () => {
  assert.ok(existsSync(configPath), 'Purchaser deep links need an explicit Vercel rewrite');
  const config = JSON.parse(readFileSync(configPath, 'utf8'));
  assert.deepEqual(config.rewrites, [
    { source: '/shop', destination: '/index.html' },
    { source: '/shop/', destination: '/index.html' },
  ]);
  for (const path of ['/', '/terms.html', '/privacy.html', '/assets/app.js', '/invite']) {
    assert.equal(config.rewrites.some((rule) => rule.source === path), false);
  }
});
