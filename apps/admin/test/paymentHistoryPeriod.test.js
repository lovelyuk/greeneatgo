import test from 'node:test';
import assert from 'node:assert/strict';
import { paymentHistoryPeriod } from '../src/paymentHistoryPeriod.js';

const base = {
  current: '2026-07-29',
  date: '2026-07-29',
  month: '2026-04',
  range: { from: '2026-04-01', to: '2026-04-30' },
};

test('builds a past month query instead of pinning month mode to the current month', () => {
  assert.deepEqual(paymentHistoryPeriod({ ...base, mode: 'month' }), {
    baseDate: '2026-04-01', granularity: 'month', end: '', label: '4월',
  });
});

test('keeps date, range and year query semantics', () => {
  assert.equal(paymentHistoryPeriod({ ...base, mode: 'date' }).granularity, 'day');
  assert.equal(paymentHistoryPeriod({ ...base, mode: 'range' }).end, '&end_date=2026-04-30');
  assert.equal(paymentHistoryPeriod({ ...base, mode: 'year' }).baseDate, '2026-01-01');
});
