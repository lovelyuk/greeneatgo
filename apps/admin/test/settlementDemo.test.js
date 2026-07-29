import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEMO_STAGES, demoInteractionsLocked, demoLoadStatus, invoiceApprovalLabel, nextDemoAction, optionReason, pastMonths,
  demoUsageReconciliation, demoUsageTotals, readinessState, stageIndex, stageState, statusLabel,
} from '../src/settlementDemo.js';

test('distinguishes load failure from a successfully loaded empty company list', () => {
  assert.equal(demoLoadStatus(null, true, ''), 'loading');
  assert.equal(demoLoadStatus(null, false, 'network failed'), 'failed');
  assert.equal(demoLoadStatus({ options: [] }, false, ''), 'loaded');
  assert.equal(demoLoadStatus({ options: [] }, false, 'refresh failed', true), 'stale');
});

test('locks every interaction after initial, manual, or post-mutation reload failure', () => {
  assert.equal(demoInteractionsLocked(null, { reloadRequired: true }), true, 'initial failure');
  assert.equal(demoInteractionsLocked({ stage: 'draft' }, { reloadRequired: true }), true, 'manual refresh failure with prior state');
  assert.equal(demoInteractionsLocked({ stage: 'confirmed' }, { reloadRequired: true }), true, 'post-mutation reload failure');
  assert.equal(demoInteractionsLocked({ stage: 'draft' }, { loading: true }), true, 'GET in progress');
  assert.equal(demoInteractionsLocked({ stage: 'draft' }, { pending: true }), true, 'action in progress');
  assert.equal(demoInteractionsLocked({ stage: 'draft' }), false, 'successful GET has cleared the reload lock');
});

test('defines the exact five-stage demo timeline and stage progression', () => {
  assert.deepEqual(DEMO_STAGES.map(({ key, label }) => [key, label]), [
    ['seeded', '거래 생성'], ['draft', '정산 생성'], ['confirmed', '정산 확정'],
    ['issued', '세금계산서 발행'], ['paid', '입금 완료'],
  ]);
  assert.equal(stageIndex('empty'), -1);
  assert.equal(stageState('confirmed', 'seeded'), 'complete');
  assert.equal(stageState('confirmed', 'confirmed'), 'current');
  assert.equal(stageState('confirmed', 'issued'), 'upcoming');
  assert.equal(stageState('unknown', 'seeded'), 'upcoming');
});

test('enables only the action matching the exact current stage', () => {
  const ready = { configured: true, is_test: true, certificate_verified: true, supplier_ready: true, corp_matches: true };
  assert.deepEqual(nextDemoAction('seeded', ready), { endpoint: 'create', label: '다음 단계: 정산 생성', enabled: true });
  assert.equal(nextDemoAction('draft', ready).endpoint, 'confirm');
  assert.deepEqual(nextDemoAction('confirmed', ready), { endpoint: 'issue', label: '세금계산서 발행', enabled: true });
  assert.equal(nextDemoAction('issued', ready).endpoint, 'mark-paid');
  assert.equal(nextDemoAction('empty', ready), null);
  assert.equal(nextDemoAction('paid', ready), null);
});

test('readiness requires all five gates and production disables every next action', () => {
  const ready = { configured: true, is_test: true, certificate_verified: true, supplier_ready: true, corp_matches: true };
  assert.deepEqual(readinessState(ready), {
    configured: true, is_test: true, certificate: true, supplier_ready: true, corp_matches: true,
    ready: true, production: false,
  });
  assert.equal(nextDemoAction('confirmed', { ...ready, certificate_verified: false }).enabled, false);
  assert.equal(nextDemoAction('seeded', { ...ready, is_test: false }).enabled, false);
  assert.equal(readinessState({ ...ready, is_test: false }).production, true);
  // Non-provider steps may proceed in an explicitly test environment while another issuance gate is pending.
  assert.equal(nextDemoAction('draft', { ...ready, certificate_verified: false }).enabled, true);
});

