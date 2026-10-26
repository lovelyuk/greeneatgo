import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { BUSINESS_INFO, BUSINESS_INFO_ROWS } from '../src/businessInfo.js';

const terms = readFileSync(new URL('../public/terms.html', import.meta.url), 'utf8');
const app = readFileSync(new URL('../src/PurchaseApp.jsx', import.meta.url), 'utf8');

test('/shop footer business facts match the terms page', () => {
  assert.ok(terms.includes(`${BUSINESS_INFO.name} / ${BUSINESS_INFO.representative}`));
  for (const key of ['bizRegNo', 'mailOrderNo', 'address', 'email']) assert.ok(terms.includes(BUSINESS_INFO[key]), key);
  assert.ok(terms.includes(BUSINESS_INFO.phone.replace(/-/g, '')), 'phone');
});

test('footer lists every required item (PG review)', () => {
  assert.deepEqual(BUSINESS_INFO_ROWS.map(([label]) => label), ['상호', '대표자', '사업자등록번호', '통신판매업신고', '주소', '이메일', '고객센터']);
  for (const [, value] of BUSINESS_INFO_ROWS) assert.ok(value && !/【|】|TODO/.test(value));
  assert.match(app, /aria-label="사업자 정보"/);
});
