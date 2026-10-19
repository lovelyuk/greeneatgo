import test from 'node:test';
import assert from 'node:assert/strict';
import { extractMemberCode, counterResultView } from '../src/counterScan.js';

const CODE = '81' + '1'.repeat(79);

test('member code is extracted from raw scanner input', () => {
  assert.equal(extractMemberCode(CODE), CODE);
  assert.equal(extractMemberCode(CODE + '\r\n'), CODE);
  assert.equal(extractMemberCode(']Q1' + CODE), CODE);
  assert.equal(extractMemberCode('QR-DONTO'), null);
  assert.equal(extractMemberCode('81' + '1'.repeat(40)), null);
  assert.equal(extractMemberCode(null), null);
});

test('result view: success, duplicate and errors are explicit', () => {
  const ok = counterResultView(true, { data: { member_name: '김구매', remaining: 4, duplicate: false } });
  assert.equal(ok.kind, 'success'); assert.equal(ok.title, '식권 1장 사용 완료'); assert.equal(ok.detail, '남은 식권 4장'); assert.equal(ok.name, '김구매님');
  const dup = counterResultView(true, { data: { member_name: '김구매', remaining: 4, duplicate: true } });
  assert.match(dup.title, /이미 사용 처리/);
  assert.equal(counterResultView(false, { detail: { code: 'NO_VOUCHER' } }).title, '남은 식권이 없어요');
  assert.equal(counterResultView(false, { detail: { code: 'MEAL_QR_EXPIRED' } }).title, 'QR 시간이 지났어요');
  assert.equal(counterResultView(false, { detail: { code: 'WHATEVER', message: '서버 메시지' } }).detail, '서버 메시지');
});
