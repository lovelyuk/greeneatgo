import test from 'node:test';
import assert from 'node:assert/strict';
import {
  SETTLEMENT_MOCK_STORE_KEY,
  canConfirmAndRequest,
  canMerchantIssue,
  canMerchantMarkPaid,
  isBusinessPartyComplete,
  isValidSettlementMockRows,
  loadSettlementMockRows,
  saveSettlementMockRows,
  transitionSettlementMockRow,
} from '../src/settlementMock.js';

const party = {
  name: '가온테크',
  biz_reg_no: '123-45-67890',
  branch_no: null,
  representative_name: '김가온',
  address: '서울시 강남구 테헤란로 1',
  business_type: '서비스업',
  business_item: '소프트웨어',
  tax_invoice_email: 'tax@example.com',
  contact_name: '김담당',
  contact_phone: '02-1234-5678',
};

function row(overrides = {}) {
  return {
    id: 'stl-1',
    company_id: 'company-gaon',
    merchant_id: 'merchant-greeneat',
    period_start: '2026-07-01',
    period_end: '2026-07-31',
    total_amount: 1100,
    supply_amount: 1000,
    vat_amount: 100,
    settlement_status: 'pending',
    tax_invoice_status: 'not_requested',
    payment_status: 'unpaid',
    due_date: '2026-08-14',
    created_at: '2026-07-31T09:00:00+09:00',
    updated_at: '2026-07-31T09:00:00+09:00',
    confirmed_at: null,
    tax_invoice_requested_at: null,
    supplier: { ...party, name: 'GreenEat' },
    recipient: { ...party },
    invoice: null,
    payment: {
      bank_name: null,
      account_number: null,
      account_holder: null,
      scheduled_at: '2026-08-14',
      paid_at: null,
      amount: 0,
      memo: null,
    },
    ...overrides,
  };
}

const requestedRow = () => row({
  settlement_status: 'confirmed',
  tax_invoice_status: 'requested',
  confirmed_at: '2026-08-01T01:00:00Z',
  tax_invoice_requested_at: '2026-08-01T01:00:00Z',
  invoice: {
    id: 'mock-invoice-stl-1',
    provider: 'local_mock',
    approval_number: null,
    external_url: null,
    pdf_url: null,
    written_at: '2026-07-31',
    issued_at: null,
    nts_sent_at: null,
    nts_accepted_at: null,
    failed_reason: null,
  },
});

test('validates a complete nonempty settlement array', () => {
  assert.equal(isValidSettlementMockRows([row()]), true);
  assert.equal(isValidSettlementMockRows([]), false);
  assert.equal(isValidSettlementMockRows(null), false);
});

test('rejects malformed required values, enums, amounts, dates, and nested shapes', () => {
  assert.equal(isValidSettlementMockRows([row({ id: '' })]), false);
  assert.equal(isValidSettlementMockRows([row({ period_end: '2026-02-31' })]), false);
  assert.equal(isValidSettlementMockRows([row({ total_amount: '1100' })]), false);
  assert.equal(isValidSettlementMockRows([row({ total_amount: 999 })]), false);
  assert.equal(isValidSettlementMockRows([row({ settlement_status: 'sent' })]), false);
  assert.equal(isValidSettlementMockRows([row({ recipient: { name: 'incomplete' } })]), false);
  assert.equal(isValidSettlementMockRows([row({ payment: null })]), false);
  assert.equal(isValidSettlementMockRows([row({ tax_invoice_status: 'requested', invoice: null })]), false);
  assert.equal(isValidSettlementMockRows([row({ tax_invoice_status: 'not_requested', invoice: requestedRow().invoice })]), false);
  assert.equal(isValidSettlementMockRows([row({ payment_status: 'paid' })]), false);
});

test('requires real calendar dates and full ISO date-time timestamps', () => {
  assert.equal(isValidSettlementMockRows([row({ period_end: '2026-02-31' })]), false);
  assert.equal(isValidSettlementMockRows([row({ created_at: '2026-07-31' })]), false);
  assert.equal(isValidSettlementMockRows([row({ updated_at: '2026-07-31 09:00:00' })]), false);
  assert.equal(isValidSettlementMockRows([row({ updated_at: '2026-07-31T09:00:00' })]), false);
});

