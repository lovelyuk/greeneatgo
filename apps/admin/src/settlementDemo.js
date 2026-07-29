export const DEMO_STAGES = Object.freeze([
  { key: 'seeded', label: '거래 생성' },
  { key: 'draft', label: '정산 생성' },
  { key: 'confirmed', label: '정산 확정' },
  { key: 'issued', label: '세금계산서 발행' },
  { key: 'paid', label: '입금 완료' },
]);

export const DEMO_ACTIONS = Object.freeze({
  seeded: { endpoint: 'create', label: '다음 단계: 정산 생성' },
  draft: { endpoint: 'confirm', label: '다음 단계: 정산 확정' },
  confirmed: { endpoint: 'issue', label: '세금계산서 발행' },
  issued: { endpoint: 'mark-paid', label: '다음 단계: 입금 완료 처리' },
});

export const STATUS_LABELS = Object.freeze({
  legacy: { draft: '작성 중', confirmed: '확정', paid: '입금 완료' },
  workflow: { draft: '작성 중', sent: '회사 전송', confirmed: '확정', cancelled: '취소', disputed: '이의 제기' },
  tax: { not_requested: '발행 요청 전', requested: '발행 요청', issuing: '발행 중', issued: '발행 완료', nts_sending: '국세청 전송 중', nts_accepted: '국세청 승인', failed: '발행 실패' },
  payment: { unpaid: '입금 대기', matching: '입금 매칭 중', partially_paid: '부분 입금', paid: '입금 완료', overpaid: '초과 입금', unmatched: '입금 미매칭' },
});

export const OPTION_REASON_LABELS = Object.freeze({
  NO_ACTIVE_EMPLOYEE_OR_CUSTOMER: '활성 임직원/고객 없음',
  NO_ACTIVE_COMPANY_ADMIN: '활성 회사 관리자 없음',
  BUSINESS_PROFILE_INCOMPLETE: '세금계산서 사업자정보 미완성',
});

export function stageIndex(stage) {
  if (stage === 'empty') return -1;
  return DEMO_STAGES.findIndex((item) => item.key === stage);
}

export function stageState(stage, itemKey) {
  const current = stageIndex(stage);
  const item = stageIndex(itemKey);
  if (item < 0 || current < 0) return 'upcoming';
  if (item < current) return 'complete';
  return item === current ? 'current' : 'upcoming';
}

export function readinessState(readiness = {}) {
  const values = {
    configured: readiness.configured === true,
    is_test: readiness.is_test === true,
    certificate: readiness.certificate_verified === true,
    supplier_ready: readiness.supplier_ready === true,
    corp_matches: readiness.corp_matches === true,
  };
  return { ...values, ready: Object.values(values).every(Boolean), production: readiness.is_test === false };
}

export function nextDemoAction(stage, readiness = {}) {
  const action = DEMO_ACTIONS[stage] ?? null;
  if (!action) return null;
  const ready = readinessState(readiness);
  return { ...action, enabled: !ready.production && (stage !== 'confirmed' || ready.ready) };
}

export function pastMonths(count = 12, now = new Date()) {
  const months = [];
  const date = new Date(now.getFullYear(), now.getMonth(), 1);
  for (let index = 1; index <= count; index += 1) {
    const value = new Date(date.getFullYear(), date.getMonth() - index, 1);
    months.push(`${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}`);
  }
  return months;
}

export function statusLabel(group, value) {
  if (!value) return '대기';
  return STATUS_LABELS[group]?.[value] ?? value;
}

export function optionReason(option = {}) {
  if (option.eligible) return '준비 완료';
  return OPTION_REASON_LABELS[option.reason] ?? option.reason ?? '조건 미충족';
}

export function demoLoadStatus(state, loading, error = '', reloadRequired = false) {
  if (state !== null && reloadRequired) return 'stale';
  if (state !== null) return 'loaded';
  if (loading || !error) return 'loading';
  return 'failed';
}

export function demoInteractionsLocked(state, { loading = false, reloadRequired = false, pending = false } = {}) {
  return state === null || loading || reloadRequired || pending;
}

export function invoiceApprovalLabel(settlement, stage) {
  if (settlement?.nts_confirm_num) return settlement.nts_confirm_num;
  if (stageIndex(stage) >= stageIndex('issued')) return '발행 완료 / 국세청 승인번호 없음';
  return '대기';
}

function amount(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function demoUsageTotals(transactions = []) {
  return transactions.reduce((totals, item) => ({
    supplyAmount: totals.supplyAmount + amount(item?.supply_amount),
    vatAmount: totals.vatAmount + amount(item?.vat_amount),
    totalAmount: totals.totalAmount + amount(item?.total_amount),
  }), { supplyAmount: 0, vatAmount: 0, totalAmount: 0 });
}

export function demoUsageReconciliation(state = {}) {
  const transactions = Array.isArray(state.transactions) ? state.transactions : [];
  const details = demoUsageTotals(transactions);
  const detailCount = transactions.length;
  const aggregateCount = amount(state.aggregate?.transaction_count ?? state.transaction_count);
  const aggregateSupply = amount(state.aggregate?.supply_amount);
  const aggregateVat = amount(state.aggregate?.vat_amount);
  const aggregateTotal = amount(state.aggregate?.total_amount);
  const hasSettlement = state.settlement != null;
  const settlementCount = hasSettlement ? amount(state.settlement?.tx_count) : null;
  const settlementSupply = hasSettlement ? amount(state.settlement?.supply_amount) : null;
  const settlementVat = hasSettlement ? amount(state.settlement?.vat_amount) : null;
  const settlementTotal = hasSettlement ? amount(state.settlement?.total_amount) : null;
  const detailsMatchAggregate = detailCount === aggregateCount
    && details.supplyAmount === aggregateSupply
    && details.vatAmount === aggregateVat
    && details.totalAmount === aggregateTotal;
  const settlementMatches = !hasSettlement || (settlementCount === aggregateCount
    && settlementSupply === aggregateSupply
    && settlementVat === aggregateVat
    && settlementTotal === aggregateTotal);
  return {
    ...details, detailCount, aggregateCount, aggregateSupply, aggregateVat, aggregateTotal,
    settlementCount, settlementSupply, settlementVat, settlementTotal, hasSettlement,
    detailsMatchAggregate, settlementMatches,
    // A settlement intentionally aggregates every ordinary source row in the month,
    // including real rows that predated generation. Only private generated details
    // must reconcile exactly with their generated aggregate.
    reconciled: detailsMatchAggregate,
  };
}
