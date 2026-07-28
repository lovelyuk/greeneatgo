import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildPaymentPayload, canConfirmAndRequest, canMerchantIssue, canMerchantMarkPaid,
  canRefreshInvoiceStatus, fetchAllSettlementSummaries, isBusinessPartyComplete,
  loadSettlementDetails, mapSettlement, openDocumentInNewWindow, paymentFormForSettlement,
  PAYMENT_STATUS_LABELS, requireHttpsUrl,
} from '../src/settlementApi.js';

const detail = {
  id: 's-1', company_id: 'c-secret', merchant_id: 'm-secret', period_ym: '2026-07',
  period_from: '2026-07-01', period_to: '2026-07-31', total_amount: 11000,
  supply_amount: 10000, vat_amount: 1000, settlement_status: 'confirmed',
  tax_invoice_status: 'issued', payment_status: 'partially_paid', due_date: '2026-08-10',
  business_information: { name: '현재 회사명', biz_reg_no: '000' },
  supplier_information: { name: '현재 공급자', biz_reg_no: '999', representative_name: '현재 대표', owner_phone: 'private' },
  tax_invoices: [{ id: 'provider-internal-id', document_type: 'original', write_date: '2026-07-31',
    supplier_snapshot: { name: '이전 공급자', registration_number: '123', representative: '이전 대표' },
    recipient_snapshot: { name: '발행 당시 회사', registration_number: '456', tax_email: 'tax@example.test' },
    nts_confirm_num: 'approval-from-server', issued_at: '2026-08-01T00:00:00Z' }],
  payments: [
    { id: 'payment-secret-1', amount: 4000, depositor_name: '첫 입금자', deposited_at: '2026-08-09T01:00:00Z', memo: '1차' },
    { id: 'payment-secret-2', amount: 3000, depositor_name: '두 번째 입금자', deposited_at: '2026-08-10T01:00:00Z', memo: '2차' },
  ],
  transactions: [
    { id: 'tx-1', created_at: '2026-07-02T03:00:00Z', employee_name: '김직원', employee_no: 'A-1', department: '개발팀', kind: 'spend', pay_type: 'ledger', item: '중식', tx_code: 'TX-1', supply_amount: 10000, vat_amount: 1000, total_amount: 11000, is_demo: true },
  ],
  events: [{ event_type: 'paid', provider_key: 'secret' }],
};

test('maps public supplier information first and preserves every payment without internal identifiers', () => {
  const row = mapSettlement(detail);
  assert.equal(row.period_start, '2026-07-01');
  assert.equal(row.supplier.name, '현재 공급자');
  assert.equal(row.supplier.biz_reg_no, '999');
  assert.equal(row.recipient.name, '발행 당시 회사');
  assert.equal(row.invoice.approval_number, 'approval-from-server');
  assert.deepEqual(row.payments, [
    { amount: 4000, depositor_name: '첫 입금자', deposited_at: '2026-08-09T01:00:00Z', memo: '1차' },
    { amount: 3000, depositor_name: '두 번째 입금자', deposited_at: '2026-08-10T01:00:00Z', memo: '2차' },
  ]);
  assert.equal(row.payment.account_holder, '두 번째 입금자');
  assert.equal(row.payment.amount, 7000);
  assert.equal(row.payment.paid_at, '2026-08-10T01:00:00Z');
  assert.deepEqual(row.transactions, [{
    id: 'tx-1', created_at: '2026-07-02T03:00:00Z', employee_name: '김직원', employee_no: 'A-1',
    department: '개발팀', kind: 'spend', pay_type: 'ledger', item: '중식', tx_code: 'TX-1',
    supply_amount: 10000, vat_amount: 1000, total_amount: 11000, is_demo: true,
  }]);
  assert.equal('company_id' in row, false);
  assert.equal('merchant_id' in row, false);
  assert.equal('id' in row.invoice, false);
  assert.equal('events' in row, false);
});

test('does not invent invoice or payment metadata for list rows', () => {
  const row = mapSettlement({ id: 's-2', period_ym: '2026-06', total_amount: 10 });
  assert.equal(row.invoice, null);
  assert.equal(row.supplier.name, '');
  assert.equal(row.payment.amount, 0);
  assert.deepEqual(row.payments, []);
  assert.deepEqual(row.transactions, []);
});

test('action eligibility exactly follows live backend lifecycle', () => {
  assert.equal(canConfirmAndRequest({ settlement_status: 'sent', tax_invoice_status: 'not_requested' }), true);
  assert.equal(canConfirmAndRequest({ settlement_status: 'pending', tax_invoice_status: 'not_requested' }), false);
  for (const [settlement_status, tax_invoice_status] of [
    ['sent', 'not_requested'], ['sent', 'failed'], ['confirmed', 'requested'], ['confirmed', 'failed'],
  ]) assert.equal(canMerchantIssue({ settlement_status, tax_invoice_status }), true);
  assert.equal(canMerchantIssue({ settlement_status: 'finalized', tax_invoice_status: 'failed' }), false);
  assert.equal(canMerchantIssue({ settlement_status: 'confirmed', tax_invoice_status: 'issued' }), false);
  assert.equal(canMerchantMarkPaid({ settlement_status: 'confirmed', tax_invoice_status: 'nts_accepted', payment_status: 'unpaid' }), true);
  assert.equal(canMerchantMarkPaid({ settlement_status: 'disputed', tax_invoice_status: 'issued', payment_status: 'unpaid' }), false);
  assert.equal(canMerchantMarkPaid({ settlement_status: 'cancelled', tax_invoice_status: 'issued', payment_status: 'unpaid' }), false);
  // The backend permits payment records for every other settlement lifecycle state,
  // including adding a correcting/overpayment record after the total was reached.
  assert.equal(canMerchantMarkPaid({ settlement_status: 'pending', tax_invoice_status: 'issued', payment_status: 'paid' }), true);
  assert.equal(canRefreshInvoiceStatus({ tax_invoice_status: 'issuing' }), true);
  assert.equal(canRefreshInvoiceStatus({ tax_invoice_status: 'requested' }), false);
});

