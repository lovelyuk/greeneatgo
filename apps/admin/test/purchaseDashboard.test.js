import test from 'node:test';
import assert from 'node:assert/strict';
import { dashboardTransactions, dashboardSummary, couponCount, scanIntent } from '../src/purchaseDashboard.js';

test('native history prefers nonempty voucher uses and otherwise recent transactions', () => {
  const use = { id: 'used', amount: -8000 }, recent = { id: 'card', amount: 9000 };
  assert.deepEqual(dashboardTransactions({ voucher_use_history: [use], recent_transactions: [recent] }), [use]);
  assert.deepEqual(dashboardTransactions({ voucher_use_history: [], recent_transactions: [recent] }), [recent]);
  assert.deepEqual(dashboardTransactions({}), []);
  assert.deepEqual(dashboardSummary([use, recent]), { count: 2, amount: 17000 });
});
test('coupon balance is unknown until wallet loads, then counts public and issued separately', () => {
  assert.equal(couponCount(null), null);
  assert.equal(couponCount({ items: [{ id: 'public' }], issued: [{ id: 'issued' }] }), 2);
  assert.equal(couponCount({ items: [], issued: [] }), 0);
});
test('same uncertain scan intent retains its key; another QR cannot replace it', () => {
  const pending = { qr_data: 'QR-SYNTHETIC', idempotency_key: 'synthetic-key' };
  assert.equal(scanIntent(pending, 'QR-SYNTHETIC', () => 'new'), pending);
  assert.throws(() => scanIntent(pending, 'QR-OTHER', () => 'new'), /이전 QR/);
  assert.deepEqual(scanIntent(null, 'QR-SYNTHETIC', () => 'new'), { qr_data: 'QR-SYNTHETIC', idempotency_key: 'new' });
});
