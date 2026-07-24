import re
from pathlib import Path


MIGRATION = Path(__file__).resolve().parents[3] / "infra/migrations/0032_product_subsidized_vouchers.sql"


def _sql() -> str:
    return re.sub(r"\s+", " ", MIGRATION.read_text(encoding="utf-8").lower()).strip()


def test_product_subsidized_migration_issues_paid_then_bonus_snapshots():
    sql = _sql()
    fulfill = sql.split("create or replace function fulfill_subsidized_order", 1)[1].split(
        "create or replace function consume_subsidized_voucher", 1
    )[0]
    assert "for i in 1..o.voucher_count loop" in fulfill
    assert "o.voucher_product_id" in fulfill
    assert "paid_price:=floor(o.total_employee_burden::numeric/o.paid_voucher_count)::int" in fulfill
    assert "burden_remainder:=o.total_employee_burden-(paid_price*o.paid_voucher_count)" in fulfill
    assert "case when i<=o.paid_voucher_count then paid_price+case when i<=burden_remainder then 1 else 0 end else 0 end" in fulfill
    assert "case when i<=o.paid_voucher_count then o.company_subsidy_amount else 0 end" in fulfill
    assert "case when i<=o.paid_voucher_count then o.restaurant_subsidy_amount else 0 end" in fulfill
    assert "on conflict(order_id,issue_index) do nothing" in fulfill


def test_product_subsidized_migration_fulfills_only_the_explicit_legacy_shape():
    sql = _sql()
    fulfill = sql.split("create or replace function fulfill_subsidized_order", 1)[1].split(
        "create or replace function consume_subsidized_voucher", 1
    )[0]
    assert "legacy:=coalesce(o.voucher_product_id is null and o.voucher_count=1 and o.paid_voucher_count=1 and o.bonus_voucher_count=0,false)" in fulfill
    assert "if legacy then" in fulfill
    assert "values(o.user_id,o.merchant_id,null,o.id,1,o.voucher_purchase_price" in fulfill
    assert "on conflict(order_id,issue_index) do nothing" in fulfill
    assert "or (o.voucher_product_id is null and not legacy)" in fulfill


def test_product_subsidized_consumption_is_fifo_and_uses_voucher_snapshots():
    sql = _sql()
    consume = sql.split("create or replace function consume_subsidized_voucher", 1)[1].split(
        "create or replace function claim_purchase_order_refund", 1
    )[0]
    assert "o.status='done'" in consume
    assert "refund_processing" not in consume
    assert "select status into order_status from payment_orders where id=candidate_order_id for update" in consume
    assert "select * into v from vouchers where id=candidate_id and status='unused' for update" in consume
    assert "skip locked" not in consume
    queue_lock = "pg_advisory_xact_lock(hashtextextended( 'voucher-refund-queue:'||p_user_id::text||':'||p_company_id::text||':'||p_merchant_id::text,0))"
    assert queue_lock in consume
    assert consume.index(queue_lock) < consume.index("select * into existing")
    assert "v.purchase_price<>trunc(v.purchase_price)" in consume
    assert "employee_amount:=v.purchase_price::int" in consume
    assert "v.company_subsidy_amount+v.restaurant_subsidy_amount" in consume
    assert "merchant_companies%rowtype" not in consume
    assert "unit_price" not in consume


def test_ordinary_consumption_is_replaced_with_done_only_strict_fifo():
    sql = _sql()
    consume = sql.split("create or replace function consume_voucher", 1)[1].split(
        "create or replace function consume_subsidized_voucher", 1
    )[0]
    queue_lock = "'voucher-refund-queue:'||p_user_id::text||':ordinary:'||p_merchant_id::text"
    assert queue_lock in consume
    assert consume.index(queue_lock) < consume.index("select * into existing")
    assert "join payment_orders o on o.id=vq.order_id" in consume
    assert "o.status='done' and o.pay_type='voucher'" in consume
    assert "refund_processing" not in consume
    assert "refunded" not in consume
    assert "canceled" not in consume
    assert "order by vq.purchased_at,vq.issue_index,vq.id limit 1" in consume
    assert "skip locked" not in consume
    assert "select status into order_status from payment_orders where id=candidate_order_id for update" in consume


