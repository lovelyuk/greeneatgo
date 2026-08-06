import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8');

test('keeps one evidence menu with tax invoice issue and completed evidence tabs', () => {
  assert.match(source, /\['tax-invoices', '증빙 내역', FileText\]/);
  assert.match(source, /\['company-tax-invoices', '증빙 내역', FileText\]/);
  assert.doesNotMatch(source, /\['settlement-evidence', '증빙 내역'/);
  assert.doesNotMatch(source, /\['tax-invoices', '세금계산서'/);
  assert.match(source, />발행 관리<\/button>/);
  assert.match(source, />발행 완료·증빙 내역<\/button>/);
  assert.match(source, /section === 'settlement-evidence'.*initialTab="evidence"/);
});

test('connects VAT and settlement document buttons to file APIs without placeholders', () => {
  assert.match(source, /settlements\/evidence\/export\?year=/);
  assert.match(source, /settlementId|selected\.id/);
  assert.match(source, /\/document\?format=\$\{format\}/);
  assert.match(source, /handleSettlementDocument\('xlsx'\)/);
  assert.match(source, /handleSettlementDocument\('html'\)/);
  assert.match(source, /handleSettlementDocument\('pdf'\)/);
  assert.match(source, /현재 조회 조건에 다운로드할 증빙 내역이 없습니다/);
  assert.doesNotMatch(source, /정산자료 엑셀 다운로드는 현재 제공되지 않습니다/);
  assert.doesNotMatch(source, /증빙내역 엑셀 다운로드는 현재 제공되지 않습니다/);
});

test('separates settlement evidence date, time, department, and employee number columns', () => {
  assert.match(source, /function formatKoreanDateTimeParts\(value\)/);
  assert.match(source, /<th>거래 날짜<\/th><th>거래 시간<\/th><th>이름<\/th><th>부서<\/th><th>사번<\/th>/);
  assert.match(source, /transactionDateTime\.date/);
  assert.match(source, /transactionDateTime\.time/);
  assert.doesNotMatch(source, /\[row\.department, row\.employee_no\]\.filter\(Boolean\)\.join\(' \/ '\)/);
});