test('past month options exclude the current month and cross year boundaries', () => {
  assert.deepEqual(pastMonths(4, new Date(2026, 0, 15)), ['2025-12', '2025-11', '2025-10', '2025-09']);
  assert.deepEqual(pastMonths(2, new Date(2026, 6, 28)), ['2026-06', '2026-05']);
});

test('status labels cover legacy, workflow, tax and payment states without inventing values', () => {
  assert.equal(statusLabel('legacy', 'draft'), '작성 중');
  assert.equal(statusLabel('legacy', 'confirmed'), '확정');
  assert.equal(statusLabel('legacy', 'paid'), '입금 완료');
  assert.equal(statusLabel('workflow', 'confirmed'), '확정');
  assert.equal(statusLabel('tax', 'issued'), '발행 완료');
  assert.equal(statusLabel('payment', 'unpaid'), '입금 대기');
  assert.equal(statusLabel('tax', null), '대기');
  assert.equal(statusLabel('tax', 'provider_new_state'), 'provider_new_state');
});

test('company reasons and NTS approval text remain explicit and truthful', () => {
  assert.equal(optionReason({ eligible: false, reason: 'NO_ACTIVE_COMPANY_ADMIN' }), '활성 회사 관리자 없음');
  assert.equal(optionReason({ eligible: false, reason: 'BUSINESS_PROFILE_INCOMPLETE' }), '세금계산서 사업자정보 미완성');
  assert.equal(optionReason({ eligible: true }), '준비 완료');
  assert.equal(invoiceApprovalLabel({ nts_confirm_num: 'REAL-NTS-123' }, 'issued'), 'REAL-NTS-123');
  assert.equal(invoiceApprovalLabel({}, 'issued'), '발행 완료 / 국세청 승인번호 없음');
  assert.equal(invoiceApprovalLabel({}, 'confirmed'), '대기');
});

test('totals sanitized demo details and reconciles aggregate and settlement exactly', () => {
  const transactions = [
    { supply_amount: 10000, vat_amount: 1000, total_amount: 11000 },
    { supply_amount: '54545', vat_amount: '5455', total_amount: '60000' },
  ];
  assert.deepEqual(demoUsageTotals(transactions), {
    supplyAmount: 64545, vatAmount: 6455, totalAmount: 71000,
  });
  assert.deepEqual(demoUsageReconciliation({
    transactions,
    aggregate: { transaction_count: 2, supply_amount: 64545, vat_amount: 6455, total_amount: 71000 },
    settlement: { tx_count: 2, supply_amount: '64545', vat_amount: '6455', total_amount: '71000' },
  }), {
    supplyAmount: 64545, vatAmount: 6455, totalAmount: 71000,
    detailCount: 2, aggregateCount: 2, aggregateSupply: 64545, aggregateVat: 6455, aggregateTotal: 71000,
    settlementCount: 2, settlementSupply: 64545, settlementVat: 6455, settlementTotal: 71000,
    hasSettlement: true, detailsMatchAggregate: true, settlementMatches: true, reconciled: true,
  });
  assert.equal(demoUsageReconciliation({
    transactions,
    aggregate: { transaction_count: 2, supply_amount: 64544, vat_amount: 6456, total_amount: 71000 },
    settlement: { tx_count: 2, supply_amount: 64545, vat_amount: 6455, total_amount: 71000 },
  }).reconciled, false);
  assert.equal(demoUsageReconciliation({
    transactions,
    aggregate: { transaction_count: 3, supply_amount: 64545, vat_amount: 6455, total_amount: 71000 },
  }).reconciled, false);
  const mixed = demoUsageReconciliation({
    transactions,
    aggregate: { transaction_count: 2, supply_amount: 64545, vat_amount: 6455, total_amount: 71000 },
    settlement: { tx_count: 3, supply_amount: 74545, vat_amount: 7455, total_amount: 82000 },
  });
  assert.equal(mixed.detailsMatchAggregate, true);
  assert.equal(mixed.settlementMatches, false);
  assert.equal(mixed.reconciled, true);
});