def test_refund_claim_uses_matching_queue_lock_and_durable_single_owner_lease():
    sql = _sql()
    claim = sql.split("create or replace function claim_purchase_order_refund", 1)[1].split(
        "create or replace function record_purchase_order_refund_provider_success", 1
    )[0]
    assert "add column if not exists processing_token uuid" in sql
    assert "add column if not exists lease_expires_at timestamptz" in sql
    assert "'voucher-refund-queue:'||p_user_id::text||':'|| coalesce(v_order.company_id::text,'ordinary')||':'||p_merchant_id::text" in claim
    assert claim.index("pg_advisory_xact_lock") < claim.index("where id=p_order_id for update")
    assert "r.status='processing' and r.lease_expires_at>now()" in claim
    assert "'acquired',false" in claim
    assert "'error_code','refund_in_progress'" in claim
    assert "lease_expires_at=now()+interval '5 minutes'" in claim
    assert "processing_token=new_token" in claim
    assert "'acquired',true" in claim


def test_refund_provider_state_writes_require_current_owner_token():
    sql = _sql()
    success = sql.split("create or replace function record_purchase_order_refund_provider_success", 1)[1].split(
        "create or replace function fail_purchase_order_refund", 1
    )[0]
    fail = sql.split("create or replace function fail_purchase_order_refund", 1)[1].split(
        "create or replace function finalize_purchase_order_refund", 1
    )[0]
    token_guard = "r.processing_token is distinct from p_processing_token"
    assert token_guard in success
    assert success.index(token_guard) < success.index("r.status in ('provider_succeeded','completed')")
    assert "status='provider_succeeded'" in success
    assert "lease_expires_at=null" in success
    assert token_guard in fail
    assert fail.index(token_guard) < fail.index("r.status<>'provider_in_flight'")
    assert "status='failed'" in fail
    assert "refund_lease_not_owned" in success
    assert "refund_lease_not_owned" in fail


def test_ambiguous_refund_state_is_durable_token_guarded_and_not_reclaimable():
    sql = _sql()
    claim = sql.split("create or replace function claim_purchase_order_refund", 1)[1].split(
        "create or replace function record_purchase_order_refund_provider_success", 1
    )[0]
    reconcile = sql.split("create or replace function mark_purchase_order_refund_reconciliation_required", 1)[1].split(
        "create or replace function fail_purchase_order_refund", 1
    )[0]
    assert "reconciliation_required" in sql
    assert "add column if not exists reconciliation_details jsonb" in sql
    assert "r.status in ('provider_in_flight','reconciliation_required')" in claim
    assert "else 'refund_reconciliation_required' end" in claim
    assert "'acquired',false" in claim
    token_guard = "r.processing_token is distinct from p_processing_token"
    assert token_guard in reconcile
    assert reconcile.index(token_guard) < reconcile.index("r.status='reconciliation_required'")
    assert "status='reconciliation_required'" in reconcile
    assert "processing_token=null,lease_expires_at=null" in reconcile
    assert "failure_code=p_failure_code" in reconcile
    assert "reconciliation_details=p_reconciliation_details" in reconcile
    assert "update payment_orders set status='done'" not in reconcile


def test_provider_attempt_is_durable_non_reclaimable_and_all_outcomes_are_guarded():
    sql = _sql()
    claim = sql.split("create or replace function claim_purchase_order_refund", 1)[1].split(
        "create or replace function mark_purchase_order_refund_provider_attempt_started", 1
    )[0]
    attempt = sql.split("create or replace function mark_purchase_order_refund_provider_attempt_started", 1)[1].split(
        "create or replace function record_purchase_order_refund_provider_success", 1
    )[0]
    success = sql.split("create or replace function record_purchase_order_refund_provider_success", 1)[1].split(
        "create or replace function mark_purchase_order_refund_reconciliation_required", 1
    )[0]
    reconcile = sql.split("create or replace function mark_purchase_order_refund_reconciliation_required", 1)[1].split(
        "create or replace function fail_purchase_order_refund", 1
    )[0]
    fail = sql.split("create or replace function fail_purchase_order_refund", 1)[1].split(
        "create or replace function finalize_purchase_order_refund", 1
    )[0]
    token_guard = "r.processing_token is distinct from p_processing_token"

    assert "'processing','provider_in_flight','provider_succeeded'" in sql
    assert "status in ('processing','provider_in_flight','provider_succeeded','reconciliation_required','completed')" in sql
    assert "r.status in ('provider_in_flight','reconciliation_required')" in claim
    assert "'error_code',case when r.status='provider_in_flight' then 'refund_provider_attempt_in_flight'" in claim
    assert "'acquired',false" in claim
    assert "provider_in_flight" not in claim.split("elsif r.status='processing' then", 1)[1]

    assert token_guard in attempt
    assert attempt.index(token_guard) < attempt.index("r.status='provider_in_flight'")
    assert "status='provider_in_flight',lease_expires_at=null" in attempt
    assert "processing_token=null" not in attempt
    assert "grant execute on function mark_purchase_order_refund_provider_attempt_started(uuid,uuid,uuid) to service_role" in attempt

    for outcome in (success, reconcile, fail):
        assert token_guard in outcome
        assert "r.status<>'provider_in_flight'" in outcome
    assert "status='provider_succeeded'" in success
    assert "status='reconciliation_required'" in reconcile
    assert "status='failed'" in fail
    assert "update payment_orders set status='done'" in fail


