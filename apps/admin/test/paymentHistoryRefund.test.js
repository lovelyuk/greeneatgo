import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { paymentMethodLabel, refundButtonState } from '../src/paymentHistoryDisplay.js';

const payment = { status: 'done', order_id: 'order-1', user_id: 'user-1' };

test('maps provider methods to 카드, 현금 and 포인트', () => {
  assert.equal(paymentMethodLabel({ payment_method: 'CARD', amount: 10000 }), '카드');
  assert.equal(paymentMethodLabel({ payment_method: 'NAVERPAY', amount: 10000 }), '카드');
  assert.equal(paymentMethodLabel({ payment_method: 'BANK', amount: 10000 }), '현금');
  assert.equal(paymentMethodLabel({ payment_method: 'POINT', amount: 0, point_amount: 10000 }), '포인트');
  assert.equal(paymentMethodLabel({ payment_method: '', amount: 0, point_amount: 10000 }), '포인트');
  assert.equal(paymentMethodLabel({ payment_method: 'CARD', amount: 7000, point_amount: 3000 }), '카드');
  assert.equal(paymentMethodLabel({ kind: 'refund', payment_method: 'BANK', amount: -10000, point_amount: 0 }), '현금');
  assert.equal(paymentMethodLabel({ kind: 'refund', payment_method: 'CARD', amount: -10000, point_amount: 3000 }), '카드');
});

test('payment method badges avoid the global card class and keep flexible single-line pills', async () => {
  const feature = await readFile(new URL('../src/PaymentFeatures.jsx', import.meta.url), 'utf8');
  const style = await readFile(new URL('../src/style.css', import.meta.url), 'utf8');
  assert.match(feature, /<span className="payment-type-badge">\{paymentType\}<\/span>/);
  assert.doesNotMatch(feature, /const paymentTone =/);
  assert.match(style, /\.payment-type-badge\s*\{[^}]*white-space:\s*nowrap/s);
  assert.match(style, /\.payment-detail-card \.history-row-payment \.payment-type-badge\s*\{[^}]*width:\s*max-content/s);
  assert.doesNotMatch(style, /\.payment-detail-card \.history-row-payment \.payment-type-badge\s*\{[^}]*width:\s*58px/s);
});

test('enables refunds only for complete payment rows with required ownership keys', () => {
  assert.deepEqual(refundButtonState(payment), { completed: false, disabled: false, label: '환불' });
  assert.deepEqual(refundButtonState({ ...payment, status: 'refunded' }), { completed: true, disabled: true, label: '환불완료' });
  assert.deepEqual(refundButtonState({ ...payment, kind: 'refund' }), { completed: true, disabled: true, label: '환불완료' });
  assert.deepEqual(refundButtonState({ ...payment, order_id: null }), { completed: false, disabled: true, label: '환불' });
});

test('keeps refund entry point out of the dashboard and next to each receipt', async () => {
  const main = await readFile(new URL('../src/main.jsx', import.meta.url), 'utf8');
  const feature = await readFile(new URL('../src/PaymentFeatures.jsx', import.meta.url), 'utf8');
  assert.equal(main.includes('merchant-refund-dock'), false);
  assert.equal(main.includes('refundOpen'), false);
  assert.match(feature, /className="receipt-trigger"[\s\S]*className="refund-row-trigger"/);
  assert.match(feature, /<RefundModal[^>]*initialPayment=/);
  assert.equal(feature.includes("step === 'account'"), false);
  assert.equal(feature.includes('refund_account'), false);
  assert.equal(feature.includes('e.status === 422'), false);
});
