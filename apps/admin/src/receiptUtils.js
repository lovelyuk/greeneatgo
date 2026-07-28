const RECEIPT_HOSTS = new Set([
  'agent.kiwoompay.co.kr',
  'agenttest.kiwoompay.co.kr',
]);

const RECEIPT_PATHS = new Map([
  ['/common/PayInfoPrintDirectCard.jsp', new Set(['DAOUTRX', 'STATUS'])],
  ['/common/PayInfoPrintBank.jsp', new Set(['DAOUTRX', 'STATUS'])],
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
