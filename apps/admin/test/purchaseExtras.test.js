import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { safeBannerLink, rewardLabel, reviewPayload, validateNewPassword, headerSubtitle } from '../src/purchaseExtras.js';

test('banner links open only absolute https URLs', () => {
  assert.equal(safeBannerLink('https://partner.example/a?b=1'), 'https://partner.example/a?b=1');
  for (const bad of ['http://partner.example', 'javascript:alert(1)', '//partner.example', '', null, 'not a url', 'data:text/html,x'])
    assert.equal(safeBannerLink(bad), null, String(bad));
});

test('reward label mirrors the app chip', () => {
  assert.equal(rewardLabel({ type: 'none' }), '');
  assert.equal(rewardLabel({ type: 'point', available: true, label: '100P 받기' }), '100P 받기');
  assert.equal(rewardLabel({ type: 'coupon', available: false, label: '쿠폰 받기' }), '지급 완료');
  assert.equal(rewardLabel(null), '');
});

test('review payload matches the API contract', () => {
  assert.deepEqual(reviewPayload('12', 4, '  맛있어요 ', ['a', 'b', 'c', 'd']), { transaction_id: 12, rating: 4, content: '맛있어요', image_urls: ['a', 'b', 'c'] });
  assert.deepEqual(reviewPayload(3, 5, '   '), { transaction_id: 3, rating: 5, content: null, image_urls: [] });
  assert.throws(() => reviewPayload('x', 5, ''));
  assert.throws(() => reviewPayload(1, 0, ''));
  assert.throws(() => reviewPayload(1, 6, ''));
});

test('password change validation', () => {
  assert.match(validateNewPassword('', 'abcdefgh', 'abcdefgh'), /현재/);
  assert.match(validateNewPassword('old', 'short', 'short'), /8자/);
  assert.match(validateNewPassword('old', 'abcdefgh', 'abcdefgX'), /일치/);
  assert.match(validateNewPassword('abcdefgh', 'abcdefgh', 'abcdefgh'), /다른/);
  assert.equal(validateNewPassword('old-pass', 'new-pass-1', 'new-pass-1'), '');
});

test('purchaser header never invents a merchant name', () => {
  assert.equal(headerSubtitle('합성 회사', undefined), '합성 회사');
  assert.equal(headerSubtitle(undefined, '합성 식당'), '합성 식당');
  assert.equal(headerSubtitle('', '  '), '');
  const source = readFileSync(new URL('../src/PurchaseDashboard.jsx', import.meta.url), 'utf8');
  assert.equal(source.includes('돈토'), false);
});
