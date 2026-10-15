"""Bounded local receipt presentation; never verified provider/order closure."""
from datetime import datetime
from uuid import UUID

LOCAL_SELECT = 'id,order_id,user_id,amount,source,scope,outcome,requested_by,requested_at,provider_finality,residual_late_approval_possible'


def public_local_abandonment(row: dict, *, order: dict, owner: str) -> dict:
    """Fail closed on malformed stored receipts; no token/provider payload exposure."""
    if (str(order.get('user_id')) != str(owner)
            or str(row.get('order_id')) != str(order['id']) or str(row.get('user_id')) != str(owner)
            or type(row.get('amount')) is not int or row['amount'] != int(order['amount'])
            or str(row.get('requested_by')) != str(owner)
            or row.get('source') != 'owner_request' or row.get('scope') != 'local_order'
            or row.get('outcome') != 'abandoned' or row.get('provider_finality') != 'unknown'
            or row.get('residual_late_approval_possible') is not True):
        raise ValueError('Invalid local abandonment identity')
    receipt_id = str(UUID(str(row['id'])))
    requested_at = row['requested_at']
    parsed = datetime.fromisoformat(requested_at.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Local receipt requires timezone')
    return dict(id=receipt_id, source='owner_request', scope='local_order', outcome='abandoned',
                requested_by=str(owner), requested_at=requested_at, provider_finality='unknown',
                residual_late_approval_possible=True)


def local_recovery(repo, order: dict, owner: str) -> dict | None:
    rows = repo.client.rest_get('payment_order_local_abandonments', {
        'select': LOCAL_SELECT, 'order_id': f"eq.{order['id']}",
        'user_id': f'eq.{owner}', 'amount': f"eq.{order['amount']}", 'limit': '1',
    })
    if not rows:
        return None
    receipt = public_local_abandonment(rows[0], order=order, owner=owner)
    # Any non-failure discrepancy is retained financial uncertainty, not closure.
    events = repo.client.rest_get('payment_callback_discrepancies', {
        'select': 'kind', 'order_id': f"eq.{order['id']}", 'kind': 'neq.nonapproval', 'limit': '1',
    })
    contradiction = bool(events or order.get('provider_payment_key') or order.get('approved_at')
                         or order.get('fulfilled_at') or order.get('status') != 'canceled')
    return dict(order_id=order['order_id'], user_id=str(owner), amount=int(order['amount']),
                status=order['status'], recovery_action='reconcile' if contradiction else 'locally_abandoned',
                resumable=False, checkout_url=None, completion=None, local_abandonment=receipt)
