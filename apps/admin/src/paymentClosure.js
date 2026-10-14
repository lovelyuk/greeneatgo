// Bounded public closure contract emitted by the authenticated recovery router.
export function verifiedOrderClosure(result, pending, userId) {
  const closure = result?.closure;
  const stamp = closure?.closed_at;
  const calendar = typeof stamp === 'string' ? stamp.slice(0, 19) : '';
  const date = new Date(`${calendar}Z`);
  const validCalendar = Number.isFinite(date.getTime()) && date.toISOString().slice(0, 19) === calendar;
  return !!(validCalendar && result?.recovery_action === 'closed' && result.resumable === false &&
    result.checkout_url === null && result.completion === null &&
    result.user_id === userId && result.order_id === pending.order_id &&
    result.amount === pending.amount && ['failed', 'canceled'].includes(result.status) &&
    closure?.scope === 'order' && closure.finality === 'verified' && closure.outcome === result.status &&
    typeof closure.id === 'string' && /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/.test(closure.id) &&
    typeof closure.evidence_sha256 === 'string' && /^[a-f0-9]{64}$/.test(closure.evidence_sha256) &&
    typeof stamp === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(stamp) &&
    Number.isFinite(Date.parse(stamp)));
}
