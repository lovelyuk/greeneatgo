import test from 'node:test';
import assert from 'node:assert/strict';
import { bizNoWithBranch, mapBusinessParty } from '../src/settlementApi.js';

test('a branch office shows its number next to the business number', () => {
  assert.equal(bizNoWithBranch({ biz_reg_no: '114-81-93597', sub_biz_no: '0001' }), '114-81-93597 (종사업장 0001)');
  assert.equal(bizNoWithBranch({ biz_reg_no: '114-81-93597', sub_biz_no: null }), '114-81-93597');
  assert.equal(bizNoWithBranch({ biz_reg_no: '114-81-93597' }), '114-81-93597');
  assert.equal(bizNoWithBranch({ biz_reg_no: '', sub_biz_no: '0001' }), '-');
  assert.equal(bizNoWithBranch(null), '-');
});

test('the settlement recipient carries the branch number from the company or the invoice copy', () => {
  assert.equal(mapBusinessParty({ name: 'x', sub_biz_no: '0006' }).branch_no, '0006');
  assert.equal(mapBusinessParty({ name: 'x', tax_reg_id: '0003' }).branch_no, '0003');
  assert.equal(mapBusinessParty({ name: 'x' }).branch_no, null);
});
