export const SETTLEMENT_MOCK_SCHEMA_VERSION = 5;
export const SETTLEMENT_MOCK_STORE_KEY = `greeneatgo:settlement-workflow:v${SETTLEMENT_MOCK_SCHEMA_VERSION}`;
export const PILOT_COMPANY_SCOPE_ID = 'company-gaon';

export const SETTLEMENT_STATUS_VALUES = ['pending', 'confirmed', 'finalized', 'completed', 'cancelled'];
export const TAX_INVOICE_STATUS_VALUES = ['not_requested', 'requested', 'issuing', 'issued', 'nts_sending', 'nts_accepted', 'failed', 'cancelled'];
export const PAYMENT_STATUS_VALUES = ['unpaid', 'scheduled', 'paid', 'overdue'];

const nonEmptyString = (value) => typeof value === 'string' && value.trim().length > 0;
const nullableString = (value) => value === null || typeof value === 'string';
const finiteAmount = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const datePattern = /^\d{4}-\d{2}-\d{2}$/;
const timestampPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/;

export function isDateString(value) {
  if (!nonEmptyString(value) || !datePattern.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  if (month < 1 || month > 12 || day < 1) return false;
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= daysInMonth[month - 1];
}

export function isTimestampString(value) {
  if (!nonEmptyString(value) || !timestampPattern.test(value)) return false;
  const [datePart] = value.split('T');
  return isDateString(datePart) && Number.isFinite(Date.parse(value));
}

function isNullableTimestamp(value) {
  return value === null || isTimestampString(value);
}

export const BUSINESS_PARTY_REQUIRED_FIELDS = [
  'biz_reg_no', 'name', 'representative_name', 'address', 'business_type',
  'business_item', 'tax_invoice_email', 'contact_name', 'contact_phone',
];

export function isBusinessPartyComplete(value) {
  return Boolean(value)
    && typeof value === 'object'
    && BUSINESS_PARTY_REQUIRED_FIELDS.every((key) => nonEmptyString(value[key]))
    && (value.branch_no === null || value.branch_no === undefined || typeof value.branch_no === 'string');
}

function isInvoice(value, taxStatus) {
  if (taxStatus === 'not_requested') return value === null;
  return Boolean(value)
    && typeof value === 'object'
    && nonEmptyString(value.id)
    && nonEmptyString(value.provider)
    && isDateString(value.written_at)
    && nullableString(value.approval_number)
    && nullableString(value.external_url)
    && nullableString(value.pdf_url)
    && isNullableTimestamp(value.issued_at)
    && isNullableTimestamp(value.nts_sent_at)
    && isNullableTimestamp(value.nts_accepted_at)
    && nullableString(value.failed_reason);
}

function isPayment(value, paymentStatus) {
  if (!value || typeof value !== 'object') return false;
  const commonValid = nullableString(value.bank_name)
    && nullableString(value.account_number)
    && nullableString(value.account_holder)
    && (value.scheduled_at === null || isDateString(value.scheduled_at))
    && isNullableTimestamp(value.paid_at)
    && (value.amount === null || finiteAmount(value.amount))
    && nullableString(value.memo);
  if (!commonValid) return false;
  if (paymentStatus === 'paid') {
    return isTimestampString(value.paid_at) && finiteAmount(value.amount) && nonEmptyString(value.memo);
  }
  return ['unpaid', 'scheduled', 'overdue'].includes(paymentStatus)
    && value.paid_at === null
    && value.amount === 0;
}

export function isValidSettlementMockRow(row) {
  if (!row || typeof row !== 'object') return false;
  if (!['id', 'company_id', 'merchant_id'].every((key) => nonEmptyString(row[key]))) return false;
  if (!isDateString(row.period_start) || !isDateString(row.period_end) || !isDateString(row.due_date)) return false;
  if (row.period_start > row.period_end) return false;
  if (!['total_amount', 'supply_amount', 'vat_amount'].every((key) => finiteAmount(row[key]))) return false;
  if (row.supply_amount + row.vat_amount !== row.total_amount) return false;
  if (!SETTLEMENT_STATUS_VALUES.includes(row.settlement_status)
      || !TAX_INVOICE_STATUS_VALUES.includes(row.tax_invoice_status)
      || !PAYMENT_STATUS_VALUES.includes(row.payment_status)) return false;
  if (!isTimestampString(row.created_at) || !isTimestampString(row.updated_at)) return false;
  if (!isNullableTimestamp(row.confirmed_at) || !isNullableTimestamp(row.tax_invoice_requested_at)) return false;
  if (row.settlement_status === 'pending' && row.confirmed_at !== null) return false;
  if (['confirmed', 'finalized', 'completed'].includes(row.settlement_status) && !isTimestampString(row.confirmed_at)) return false;
  if (row.tax_invoice_status === 'not_requested' && row.tax_invoice_requested_at !== null) return false;
  if (row.tax_invoice_status !== 'not_requested' && !isTimestampString(row.tax_invoice_requested_at)) return false;
  if (['issued', 'nts_sending', 'nts_accepted'].includes(row.tax_invoice_status) && !isTimestampString(row.invoice?.issued_at)) return false;
  if (row.tax_invoice_status === 'nts_accepted' && !isTimestampString(row.invoice?.nts_accepted_at)) return false;
  const postConfirm = ['confirmed', 'finalized', 'completed'].includes(row.settlement_status);
  const nonPaid = ['unpaid', 'scheduled', 'overdue'].includes(row.payment_status);
  if (row.settlement_status === 'pending' && (row.tax_invoice_status !== 'not_requested' || !nonPaid)) return false;
  if (['requested', 'issuing', 'issued', 'nts_sending', 'nts_accepted', 'failed'].includes(row.tax_invoice_status) && !postConfirm) return false;
  if (row.tax_invoice_status === 'cancelled' && !(postConfirm || row.settlement_status === 'cancelled')) return false;
  if (row.payment_status === 'paid' && (!postConfirm || !['issued', 'nts_sending', 'nts_accepted'].includes(row.tax_invoice_status))) return false;
  if (row.payment_status === 'paid' && row.payment?.amount !== row.total_amount) return false;
  if (row.settlement_status === 'cancelled' && row.payment_status === 'paid') return false;
  return isBusinessPartyComplete(row.supplier)
    && isBusinessPartyComplete(row.recipient)
    && isInvoice(row.invoice, row.tax_invoice_status)
    && isPayment(row.payment, row.payment_status);
}

export function isValidSettlementMockRows(rows) {
  return Array.isArray(rows) && rows.length > 0 && rows.every(isValidSettlementMockRow);
}

export function cloneSettlementRows(rows) {
  return rows.map((row) => ({
    ...row,
    supplier: { ...row.supplier },
    recipient: { ...row.recipient },
    invoice: row.invoice ? { ...row.invoice } : null,
    payment: { ...row.payment },
  }));
}

export function loadSettlementMockRows(storage, seedRows) {
  try {
    const stored = storage?.getItem(SETTLEMENT_MOCK_STORE_KEY);
    const parsed = stored ? JSON.parse(stored) : null;
    if (isValidSettlementMockRows(parsed)) return cloneSettlementRows(parsed);
  } catch {
    // Storage can be unavailable (privacy mode, quota/security errors).
  }
  return cloneSettlementRows(seedRows);
}

export function saveSettlementMockRows(storage, rows) {
  if (!isValidSettlementMockRows(rows)) return false;
  try {
    storage?.setItem(SETTLEMENT_MOCK_STORE_KEY, JSON.stringify(rows));
    return Boolean(storage);
  } catch {
    return false;
  }
}

export const canConfirmAndRequest = (row) => row?.settlement_status === 'pending' && row?.tax_invoice_status === 'not_requested';
export const canMerchantIssue = (row) => row?.settlement_status === 'confirmed' && ['requested', 'failed'].includes(row?.tax_invoice_status);
export const canMerchantMarkPaid = (row) => row?.settlement_status !== 'cancelled'
  && ['confirmed', 'finalized', 'completed'].includes(row?.settlement_status)
  && row?.payment_status !== 'paid'
  && ['issued', 'nts_sending', 'nts_accepted'].includes(row?.tax_invoice_status);

function localMockInvoice(row, previous = null) {
  return {
    ...(previous ?? {}),
    id: previous?.id ?? `mock-invoice-${row.id}`,
    provider: 'local_mock',
    approval_number: null,
    external_url: null,
    pdf_url: null,
    written_at: row.period_end,
    issued_at: previous?.issued_at ?? null,
    nts_sent_at: previous?.nts_sent_at ?? null,
    nts_accepted_at: previous?.nts_accepted_at ?? null,
    failed_reason: null,
  };
}

export function transitionSettlementMockRow(row, action, now, recipientSnapshot = null) {
  if (!isTimestampString(now)) return null;
  if (action === 'confirm_and_request' && canConfirmAndRequest(row) && isBusinessPartyComplete(recipientSnapshot)) {
    return {
      ...row,
      settlement_status: 'confirmed',
      tax_invoice_status: 'requested',
      confirmed_at: now,
      tax_invoice_requested_at: now,
      updated_at: now,
      recipient: { ...recipientSnapshot },
      invoice: localMockInvoice(row),
    };
  }
  if (action === 'merchant_issue' && canMerchantIssue(row)) {
    return {
      ...row,
      tax_invoice_status: 'issued',
      updated_at: now,
      invoice: { ...localMockInvoice(row, row.invoice), issued_at: now, nts_sent_at: null, nts_accepted_at: null },
    };
  }
  if (action === 'merchant_mark_paid' && canMerchantMarkPaid(row)) {
    return {
      ...row,
      payment_status: 'paid',
      updated_at: now,
      payment: { ...row.payment, paid_at: now, amount: row.total_amount, memo: `${row.period_start.slice(0, 7)} 식대 정산` },
    };
  }
  return null;
}