test('rejects settlement and invoice status/timestamp contradictions', () => {
  const requested = requestedRow();
  assert.equal(isValidSettlementMockRows([row({ confirmed_at: requested.confirmed_at })]), false);
  assert.equal(isValidSettlementMockRows([{ ...requested, confirmed_at: null }]), false);
  assert.equal(isValidSettlementMockRows([row({ tax_invoice_requested_at: requested.tax_invoice_requested_at })]), false);
  assert.equal(isValidSettlementMockRows([{ ...requested, tax_invoice_requested_at: null }]), false);
  assert.equal(isValidSettlementMockRows([{ ...requested, tax_invoice_status: 'issued' }]), false);
  assert.equal(isValidSettlementMockRows([{ ...requested, tax_invoice_status: 'nts_accepted', invoice: { ...requested.invoice, issued_at: '2026-08-02T03:00:00Z' } }]), false);
});

test('rejects paid amount/timestamp mismatches and paid cancelled settlements', () => {
  const source = requestedRow();
  const issued = { ...source, tax_invoice_status: 'issued', invoice: { ...source.invoice, issued_at: '2026-08-02T03:00:00Z' } };
  const paid = transitionSettlementMockRow(issued, 'merchant_mark_paid', '2026-08-14T01:30:00Z');
  assert.equal(isValidSettlementMockRows([paid]), true);
  assert.equal(isValidSettlementMockRows([{ ...paid, payment: { ...paid.payment, amount: paid.total_amount - 1 } }]), false);
  assert.equal(isValidSettlementMockRows([{ ...paid, payment: { ...paid.payment, paid_at: null } }]), false);
  assert.equal(isValidSettlementMockRows([{ ...paid, settlement_status: 'cancelled' }]), false);
  assert.equal(isValidSettlementMockRows([row({ payment: { ...row().payment, amount: null } })]), false);
});

test('requires zero amount and null paid_at for every non-paid status', () => {
  for (const payment_status of ['scheduled', 'overdue']) {
    assert.equal(isValidSettlementMockRows([row({ payment_status })]), true);
    assert.equal(isValidSettlementMockRows([row({ payment_status, payment: { ...row().payment, amount: 1 } })]), false);
    assert.equal(isValidSettlementMockRows([row({ payment_status, payment: { ...row().payment, paid_at: '2026-08-14T01:30:00Z' } })]), false);
  }
});

test('enforces settlement, tax invoice, and payment cross-state invariants', () => {
  const requested = requestedRow();
  const issued = { ...requested, tax_invoice_status: 'issued', invoice: { ...requested.invoice, issued_at: '2026-08-02T03:00:00Z' } };
  const paid = transitionSettlementMockRow(issued, 'merchant_mark_paid', '2026-08-14T01:30:00Z');
  assert.equal(isValidSettlementMockRows([{ ...issued, settlement_status: 'pending', confirmed_at: null }]), false);
  assert.equal(canMerchantMarkPaid({ ...issued, settlement_status: 'pending' }), false);
  assert.equal(transitionSettlementMockRow({ ...issued, settlement_status: 'pending' }, 'merchant_mark_paid', '2026-08-14T01:30:00Z'), null);
  assert.equal(isValidSettlementMockRows([{ ...paid, tax_invoice_status: 'requested', invoice: requested.invoice }]), false);
});

test('business recipient completeness requires work-order fields and blocks without mutation', () => {
  assert.equal(isBusinessPartyComplete(party), true);
  const incomplete = { ...party, contact_phone: '' };
  assert.equal(isBusinessPartyComplete(incomplete), false);
  const source = row();
  const snapshot = structuredClone(source);
  assert.equal(transitionSettlementMockRow(source, 'confirm_and_request', '2026-08-01T02:00:00Z', incomplete), null);
  assert.deepEqual(source, snapshot);
});

