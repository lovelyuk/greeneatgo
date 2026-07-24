import assert from 'node:assert/strict';
import test from 'node:test';

import { contractFormFromItem, subsidyContractInvalid } from '../src/contractForm.js';

test('persisted nested subsidy contract initializes the form', () => {
  assert.deepEqual(contractFormFromItem({
    contract: {
      settlement_cycle: 'month_end',
      settlement_day: null,
      unit_price: 8000,
      subsidy_enabled: true,
      company_subsidy_amount: 2000,
      restaurant_subsidy_amount: 1000,
    },
  }), {
    settlement_cycle: 'month_end',
    settlement_day: '25',
    unit_price: '8000',
    subsidy_enabled: true,
    company_subsidy_amount: '2000',
    restaurant_subsidy_amount: '1000',
  });
});

test('subsidy total equal to unit price is invalid', () => {
  assert.equal(subsidyContractInvalid({
    subsidy_enabled: true,
    unit_price: '8000',
    company_subsidy_amount: '7000',
    restaurant_subsidy_amount: '1000',
  }), true);
});

test('persisted 8000 / 2000 / 1000 contract is valid', () => {
  assert.equal(subsidyContractInvalid({
    subsidy_enabled: true,
    unit_price: '8000',
    company_subsidy_amount: '2000',
    restaurant_subsidy_amount: '1000',
  }), false);
});
