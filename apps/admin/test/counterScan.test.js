import test from 'node:test';
import assert from 'node:assert/strict';
import { extractMemberCode, extractKioskReceipt, classifyScan, counterResultView, isRepeatScan, REPEAT_SCAN_IGNORE_MS } from '../src/counterScan.js';

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

test('kiosk receipt (24 hex) is recognised and kept apart from the member QR', () => {
  const R = '6ad6e86b3bea82fef79ff23b';
  assert.equal(extractKioskReceipt(R), R);
  assert.equal(extractKioskReceipt(']Q1' + R.toUpperCase() + '\r\n'), R);
  assert.equal(extractKioskReceipt(R + 'ab'), null);
  assert.equal(extractKioskReceipt('QR-DONTO'), null);
  assert.deepEqual(classifyScan(R), { kind: 'kiosk', code: R });
  assert.equal(classifyScan(CODE).kind, 'member');
  assert.equal(classifyScan('hello'), null);
  // 24 digits only is also valid hex, but never confused with the 81-digit member QR.
  assert.equal(classifyScan('1'.repeat(24)).kind, 'kiosk');
});

test('kiosk receipt result views', () => {
  const ok = counterResultView(true, { data: { kind: 'kiosk_receipt', receipt_id: '6ad6e86b3bea82fef79ff23b' } });
  assert.equal(ok.title, '키오스크 식권 사용 완료'); assert.equal(ok.detail, '영수증 …9ff23b'); assert.equal(ok.receipt, true);
  assert.equal(counterResultView(false, { detail: { code: 'KIOSK_RECEIPT_USED' } }).title, '이미 사용된 영수증이에요');
  assert.equal(counterResultView(false, { detail: { code: 'KIOSK_UNAVAILABLE' } }).title, '영수증을 확인하지 못했어요');
  assert.equal(counterResultView(false, { detail: { code: 'KIOSK_NOT_CONFIGURED' } }).title, '키오스크 영수증 준비 중');
});

test('scanner keystrokes map to code characters, also under an IME', async () => {
  const { scanKeyChar } = await import('../src/counterScan.js');
  assert.equal(scanKeyChar({ key: '8', code: 'Digit8' }), '8');
  assert.equal(scanKeyChar({ key: 'a', code: 'KeyA' }), 'a');
  assert.equal(scanKeyChar({ key: ']', code: 'BracketRight' }), ']');
  // IME active: the browser hides the character, the physical key still tells.
  assert.equal(scanKeyChar({ key: 'Process', code: 'Digit1' }), '1');
  assert.equal(scanKeyChar({ key: 'Process', code: 'Numpad7' }), '7');
  assert.equal(scanKeyChar({ key: 'Process', code: 'KeyF' }), 'f');
  assert.equal(scanKeyChar({ key: 'Unidentified', code: 'KeyQ', shiftKey: true }), 'Q');
  // Not part of a code: control keys, space (would click a focused button), unknown.
  for (const key of ['Enter', 'Shift', 'Tab', 'ArrowDown', 'F5', ' ', 'Process', '']) assert.equal(scanKeyChar({ key, code: '' }), '', key);
  assert.equal(scanKeyChar(undefined), '');
});

test('a code held at the scanner is ignored for 10 seconds after it was last seen', () => {
  assert.equal(REPEAT_SCAN_IGNORE_MS, 10000);
  const last = { code: CODE, at: 1_000_000 };
  assert.equal(isRepeatScan(last, CODE, 1_000_000), true);
  assert.equal(isRepeatScan(last, CODE, 1_009_999), true);
  assert.equal(isRepeatScan(last, CODE, 1_010_000), false); // a deliberate re-scan is answered
  assert.equal(isRepeatScan(last, '81' + '2'.repeat(79), 1_000_500), false); // the next guest is never delayed
  assert.equal(isRepeatScan(null, CODE, 1_000_000), false);
  assert.equal(isRepeatScan(last, CODE, 999_000), false); // clock moved backwards: do not swallow scans
});