def test_integer_burden_distribution_conserves_every_order_total():
    # Behavioral counterpart to the PL/pgSQL expression above, including a
    # burden smaller than the paid count and free bonus snapshots.
    for total, paid, bonus, expected in (
        (52_000, 10, 1, [5_200] * 10 + [0]),
        (10, 3, 2, [4, 3, 3, 0, 0]),
        (2, 3, 1, [1, 1, 0, 0]),
    ):
        base, remainder = divmod(total, paid)
        snapshots = [base + (index < remainder) for index in range(paid)] + [0] * bonus
        assert snapshots == expected
        assert sum(snapshots[:paid]) == total
        assert snapshots[paid:] == [0] * bonus


def test_product_subsidized_refund_excludes_subsidies_and_forfeits_bonus():
    sql = _sql()
    claim = sql.split("create or replace function claim_purchase_order_refund", 1)[1].split(
        "create or replace function finalize_purchase_order_refund", 1
    )[0]
    finalize = sql.split("create or replace function finalize_purchase_order_refund", 1)[1]
    assert "burden_base:=floor(o.total_employee_burden::numeric/o.paid_voucher_count)::int" in claim
    assert "burden_remainder:=o.total_employee_burden-(burden_base*o.paid_voucher_count)" in claim
    assert "burden_base*used_paid+least(used_paid,burden_remainder)" in claim
    assert "card_refund:=refundable_burden-point_refund" in claim
    assert "if card_refund>o.amount then" in claim
    assert "company_subsidy_amount" not in claim
    assert "restaurant_subsidy_amount" not in claim
    assert "issue_index<=o.paid_voucher_count" in finalize
    assert "issue_index>o.paid_voucher_count" in finalize
    assert "status='forfeited'" in finalize


def test_stale_subsidized_expiry_is_bounded_atomic_and_service_only():
    sql = _sql()
    expire = sql.split("create or replace function expire_stale_subsidized_orders", 1)[1].split(
        "create or replace function fulfill_subsidized_order", 1
    )[0]
    assert "pay_type='subsidized' and status='ready'" in expire
    assert "created_at<=now()-interval '30 minutes'" in expire
    assert "order by created_at,id for update" in expire
    assert "stale_ids:=array_append(stale_ids,stale.id)" in expire
    assert "if stale.point_reserved then released_points:=released_points+stale.point_amount" in expire
    assert "point_reserved=greatest(point_reserved-released_points,0)" in expire
    assert "where id=any(stale_ids) and status='ready'" in expire
    assert "status='canceled'" in expire
    assert "point_transactions" in expire  # comment documents why releases have no balance audit row
    assert "grant execute on function expire_stale_subsidized_orders(uuid) to service_role" in expire
    assert "grant execute on function expire_stale_subsidized_orders(uuid) to authenticated" not in expire


def test_exact_refund_formula_matches_fifo_integer_snapshots():
    for burden, card, points, paid, used, expected in (
        (11, 10, 1, 3, 2, (2, 1)),
        (10, 1, 9, 3, 2, (0, 3)),
        (2, 0, 2, 3, 1, (0, 1)),
    ):
        base, remainder = divmod(burden, paid)
        refundable = burden - (base * used + min(used, remainder))
        point_refund = min(max(points - points * used // paid, 0), points, refundable)
        card_refund = refundable - point_refund
        if card_refund > card:
            point_refund += card_refund - card
            card_refund = card
        point_refund = min(point_refund, points)
        card_refund = max(refundable - point_refund, 0)
        assert (card_refund, point_refund) == expected
        assert card_refund + point_refund == refundable
