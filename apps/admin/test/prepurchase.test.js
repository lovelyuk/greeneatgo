import assert from 'node:assert/strict';
import test from 'node:test';

import {
  PREPURCHASE_MAX_QUANTITY,
  PREPURCHASE_MAX_UNIT_PRICE,
  prepurchaseChargeInvalid,
  prepurchaseChargePayload,
  prepurchaseChargeTotal,
  prepurchaseItems,
} from '../src/prepurchase.js';

function inventoryItem(overrides = {}) {
  return {
    merchant_company_id: 'merchant-company-1',
    company_id: 'company-1',
    company_name: '그린 회사',
    prepurchase_enabled: true,
    latest_purchase_at: null,
    purchase_quantity: null,
    unit_price: null,
    remaining_quantity: 0,
    ...overrides,
  };
}

test('prepurchase list strictly validates the response and keeps only enabled contracts', () => {
  const enabled = inventoryItem();
  const disabled = inventoryItem({ merchant_company_id: 'merchant-company-2', company_id: 'company-2', prepurchase_enabled: false });
  assert.deepEqual(prepurchaseItems({ items: [enabled, disabled] }), [enabled]);
  assert.throws(() => prepurchaseItems(null), /items 배열/);
  assert.throws(() => prepurchaseItems({}), /items 배열/);
  assert.throws(() => prepurchaseItems({ items: [inventoryItem({ company_name: '' })] }), /company_name/);
  assert.throws(() => prepurchaseItems({ items: [inventoryItem({ prepurchase_enabled: 'true' })] }), /prepurchase_enabled/);
  assert.throws(() => prepurchaseItems({ items: [inventoryItem({ unit_price: '8000' })] }), /unit_price/);
  assert.throws(() => prepurchaseItems({ items: [inventoryItem({ remaining_quantity: -1 })] }), /remaining_quantity/);
  assert.throws(() => prepurchaseItems({ items: [inventoryItem({ latest_purchase_at: 'not-a-date' })] }), /latest_purchase_at/);
});

test('charge amount and API payload use numeric quantity and unit price', () => {
  assert.equal(prepurchaseChargeTotal('12', '8500'), 102000);
  assert.deepEqual(prepurchaseChargePayload('12', '8500', 'request-uuid'), {
    quantity: 12,
    unit_price: 8500,
    idempotency_key: 'request-uuid',
  });
});

test('charge validation requires positive bounded integer values', () => {
  assert.equal(prepurchaseChargeInvalid('1', '8000'), false);
  assert.equal(prepurchaseChargeInvalid(String(PREPURCHASE_MAX_QUANTITY), String(PREPURCHASE_MAX_UNIT_PRICE)), false);
  assert.equal(prepurchaseChargeInvalid('1.5', '8000'), true);
  assert.equal(prepurchaseChargeInvalid('0', '8000'), true);
  assert.equal(prepurchaseChargeInvalid('1', ''), true);
  assert.equal(prepurchaseChargeInvalid(String(PREPURCHASE_MAX_QUANTITY + 1), '8000'), true);
  assert.equal(prepurchaseChargeInvalid('1', String(PREPURCHASE_MAX_UNIT_PRICE + 1)), true);
});
