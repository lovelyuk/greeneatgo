// Pure helpers for the restaurant revenue panel (unit-tested).

const number = (value) => (Number.isFinite(Number(value)) ? Number(value) : 0);
const text = (value) => (typeof value === 'string' ? value : value == null ? '' : String(value));

export const won = (value) => `${number(value) < 0 ? '-' : ''}₩${Math.abs(number(value)).toLocaleString('ko-KR')}`;

function mapParty(row = {}) {
  return {
    key: text(row.key),
    name: text(row.name) || '거래처',
    revenue_amount: number(row.revenue_amount),
    net_payment_amount: number(row.net_payment_amount),
    invoice_amount: number(row.invoice_amount),
    usage_amount: number(row.usage_amount),
    usage_count: number(row.usage_count),
    unbilled_amount: number(row.unbilled_amount),
  };
}

/** GET /admin/merchant/revenue/summary -> what the panel renders. */
export function mapRevenueSummary(data = {}) {
  const paid = data?.paid_basis ?? {};
  return {
    paid: {
      revenue: number(paid.revenue_amount),
      payment: number(paid.payment_amount),
      refund: number(paid.refund_amount),
      netPayment: number(paid.net_payment_amount),
      invoice: number(paid.invoice_amount),
      invoiceCount: number(paid.invoice_count),
      paymentCount: number(paid.payment_count),
      // Company points used on those orders: billed separately, not revenue here.
      point: number(paid.point_amount),
    },
    usage: { amount: number(data?.usage_basis?.amount), count: number(data?.usage_basis?.count) },
    unbilled: { amount: number(data?.unbilled?.amount), count: number(data?.unbilled?.count) },
    parties: (Array.isArray(data?.parties) ? data.parties : []).map(mapParty).filter((party) => party.key),
  };
}

/** The dashboard's ranking tables only know company names. */
export function partyByName(parties, name) {
  const wanted = text(name).trim();
  if (!wanted) return null;
  return (Array.isArray(parties) ? parties : []).find((party) => party.name === wanted) ?? null;
}

const KIND_LABELS = { payment: '식권 결제', refund: '환불', invoice: '세금계산서' };
const MEAL_LABELS = { ledger: '장부', subsidized: '보조금', voucher: '식권' };

export function dateTimeParts(value) {
  const parsed = value ? new Date(value) : null;
  if (!parsed || Number.isNaN(parsed.getTime())) return { date: '-', time: '-' };
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(parsed).map((part) => [part.type, part.value]));
  return { date: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}` };
}

/** GET /admin/merchant/revenue/detail -> rows for the popup. */
export function mapRevenueDetail(data = {}) {
  const paid = data?.paid_basis ?? {};
  const usage = data?.usage_basis ?? {};
  const entries = (Array.isArray(paid.entries) ? paid.entries : []).map((row) => ({
    ...dateTimeParts(row?.at),
    kind: text(row?.kind),
    kindLabel: KIND_LABELS[row?.kind] ?? '-',
    label: text(row?.label) || '-',
    who: text(row?.person_name) && row.person_name !== '-' ? text(row.person_name) : '',
    // Payment method for payments/refunds, NTS approval number for invoices.
    note: text(row?.method),
    amount: number(row?.amount),
    point: number(row?.point_amount),
  }));
  const items = (Array.isArray(usage.items) ? usage.items : []).map((row) => ({
    id: row?.id,
    ...dateTimeParts(row?.at),
    name: text(row?.person_name) || '-',
    department: text(row?.department) || '-',
    employeeNo: text(row?.employee_no) || '-',
    kindLabel: row?.kind === 'spend' ? (MEAL_LABELS[row?.pay_type] ?? '식사') : row?.kind === 'refund' ? '환불' : '취소',
    item: text(row?.item) || '-',
    amount: number(row?.amount),
  }));
  return {
    name: text(data?.party?.name) || '거래처',
    paid: {
      revenue: number(paid.revenue_amount), payment: number(paid.payment_amount), refund: number(paid.refund_amount),
      invoice: number(paid.invoice_amount), entries, entryCount: number(paid.entry_count) || entries.length,
    },
    usage: {
      amount: number(usage.amount), count: number(usage.count), cancelCount: number(usage.cancel_count),
      daily: (Array.isArray(usage.daily) ? usage.daily : []).map((row) => ({
        date: text(row?.date), count: number(row?.count), cancelCount: number(row?.cancel_count), amount: number(row?.amount),
      })),
      items, itemCount: number(usage.item_count) || items.length,
    },
    unbilled: {
      amount: number(data?.unbilled?.amount),
      settlements: (Array.isArray(data?.unbilled?.settlements) ? data.unbilled.settlements : []).map((row) => ({
        month: text(row?.period_ym), amount: number(row?.amount),
      })),
    },
    limit: number(data?.detail_limit) || 500,
  };
}
