export function paymentMethodLabel(item = {}) {
  const method = String(item.payment_method ?? '').trim().toUpperCase();
  const paidAmount = Number(item.amount ?? item.payment_amount ?? 0);
  const pointAmount = Number(item.point_amount ?? 0);

  if (method === 'POINT') return '포인트';
  if (['BANK', 'CASH', 'TRANSFER', 'BANK_TRANSFER', 'VACCOUNT', 'VBANK', 'VACCT'].includes(method)) return '현금';
  if (method) return '카드';
  if (paidAmount <= 0 && pointAmount > 0) return '포인트';
  return '카드';
}

export function refundButtonState(item = {}) {
  const completed = item.kind === 'refund'
    || String(item.status ?? '').toLowerCase() === 'refunded'
    || Number(item.refund_amount ?? 0) > 0;
  const actionable = !completed
    && String(item.status ?? '').toLowerCase() === 'done'
    && Boolean(item.order_id)
    && Boolean(item.user_id);

  return {
    completed,
    disabled: !actionable,
    label: completed ? '환불완료' : '환불',
  };
}
