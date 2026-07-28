const DEMO_FLAG_KEYS = ['settlement_demo', 'is_demo', 'demo'];

export function isDemoTransaction(item) {
  if (!item || typeof item !== 'object') return false;
  if (item.is_demo === true || item.is_demo === 'true') return true;
  const flags = item.flags;
  return !!flags && typeof flags === 'object'
    && DEMO_FLAG_KEYS.some((key) => flags[key] === true || flags[key] === 'true');
}

export function filterMerchantTransactions(list) {
  return list;
}

export function merchantMealPaymentIds(list) {
  return (list?.items ?? [])
    .filter((item) => item.source !== 'payment' && !['refund', 'cancel'].includes(item.kind))
    .map((item) => String(item.id));
}

export function reconcileMerchantPaymentFeed(list, notifiedIds, ready = true) {
  const safeList = list;
  const ids = merchantMealPaymentIds(list);
  const known = notifiedIds instanceof Set ? notifiedIds : new Set();
  const newIds = ready ? ids.filter((id) => !known.has(id)) : [];
  const nextNotifiedIds = new Set(known);
  ids.forEach((id) => nextNotifiedIds.add(id));
  return { list: safeList, newIds, nextNotifiedIds };
}

export function merchantRecentKpis(list, day, timeZone = 'Asia/Seoul') {
  const safeList = filterMerchantTransactions(list);
  const payments = (safeList?.items ?? []).filter((item) => (
    item.source !== 'payment'
    && !['refund', 'cancel'].includes(item.kind)
    && item.created_at
    && new Date(item.created_at).toLocaleDateString('sv-SE', { timeZone }) === day
  ));
  return {
    amount: payments.reduce((sum, item) => sum + Math.abs(Number(item.amount ?? 0)), 0),
    count: payments.length,
    loadedCount: safeList?.items?.length ?? 0,
    totalCount: Number.isFinite(Number(safeList?.total_count)) ? Number(safeList.total_count) : null,
  };
}
