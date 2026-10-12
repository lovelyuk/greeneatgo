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
test('privacy publishes approved officer date and contact while unresolved provider keeps purchases blocked', () => {
  assert.ok(privacy.includes('<li>보호책임자: 손슬기 / 과장</li>'));
  assert.ok(privacy.includes('<li>연락처: 15555952 / greeneat0419@naver.com</li>'));
  assert.ok(privacy.includes('· 시행일 2026.10.12</div>'));
  assert.ok(privacy.includes('이 방침은 2026.10.12부터 적용되며'));
  assert.ok(!privacy.includes('【YYYY.MM.DD】'));
  assert.ok(!privacy.includes('【전화】'));
  assert.ok(!privacy.includes('【이메일】'));
  assert.ok(privacy.includes('【클라우드/호스팅 사업자】'));
  assert.equal(legalDocumentsReady([terms, privacy]), false, 'Incomplete provider publication must not enable signup or purchase');
});