test('payment labels cover the live backend enum and optional unpaid compatibility value', () => {
  assert.deepEqual(Object.keys(PAYMENT_STATUS_LABELS).sort(),
    ['matching', 'overpaid', 'paid', 'partially_paid', 'unmatched', 'unpaid']);
  for (const value of ['matching', 'partially_paid', 'paid', 'overpaid', 'unmatched', 'unpaid']) {
    assert.match(PAYMENT_STATUS_LABELS[value], /[가-힣]/);
  }
});

test('business party completeness is a production-safe validation helper', () => {
  const complete = Object.fromEntries(['biz_reg_no', 'name', 'representative_name', 'address', 'business_type', 'business_item', 'tax_invoice_email', 'contact_name', 'contact_phone'].map((key) => [key, key]));
  assert.equal(isBusinessPartyComplete(complete), true);
  assert.equal(isBusinessPartyComplete({ ...complete, address: ' ' }), false);
});

test('loads every list page and rejects duplicate ids or a reached hard cap', async () => {
  const calls = [];
  const rows = await fetchAllSettlementSummaries(async ({ limit, offset }) => {
    calls.push([limit, offset]);
    return { items: Array.from({ length: offset === 0 ? 100 : 3 }, (_, index) => ({ id: `s-${offset + index}` })) };
  });
  assert.equal(rows.length, 103);
  assert.deepEqual(calls, [[100, 0], [100, 100]]);
  await assert.rejects(() => fetchAllSettlementSummaries(async ({ offset }) => ({ items: offset ? [{ id: 'same' }] : Array.from({ length: 100 }, (_, i) => ({ id: i ? `s-${i}` : 'same' })) })), /duplicate/i);
  await assert.rejects(() => fetchAllSettlementSummaries(async ({ offset }) => ({ items: Array.from({ length: 100 }, (_, i) => ({ id: `${offset}-${i}` })) }), { maxPages: 2 }), /limit/i);
});

test('loads details in bounded batches and preserves successes with failure metadata', async () => {
  let active = 0; let maxActive = 0;
  const summaries = Array.from({ length: 23 }, (_, index) => ({ id: `s-${index}` }));
  const result = await loadSettlementDetails(summaries, async (item) => {
    active += 1; maxActive = Math.max(maxActive, active);
    await new Promise((resolve) => setTimeout(resolve, 1));
    active -= 1;
    if (item.id === 's-7') throw new Error('404');
    return { ...item, total_amount: 1 };
  }, { batchSize: 10 });
  assert.equal(maxActive, 10);
  assert.equal(result.rows.length, 22);
  assert.deepEqual(result.failures.map((failure) => failure.id), ['s-7']);
});

test('document popup is opened synchronously, navigated only to HTTPS, and closed on failure', async () => {
  let resolved = false;
  const handle = { opener: {}, closed: false, location: { replace(url) { this.url = url; } }, close() { this.closed = true; } };
  const open = () => { assert.equal(resolved, false); return handle; };
  await openDocumentInNewWindow(open, async () => { resolved = true; return 'https://example.test/doc'; });
  assert.equal(handle.opener, null);
  assert.equal(handle.location.url, 'https://example.test/doc');
  const failed = { opener: {}, closed: false, location: {}, close() { this.closed = true; } };
  await assert.rejects(() => openDocumentInNewWindow(() => failed, async () => 'http://bad.test'), /안전하지 않은/);
  assert.equal(failed.closed, true);
  await assert.rejects(() => openDocumentInNewWindow(() => null, async () => { throw new Error('must not load'); }), /팝업/);
});

test('document URLs must be valid HTTPS URLs', () => {
  assert.equal(requireHttpsUrl('https://example.test/doc'), 'https://example.test/doc');
  assert.throws(() => requireHttpsUrl('http://example.test/doc'), /안전하지 않은/);
  assert.throws(() => requireHttpsUrl('javascript:alert(1)'), /안전하지 않은/);
  assert.throws(() => requireHttpsUrl('not a url'), /올바르지/);
});

test('payment form defaults to remaining amount and payload exactly matches backend schema', () => {
  const form = paymentFormForSettlement(mapSettlement(detail), new Date('2026-08-11T03:04:00Z'));
  assert.equal(form.amount, '4000');
  assert.equal(form.depositor_name, '발행 당시 회사');
  assert.match(form.deposited_at, /^2026-08-11T\d{2}:04$/);
  const payload = buildPaymentPayload({ ...form, depositor_name: ' 입금자 ', memo: ' 메모 ' }, 'key-1');
  assert.deepEqual(payload, {
    amount: 4000, depositor_name: '입금자', deposited_at: new Date(form.deposited_at).toISOString(), memo: '메모', idempotency_key: 'key-1',
  });
  assert.throws(() => buildPaymentPayload({ ...form, amount: '1.5' }, 'key'), /입금액/);
  assert.throws(() => buildPaymentPayload({ ...form, depositor_name: ' ' }, 'key'), /입금자/);
});
