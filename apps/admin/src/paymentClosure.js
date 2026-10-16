// Discriminated local-stop authorities; neither source attests PG finality.
export function validLocalAbandonment(result, pending, userId, { history = false } = {}) {
  const r = result?.local_abandonment, stamp = r?.requested_at;
  const authority = r?.source === 'owner_request'
    ? r.requested_by === userId && r.actor_kind === undefined && r.reason === undefined && r.evidence_sha256 === undefined
    : r?.source === 'manual_database_operator' && r.requested_by === undefined &&
      r.actor_kind === 'database_operator' && r.reason === 'manual_local_stop_unknown_provider' &&
      typeof r.evidence_sha256 === 'string' && /^[a-f0-9]{64}$/.test(r.evidence_sha256) &&
      r.acknowledge_provider_uncertainty === undefined && r.explicit_checkout_cancel_intent === undefined &&
      r.checkout_return_ended === undefined;
  const calendar = typeof stamp === 'string' ? stamp.slice(0, 19) : '';
  const date = new Date(`${calendar}Z`);
  return !!(pending && typeof userId === 'string' && userId &&
    /^[A-Za-z0-9_-]{6,64}$/.test(pending.order_id) && Number.isSafeInteger(pending.amount) && pending.amount > 0 &&
    result?.order_id === pending.order_id && result.amount === pending.amount && result.user_id === userId &&
    (history ? ['locally_abandoned', 'reconcile'].includes(result.recovery_action) : result.recovery_action === 'locally_abandoned') &&
    result.status === 'canceled' && result.resumable === false && result.checkout_url === null && result.completion === null &&
    result.closure === undefined && authority && r.scope === 'local_order' && r.outcome === 'abandoned' &&
    r.provider_finality === 'unknown' && r.residual_late_approval_possible === true &&
    typeof r.id === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(r.id) &&
    typeof stamp === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(stamp) &&
    Number.isFinite(date.getTime()) && date.toISOString().slice(0, 19) === calendar && Number.isFinite(Date.parse(stamp)));
}

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
