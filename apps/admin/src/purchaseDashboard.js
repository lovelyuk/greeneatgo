// Match the active Flutter dashboard, not its unused ledger/legacy home.
export function dashboardTransactions(me) {
  return Array.isArray(me.voucher_use_history) && me.voucher_use_history.length
    ? me.voucher_use_history
    : Array.isArray(me.recent_transactions) ? me.recent_transactions : [];
}
export function dashboardSummary(rows) {
  return { count: rows.length, amount: rows.reduce((sum, row) => sum + Math.abs(Number(row.amount) || 0), 0) };
}
export function couponCount(wallet) {
  return wallet ? (wallet.items?.length || 0) + (wallet.issued?.length || 0) : null;
}
export function scanIntent(pending, qr, makeKey) {
  if (pending && pending.qr_data !== qr) throw new Error('이전 QR 요청을 먼저 확인해 주세요.');
  return pending || { qr_data: qr, idempotency_key: makeKey() };
}
