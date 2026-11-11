const RECEIPT_HOSTS = new Set([
  'agent.kiwoompay.co.kr',
  'agenttest.kiwoompay.co.kr',
]);

const RECEIPT_PATHS = new Map([
  ['/common/PayInfoPrintDirectCard.jsp', new Set(['DAOUTRX', 'STATUS'])],
  ['/common/PayInfoPrintBank.jsp', new Set(['DAOUTRX', 'STATUS'])],
  ['/common/PayInfoPrintNaverPay.jsp', new Set(['DAOUTRX', 'STATUS'])],
  ['/common/PayInfoPrintKakaoPay.jsp', new Set(['DAOUTRX', 'STATUS'])],
  ['/common/CashRecInfoPrint.jsp', new Set(['DAOUTRX'])],
]);

export function validateReceiptUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || (url.port && url.port !== '443') || url.hash) return '';
    if (!RECEIPT_HOSTS.has(url.hostname.toLowerCase())) return '';
    const allowedParams = RECEIPT_PATHS.get(url.pathname);
    if (!allowedParams || !url.searchParams.get('DAOUTRX')) return '';
    if ([...url.searchParams.keys()].some((key) => !allowedParams.has(key))) return '';
    if (allowedParams.has('STATUS') && url.searchParams.get('STATUS') !== 'A') return '';
    return url.href;
  } catch {
    return '';
  }
}

export function receiptApiPath(descriptor, receiptType) {
  const entryKind = descriptor?.entry_kind;
  const entryId = String(descriptor?.entry_id ?? '').trim();
  if (!['payment', 'refund'].includes(entryKind) || !['sales_slip', 'cash_receipt'].includes(receiptType) || !entryId) return '';
  return `/admin/merchant/payment-history/receipts/${encodeURIComponent(entryKind)}/${encodeURIComponent(entryId)}/${encodeURIComponent(receiptType)}`;
}

export function receiptTypeLabel(type, source = 'payment') {
  const label = type === 'cash_receipt' ? '현금영수증' : '매출전표';
  return source === 'original_payment' ? `원결제 ${label}` : label;
}

const text = (value) => (typeof value === 'string' && value.trim() ? value.trim() : '');
const won = (value) => (Number.isSafeInteger(value) ? `${value.toLocaleString('ko-KR')}원` : '');

function kstDateTime(iso) {
  const time = Date.parse(text(iso));
  if (Number.isNaN(time)) return '';
  const d = new Date(time + 9 * 3600 * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}.${pad(d.getUTCMonth() + 1)}.${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

// Rows of our own payment record for the receipt modal. Empty values are dropped, so a
// missing card name (legacy garbled data is sent as null) never shows as a blank line.
export function receiptRows(receipt) {
  if (!receipt || typeof receipt !== 'object') return [];
  const card = [text(receipt.issuer_name), text(receipt.masked_card_number)].filter(Boolean).join(' ');
  return [
    ['상품명', text(receipt.product_name)],
    ['판매처', text(receipt.merchant_name)],
    ['결제수단', text(receipt.method_label)],
    ['카드', card],
    ['은행', text(receipt.bank_name)],
    ['승인번호', text(receipt.authorization_number)],
    ['주문번호', text(receipt.order_number)],
    ['결제일시', kstDateTime(receipt.approved_at)],
    ['거래상태', receipt.status === 'refunded' ? '환불 완료' : receipt.status === 'done' ? '승인 완료' : ''],
  ].filter(([, value]) => value);
}

// The three values Kiwoom's official slip page asks for before it shows the slip.
export function receiptLookupRows(receipt) {
  const lookup = receipt?.lookup;
  if (!lookup || typeof lookup !== 'object') return [];
  const number = text(lookup.number);
  const date = /^\d{4}-\d{2}-\d{2}$/.test(text(lookup.date)) ? lookup.date : '';
  if (!number || !date || !Number.isSafeInteger(lookup.amount)) return [];
  return [
    { label: '결제일자', value: date },
    { label: '결제금액', value: String(lookup.amount) },
    { label: lookup.number_type === 'order' ? '주문번호' : '승인번호', value: number },
  ];
}

export function receiptAmountLabel(receipt) {
  return won(receipt?.amount);
}

// Buyer completion DTO -> the same three values, for the hint under "매출전표 보기".
export function completionLookupRows(completion) {
  const time = Date.parse(text(completion?.payment?.approved_at));
  const amount = completion?.amount;
  const approval = text(completion?.payment?.authorization_number);
  const number = approval || text(completion?.order_id);
  if (Number.isNaN(time) || !Number.isSafeInteger(amount) || amount <= 0 || !number) return [];
  const date = new Date(time + 9 * 3600 * 1000).toISOString().slice(0, 10);
  return receiptLookupRows({ lookup: { date, amount, number, number_type: approval ? 'approval' : 'order' } });
}
