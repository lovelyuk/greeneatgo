import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { legalDocumentsReady } from '../src/purchaseSafety.js';
const terms = readFileSync(new URL('../public/terms.html', import.meta.url), 'utf8');
const privacy = readFileSync(new URL('../public/privacy.html', import.meta.url), 'utf8');

test('terms publish user-confirmed business facts and exact approved effective date', () => {
  for (const value of ['2026.10.12', '그린잇 / 오안식', '601-85-17320', '2025-서울금천-1242', '서울특별시 금천구 가산디지털1로 145, 3차동 지하1층 B108~B111호(가산동, 에이스하이엔드타워3차)', '15555952', 'greeneat0419@naver.com']) {
    assert.ok(terms.includes(value), `Missing confirmed value: ${value}`);
  }
  assert.ok(!terms.includes('【YYYY.MM.DD】'));
});
test('privacy names the user-appointed officer without inventing a private phone or provider', () => {
  assert.ok(privacy.includes('보호책임자: 손슬기 / 과장'));
  assert.ok(privacy.includes('【클라우드/호스팅 사업자】'));
  assert.ok(privacy.includes('【YYYY.MM.DD】'), 'Privacy effective date has not been separately approved');
  assert.equal(legalDocumentsReady([terms, privacy]), false, 'Incomplete privacy publication must not enable signup or purchase');
});
