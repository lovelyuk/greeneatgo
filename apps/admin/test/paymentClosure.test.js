import { test } from 'node:test';
import assert from 'node:assert/strict';
import { verifiedOrderClosure } from '../src/paymentClosure.js';
const pending = { order_id: 'GE-synthetic', amount: 100 };
const good = { ...pending, user_id: 'current-owner', recovery_action: 'closed', resumable: false,
  status: 'failed', checkout_url: null, completion: null,
  closure: { id: '00000000-0000-4000-8000-000000000003', evidence_sha256: 'a'.repeat(64),
    scope: 'order', finality: 'verified', outcome: 'failed', closed_at: '2026-10-14T00:00:00Z' } };
test('exact authenticated failed closure is trusted', () => assert.equal(verifiedOrderClosure(good, pending, 'current-owner'), true));
for (const [field, value] of Object.entries({ user_id: 'other', order_id: 'GE-other', amount: '100', status: 'ready',
  recovery_action: 'reconcile', resumable: true, checkout_url: 'https://fixture.invalid', completion: {}, closure: null }))
  test(`closure rejects ${field}`, () => assert.equal(verifiedOrderClosure({ ...good, [field]: value }, pending, 'current-owner'), false));
for (const [field, values] of Object.entries({ id: ['bad', '', 1], evidence_sha256: ['A'.repeat(64), 'a'.repeat(63), null],
  scope: ['attempt', null], finality: ['unknown', null], outcome: ['canceled', null],
  closed_at: ['2026-10-14', 'not-date', '2026-02-30T00:00:00Z', '2026-13-01T00:00:00Z', '2026-10-14T24:00:00Z'] }))
  for (const value of values) test(`closure rejects ${field}=${value}`, () => assert.equal(verifiedOrderClosure({ ...good, closure: { ...good.closure, [field]: value } }, pending, 'current-owner'), false));
