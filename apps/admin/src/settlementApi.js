const DOCUMENT_STATUSES = new Set(['issued', 'nts_sending', 'nts_accepted']);
const REFRESHABLE_STATUSES = new Set(['issuing', ...DOCUMENT_STATUSES]);
export const PAYMENT_STATUS_LABELS = Object.freeze({
  matching: '입금 매칭 중',
  partially_paid: '부분 입금',
  paid: '입금 완료',
  overpaid: '초과 입금',
  unmatched: '입금 미매칭',
  unpaid: '입금 대기',
});
const BUSINESS_PARTY_REQUIRED_FIELDS = [
  'biz_reg_no', 'name', 'representative_name', 'address', 'business_type',
  'business_item', 'tax_invoice_email', 'contact_name', 'contact_phone',
];

function text(value) {
  return typeof value === 'string' ? value : '';
}

export function mapBusinessParty(snapshot = {}) {
  if (!snapshot || typeof snapshot !== 'object' || Array.isArray(snapshot)) snapshot = {};
  return {
    name: text(snapshot.name),
    biz_reg_no: text(snapshot.biz_reg_no || snapshot.registration_number),
    branch_no: snapshot.branch_no ?? snapshot.branch_number ?? null,
    representative_name: text(snapshot.representative_name || snapshot.representative),
    address: text(snapshot.address),
    business_type: text(snapshot.business_type),
    business_item: text(snapshot.business_item),
    tax_invoice_email: text(snapshot.tax_invoice_email || snapshot.tax_email || snapshot.contact_email),
    contact_name: text(snapshot.contact_name),
    contact_phone: text(snapshot.contact_phone),
  };
}

export function isBusinessPartyComplete(value) {
  return Boolean(value) && typeof value === 'object'
    && BUSINESS_PARTY_REQUIRED_FIELDS.every((key) => text(value[key]).trim().length > 0);
}

function originalInvoice(row) {
  const invoices = Array.isArray(row?.tax_invoices) ? row.tax_invoices : [];
  return invoices.find((item) => item?.document_type === 'original') ?? null;
}

function mapPayment(item) {
  return {
    amount: Number(item?.amount) || 0,
    depositor_name: text(item?.depositor_name),
    deposited_at: item?.deposited_at ?? null,
    memo: text(item?.memo) || null,
  };
}

export function mapSettlement(row = {}) {
  const source = row && typeof row === 'object' ? row : {};
  const invoiceSource = originalInvoice(source);
  const recipientSource = invoiceSource?.recipient_snapshot ?? source.business_information ?? {};
  const supplierSource = source.supplier_information ?? invoiceSource?.supplier_snapshot ?? source.supplier ?? {};
  const payments = (Array.isArray(source.payments) ? source.payments : []).map(mapPayment);
  const latestPayment = payments.at(-1) ?? null;
  const paidAmount = payments.reduce((total, payment) => total + payment.amount, 0);
  const periodStart = text(source.period_from) || (text(source.period_ym) ? `${source.period_ym}-01` : '');
  const periodEnd = text(source.period_to) || periodStart;
  const paidAt = latestPayment?.deposited_at ?? source.paid_at ?? null;
  return {
    id: source.id,
    period_start: periodStart,
    period_end: periodEnd,
    total_amount: Number(source.total_amount) || 0,
    supply_amount: Number(source.supply_amount) || 0,
    vat_amount: Number(source.vat_amount) || 0,
    settlement_status: text(source.settlement_status || source.status) || 'pending',
    tax_invoice_status: text(source.tax_invoice_status) || 'not_requested',
    payment_status: text(source.payment_status) || 'unpaid',
    due_date: source.due_date ?? null,
    created_at: source.created_at ?? null,
    updated_at: source.updated_at ?? null,
    confirmed_at: source.confirmed_at ?? null,
    tax_invoice_requested_at: invoiceSource?.requested_at ?? null,
    supplier: mapBusinessParty(supplierSource),
    recipient: mapBusinessParty(recipientSource),
    invoice: invoiceSource ? {
      written_at: invoiceSource.write_date ?? null,
      issued_at: invoiceSource.issued_at ?? null,
      nts_sent_at: invoiceSource.nts_sent_at ?? null,
      nts_accepted_at: invoiceSource.nts_accepted_at ?? null,
      approval_number: invoiceSource.nts_confirm_num ?? null,
      failed_reason: invoiceSource.failure_message ?? null,
    } : null,
    payments,
    payment: {
      bank_name: null,
      account_number: null,
      account_holder: latestPayment?.depositor_name || null,
      scheduled_at: source.due_date ?? null,
      paid_at: paidAt,
      amount: paidAmount || (paidAt && payments.length === 0 ? Number(source.total_amount) || 0 : 0),
      memo: latestPayment?.memo ?? null,
    },
  };
}