test('loads valid storage and falls back safely for invalid data or get exceptions', () => {
  const stored = [requestedRow()];
  const storage = { getItem: (key) => key === SETTLEMENT_MOCK_STORE_KEY ? JSON.stringify(stored) : null };
  assert.deepEqual(loadSettlementMockRows(storage, [row()]), stored);
  assert.deepEqual(loadSettlementMockRows({ getItem: () => '[]' }, [row()]), [row()]);
  assert.deepEqual(loadSettlementMockRows({ getItem: () => { throw new Error('denied'); } }, [row()]), [row()]);
});

test('save catches storage errors and refuses invalid rows', () => {
  let saved = '';
  assert.equal(saveSettlementMockRows({ setItem: (_key, value) => { saved = value; } }, [row()]), true);
  assert.deepEqual(JSON.parse(saved), [row()]);
  assert.equal(saveSettlementMockRows({ setItem: () => { throw new Error('quota'); } }, [row()]), false);
  assert.equal(saveSettlementMockRows({ setItem: () => assert.fail('must not write') }, []), false);
});

test('company confirm and request snapshots the checked recipient only for pending/not_requested', () => {
  const source = row();
  const latestRecipient = { ...party, name: '가온테크 최신 상호', address: '서울시 새 주소', tax_invoice_email: 'latest@example.com' };
  assert.equal(canConfirmAndRequest(source), true);
  assert.equal(canConfirmAndRequest(requestedRow()), false);
  const changed = transitionSettlementMockRow(source, 'confirm_and_request', '2026-08-01T02:00:00Z', latestRecipient);
  assert.equal(changed.settlement_status, 'confirmed');
  assert.equal(changed.tax_invoice_status, 'requested');
  assert.equal(changed.invoice.written_at, source.period_end);
  assert.equal(changed.invoice.approval_number, null);
  assert.deepEqual(changed.recipient, latestRecipient);
  assert.notEqual(changed.recipient, latestRecipient);
  latestRecipient.name = '호출 후 변경';
  assert.equal(changed.recipient.name, '가온테크 최신 상호');
  assert.equal(transitionSettlementMockRow(source, 'confirm_and_request', '2026-08-01T02:00:00Z'), null);
  assert.equal(transitionSettlementMockRow(source, 'confirm_and_request', '2026-08-01T02:00:00Z', { name: '불완전' }), null);
  assert.equal(transitionSettlementMockRow(requestedRow(), 'confirm_and_request', '2026-08-01T02:00:00Z', party), null);
});

test('merchant issue requires confirmed plus requested or failed', () => {
  const source = requestedRow();
  assert.equal(canMerchantIssue(source), true);
  const issued = transitionSettlementMockRow(source, 'merchant_issue', '2026-08-02T03:00:00Z');
  assert.equal(issued.tax_invoice_status, 'issued');
  assert.equal(issued.invoice.written_at, source.period_end);
  assert.equal(issued.invoice.issued_at, '2026-08-02T03:00:00Z');
  assert.equal(issued.invoice.approval_number, null);
  assert.equal(canMerchantIssue({ ...source, settlement_status: 'cancelled' }), false);
  assert.equal(canMerchantIssue({ ...source, tax_invoice_status: 'issuing' }), false);
});

test('merchant mark-paid excludes cancelled, already-paid, and ineligible tax statuses', () => {
  const issued = { ...requestedRow(), tax_invoice_status: 'issued' };
  assert.equal(canMerchantMarkPaid(issued), true);
  const paid = transitionSettlementMockRow(issued, 'merchant_mark_paid', '2026-08-14T01:30:00Z');
  assert.equal(paid.payment_status, 'paid');
  assert.equal(paid.payment.amount, issued.total_amount);
  assert.equal(canMerchantMarkPaid({ ...issued, settlement_status: 'cancelled' }), false);
  assert.equal(canMerchantMarkPaid({ ...issued, payment_status: 'paid' }), false);
  assert.equal(canMerchantMarkPaid(requestedRow()), false);
  assert.equal(transitionSettlementMockRow({ ...issued, settlement_status: 'cancelled' }, 'merchant_mark_paid', '2026-08-14T01:30:00Z'), null);
});
