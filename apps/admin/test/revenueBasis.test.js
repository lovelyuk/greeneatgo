import test from 'node:test';
import assert from 'node:assert/strict';
import { dateTimeParts, mapRevenueDetail, mapRevenueSummary, partyByName, won } from '../src/revenueBasis.js';

test('summary maps both bases and tolerates missing fields', () => {
  const summary = mapRevenueSummary({
    paid_basis: { payment_amount: 94000, refund_amount: 8000, net_payment_amount: 86000, invoice_amount: 176000, invoice_count: 1, payment_count: 3, revenue_amount: 262000, point_amount: 1000, subsidy_amount: 5000, subsidy_count: 5 },
    usage_basis: { amount: 19800, count: 3 }, unbilled: { amount: 19800, count: 2 },
    parties: [
      { key: 'c1', name: '합성테크', revenue_amount: 176000, net_payment_amount: 0, invoice_amount: 176000, usage_amount: 8800, usage_count: 1, unbilled_amount: 8800 },
      { key: 'personal', name: '개인 고객', revenue_amount: 80000, usage_amount: 8000, usage_count: 1 },
      { name: '키 없음' },
    ],
  });
  assert.deepEqual(summary.paid, { revenue: 262000, payment: 94000, refund: 8000, netPayment: 86000, invoice: 176000, invoiceCount: 1, subsidy: 5000, subsidyCount: 5, paymentCount: 3, point: 1000 });
  assert.deepEqual(summary.usage, { amount: 19800, count: 3 });
  assert.deepEqual(summary.unbilled, { amount: 19800, count: 2 });
  assert.deepEqual(summary.parties.map((party) => [party.key, party.unbilled_amount, party.invoice_amount]), [['c1', 8800, 176000], ['personal', 0, 0]]);
  assert.deepEqual(mapRevenueSummary(undefined), { paid: { revenue: 0, payment: 0, refund: 0, netPayment: 0, invoice: 0, invoiceCount: 0, subsidy: 0, subsidyCount: 0, paymentCount: 0, point: 0 }, usage: { amount: 0, count: 0 }, unbilled: { amount: 0, count: 0 }, parties: [] });
  assert.equal(partyByName(summary.parties, ' 합성테크 ').key, 'c1');
  assert.equal(partyByName(summary.parties, '기타'), null);
  assert.equal(partyByName(summary.parties, ''), null);
  assert.equal(won(-8000), '-₩8,000');
});

test('detail rows are labelled and shown in Korean time', () => {
  assert.deepEqual(dateTimeParts('2026-11-05T15:30:00+00:00'), { date: '2026-11-06', time: '00:30' });
  assert.deepEqual(dateTimeParts('nope'), { date: '-', time: '-' });
  const detail = mapRevenueDetail({
    party: { key: 'c1', name: '합성테크' }, detail_limit: 500,
    paid_basis: { revenue_amount: 168000, payment_amount: 0, refund_amount: 8000, invoice_amount: 176000, subsidy_amount: 0, entry_count: 4, entries: [
      { kind: 'subsidy', at: '2026-11-04T03:00:00+00:00', amount: 1000, label: '회사 보조금 (식권 구매)', method: '', person_name: '박민수' },
      { kind: 'subsidy_refund', at: '2026-11-04T04:00:00+00:00', amount: -1000, label: '회사 보조금 환불 (미사용 식권)', method: '', person_name: '박민수' },
      { kind: 'invoice', at: '2026-11-05T05:00:00+00:00', amount: 176000, label: '세금계산서 발행', method: '20261105-1', person_name: '-' },
      { kind: 'refund', at: '2026-11-06T02:00:00+00:00', amount: -8000, point_amount: -300, label: '1장 식권', method: '네이버페이', person_name: '이손님' },
    ] },
    usage_basis: { amount: 8800, count: 2, cancel_count: 1, item_count: 900, daily: [{ date: '2026-11-15', count: 1, cancel_count: 1, amount: 0 }], items: [
      { id: 1, at: '2026-11-03T03:00:00+00:00', kind: 'spend', pay_type: 'ledger', item: '중식', amount: 8800, person_name: '김하늘', department: null, employee_no: 'E1' },
      { id: 3, at: '2026-11-15T03:00:00+00:00', kind: 'cancel', pay_type: 'ledger', item: '중식', amount: -8800, person_name: '김하늘' },
      { id: 4, at: '2026-11-16T03:00:00+00:00', kind: 'spend', pay_type: 'subsidized', item: '석식', amount: 3000, person_name: '박민수' },
    ] },
    unbilled: { amount: 8800, settlements: [{ period_ym: '2026-11', amount: 8800 }] },
  });
  assert.equal(detail.name, '합성테크');
  assert.deepEqual(detail.paid.entries.map((row) => [row.date, row.time, row.kindLabel, row.who, row.note, row.amount]), [
    ['2026-11-04', '12:00', '회사 보조금', '박민수', '', 1000],
    ['2026-11-04', '13:00', '보조금 환불', '박민수', '', -1000],
    ['2026-11-05', '14:00', '세금계산서', '', '20261105-1', 176000],
    ['2026-11-06', '11:00', '환불', '이손님', '네이버페이', -8000],
  ]);
  assert.deepEqual(detail.paid.entries.map((row) => row.point), [0, 0, 0, -300]);
  assert.equal(detail.paid.subsidy, 0);
  assert.deepEqual(detail.usage.items.map((row) => [row.kindLabel, row.department, row.employeeNo, row.amount]), [
    ['장부', '-', 'E1', 8800], ['취소', '-', '-', -8800], ['보조금', '-', '-', 3000]]);
  assert.equal(detail.usage.itemCount, 900);
  assert.deepEqual(detail.unbilled.settlements, [{ month: '2026-11', amount: 8800 }]);
  assert.equal(mapRevenueDetail(undefined).paid.entries.length, 0);
});