export function canConfirmAndRequest(row) {
  return row?.settlement_status === 'sent' && row?.tax_invoice_status === 'not_requested';
}

export function canMerchantIssue(row) {
  const state = `${row?.settlement_status}:${row?.tax_invoice_status}`;
  return new Set(['sent:not_requested', 'sent:failed', 'confirmed:requested', 'confirmed:failed']).has(state);
}

export function canMerchantMarkPaid(row) {
  return !['cancelled', 'disputed'].includes(row?.settlement_status)
    && DOCUMENT_STATUSES.has(row?.tax_invoice_status);
}

export function canRefreshInvoiceStatus(row) {
  return REFRESHABLE_STATUSES.has(row?.tax_invoice_status);
}

export function hasInvoiceDocument(row) {
  return DOCUMENT_STATUSES.has(row?.tax_invoice_status);
}

export function requireHttpsUrl(value) {
  let url;
  try { url = new URL(value); } catch { throw new Error('문서 주소가 올바르지 않습니다.'); }
  if (url.protocol !== 'https:') throw new Error('안전하지 않은 문서 주소는 열 수 없습니다.');
  return url.href;
}

export async function openDocumentInNewWindow(openWindow, loadUrl) {
  const handle = openWindow('', '_blank', 'noopener,noreferrer');
  if (!handle) throw new Error('브라우저가 팝업을 차단했습니다. 팝업을 허용한 뒤 다시 시도해 주세요.');
  handle.opener = null;
  try {
    const url = requireHttpsUrl(await loadUrl());
    if (typeof handle.location?.replace === 'function') handle.location.replace(url);
    else handle.location.href = url;
    return url;
  } catch (error) {
    try { handle.close(); } catch { /* best effort: never retain a failed blank popup */ }
    throw error;
  }
}

export async function fetchAllSettlementSummaries(fetchPage, { limit = 100, maxPages = 100 } = {}) {
  const rows = [];
  const ids = new Set();
  for (let page = 0; page < maxPages; page += 1) {
    const items = (await fetchPage({ limit, offset: page * limit }))?.items ?? [];
    for (const item of items) {
      if (!item?.id) throw new Error('Settlement list item is missing an id.');
      if (ids.has(item.id)) throw new Error(`Duplicate settlement id received: ${item.id}`);
      ids.add(item.id);
      rows.push(item);
    }
    if (items.length < limit) return rows;
  }
  throw new Error(`Settlement pagination safety limit reached (${maxPages} pages).`);
}

export async function loadSettlementDetails(summaries, fetchDetail, { batchSize = 10 } = {}) {
  const rows = [];
  const failures = [];
  for (let start = 0; start < summaries.length; start += batchSize) {
    const batch = summaries.slice(start, start + batchSize);
    const settled = await Promise.allSettled(batch.map((item) => fetchDetail(item)));
    settled.forEach((result, index) => {
      if (result.status === 'fulfilled') rows.push(result.value);
      else failures.push({ id: batch[index]?.id, error: result.reason });
    });
  }
  return { rows, failures };
}

function localDateTimeValue(now) {
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function paymentFormForSettlement(row, now = new Date()) {
  const remaining = Math.max(0, Number(row?.total_amount ?? 0) - Number(row?.payment?.amount ?? 0));
  return {
    amount: String(remaining),
    depositor_name: text(row?.recipient?.name),
    deposited_at: localDateTimeValue(now),
    memo: '',
  };
}

export function buildPaymentPayload(form, idempotencyKey) {
  const amount = Number(form?.amount);
  if (!Number.isInteger(amount) || amount <= 0) throw new Error('입금액은 1원 이상의 정수여야 합니다.');
  const depositorName = text(form?.depositor_name).trim();
  if (!depositorName) throw new Error('입금자명을 입력해 주세요.');
  const date = new Date(form?.deposited_at);
  if (!form?.deposited_at || Number.isNaN(date.getTime())) throw new Error('입금 일시를 올바르게 입력해 주세요.');
  return {
    amount,
    depositor_name: depositorName,
    deposited_at: date.toISOString(),
    memo: text(form?.memo).trim() || null,
    idempotency_key: idempotencyKey,
  };
}

export function settlementApiRoot(isMerchant) {
  return isMerchant ? '/admin/merchant/settlements' : '/company/settlements';
}
