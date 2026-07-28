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

test('keeps marked demo rows integrated in the visible feed and count', () => {
  const result = filterMerchantTransactions({ items: [real, flaggedDemo, columnDemo], total_count: 3 });
  assert.deepEqual(result.items, [real, flaggedDemo, columnDemo]);
  assert.equal(result.total_count, 3);
});

test('reconciliation notifies for real and demo ids confirmed by the backend feed', () => {
  const result = reconcileMerchantPaymentFeed(
    { items: [real, flaggedDemo], total_count: 2 },
    new Set(['9']),
    true,
  );
  assert.deepEqual(result.newIds, ['10', '11']);
  assert.deepEqual([...result.nextNotifiedIds], ['9', '10', '11']);
  assert.deepEqual(result.list.items, [real, flaggedDemo]);
});

test('initial reconciliation seeds ids without producing a chime candidate', () => {
  const result = reconcileMerchantPaymentFeed({ items: [real] }, new Set(), false);
  assert.deepEqual(result.newIds, []);
  assert.deepEqual([...result.nextNotifiedIds], ['10']);
});

test('payment ids and dashboard KPIs include demo rows', () => {
  const list = { items: [real, flaggedDemo], total_count: 2 };
  assert.deepEqual(merchantMealPaymentIds(list), ['10', '11']);
  assert.deepEqual(merchantRecentKpis(list, '2026-07-28'), {
    amount: 80000,
    count: 2,
    loadedCount: 2,
    totalCount: 2,
  });
});
