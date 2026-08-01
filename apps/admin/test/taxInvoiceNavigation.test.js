import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8');

test('keeps one tax invoice menu with issue and completed evidence tabs', () => {
  assert.match(source, /\['tax-invoices', '세금계산서', FileText\]/);
  assert.doesNotMatch(source, /\['settlement-evidence', '증빙 내역'/);
  assert.doesNotMatch(source, /\['tax-invoices', '세금계산서 발행'/);
  assert.match(source, />발행 관리<\/button>/);
  assert.match(source, />발행 완료·증빙 내역<\/button>/);
  assert.match(source, /section === 'settlement-evidence'.*initialTab="evidence"/);
});
