import test from 'node:test';
import assert from 'node:assert/strict';
import {
  filterMerchantTransactions,
  isDemoTransaction,
  merchantMealPaymentIds,
  merchantRecentKpis,
  reconcileMerchantPaymentFeed,
} from '../src/merchantPaymentFeed.js';

const real = { id: 10, kind: 'spend', amount: -9000, created_at: '2026-07-28T03:00:00Z' };
const flaggedDemo = { id: 11, kind: 'spend', amount: -71000, flags: { settlement_demo: true }, created_at: '2026-07-28T03:01:00Z' };
const columnDemo = { id: 12, kind: 'spend', amount: -8000, is_demo: true, created_at: '2026-07-28T03:02:00Z' };

test('recognizes both the existing event flag and the proposed is_demo column', () => {
  assert.equal(isDemoTransaction(flaggedDemo), true);
  assert.equal(isDemoTransaction(columnDemo), true);
  assert.equal(isDemoTransaction({ ...real, is_demo: false, flags: { settlement_demo: false } }), false);
});

test('defensively removes marked demo rows and their visible count', () => {
  const result = filterMerchantTransactions({ items: [real, flaggedDemo, columnDemo], total_count: 3 });
  assert.deepEqual(result.items, [real]);
  assert.equal(result.total_count, 1);
});

test('reconciliation only notifies for ids confirmed by the filtered backend feed', () => {
  const result = reconcileMerchantPaymentFeed(
    { items: [real, flaggedDemo], total_count: 2 },
    new Set(['9']),
    true,
  );
  assert.deepEqual(result.newIds, ['10']);
  assert.deepEqual([...result.nextNotifiedIds], ['9', '10']);
  assert.deepEqual(result.list.items, [real]);
});

test('initial reconciliation seeds ids without producing a chime candidate', () => {
  const result = reconcileMerchantPaymentFeed({ items: [real] }, new Set(), false);
  assert.deepEqual(result.newIds, []);
  assert.deepEqual([...result.nextNotifiedIds], ['10']);
});

test('payment ids and dashboard KPIs never include demo rows', () => {
  const list = { items: [real, flaggedDemo], total_count: 2 };
  assert.deepEqual(merchantMealPaymentIds(list), ['10']);
  assert.deepEqual(merchantRecentKpis(list, '2026-07-28'), {
    amount: 9000,
    count: 1,
    loadedCount: 1,
    totalCount: 1,
  });
});
