begin;

-- Direct meal payments are full-order charges with no voucher rows. Reuse the
-- existing claim/lease/provider/finalize pipeline while preserving the locked
-- voucher snapshot calculations for voucher and subsidized orders.
create or replace function public.claim_purchase_order_refund(
  p_order_id uuid, p_merchant_id uuid, p_user_id uuid,
  p_requested_by uuid, p_refund_account jsonb default null
) returns jsonb language plpgsql security definer set search_path=public as $$
declare o payment_orders%rowtype; r refund_requests%rowtype; v_order payment_orders%rowtype;
  new_token uuid;
  used_count int; used_paid int; paid_remaining int; unused_bonus int; card_refund int; point_refund int;
  already_refunded int; burden_base int; burden_remainder int; refundable_burden int;
  snapshot_count int; snapshot_paid_count int; snapshot_bonus_count int;
  snapshot_invalid_count int; snapshot_paid_total bigint; snapshot_bonus_total bigint;
begin
 select * into v_order from payment_orders where id=p_order_id;
 if not found or v_order.merchant_id<>p_merchant_id or v_order.user_id<>p_user_id then raise exception 'ORDER_NOT_FOUND' using errcode='P0001'; end if;
 perform pg_advisory_xact_lock(hashtextextended('voucher-refund-queue:'||p_user_id::text||':'||
   coalesce(v_order.company_id::text,'ordinary')||':'||p_merchant_id::text,0));
 select * into o from payment_orders where id=p_order_id for update;
 if not found or o.merchant_id<>p_merchant_id or o.user_id<>p_user_id
    or o.company_id is distinct from v_order.company_id then raise exception 'ORDER_NOT_FOUND' using errcode='P0001'; end if;
 select * into r from refund_requests where order_id=o.id
   and status in ('processing','provider_in_flight','provider_succeeded','reconciliation_required','completed') for update;
 if found then
  if r.merchant_id<>p_merchant_id or r.user_id<>p_user_id then raise exception 'REFUND_CONFLICT' using errcode='P0001'; end if;
  if r.status in ('provider_in_flight','reconciliation_required') then
   return jsonb_build_object('refund_request_id',r.id,'order_id',o.order_id,
     'provider_payment_key',o.provider_payment_key,'pay_type',o.pay_type,
     'refund_amount',r.refund_amount,'point_amount',r.point_amount,
     'refunded_voucher_count',r.refunded_voucher_count,
     'forfeited_voucher_count',r.forfeited_voucher_count,
     'provider_succeeded',false,'acquired',false,'processing_token',null,
     'error_code',case when r.status='provider_in_flight' then 'REFUND_PROVIDER_ATTEMPT_IN_FLIGHT'
                       else 'REFUND_RECONCILIATION_REQUIRED' end,'pg_response',r.pg_response,
     'reconciliation_details',r.reconciliation_details,'duplicate',true);
  elsif r.status='processing' and r.lease_expires_at>now() then
   return jsonb_build_object('refund_request_id',r.id,'order_id',o.order_id,
     'provider_payment_key',o.provider_payment_key,'pay_type',o.pay_type,
     'refund_amount',r.refund_amount,'point_amount',r.point_amount,
     'refunded_voucher_count',r.refunded_voucher_count,
     'forfeited_voucher_count',r.forfeited_voucher_count,
     'provider_succeeded',false,'acquired',false,'processing_token',null,
     'error_code','REFUND_IN_PROGRESS','pg_response',r.pg_response,'duplicate',true);
  elsif r.status='processing' then
   new_token:=gen_random_uuid();
   update refund_requests set processing_token=new_token,
     lease_expires_at=now()+interval '5 minutes',updated_at=now()
   where id=r.id returning * into r;
  end if;
  return jsonb_build_object('refund_request_id',r.id,'order_id',o.order_id,
    'provider_payment_key',o.provider_payment_key,'pay_type',o.pay_type,
    'refund_amount',r.refund_amount,'point_amount',r.point_amount,
    'refunded_voucher_count',r.refunded_voucher_count,
    'forfeited_voucher_count',r.forfeited_voucher_count,
    'provider_succeeded',r.status in ('provider_succeeded','completed'),
    'acquired',r.status='processing','processing_token',
      case when r.status='processing' then r.processing_token else null end,
    'pg_response',r.pg_response,'duplicate',true);
 end if;
 if o.status<>'done' or o.pay_type not in ('direct','voucher','subsidized') then raise exception 'ORDER_NOT_REFUNDABLE' using errcode='P0001'; end if;
 select coalesce(sum(refund_amount),0) into already_refunded from refund_requests where order_id=o.id and status='completed';
 if o.pay_type='direct' then
  paid_remaining:=0; unused_bonus:=0; point_refund:=0;
  card_refund:=greatest(o.amount-already_refunded,0);
  if card_refund<=0 then raise exception 'ORDER_ALREADY_REFUNDED' using errcode='P0001'; end if;
 else
  perform 1 from vouchers where order_id=o.id order by issue_index,id for update;
  select count(*) filter(where status='used'),
    count(*) filter(where status='unused' and issue_index<=o.paid_voucher_count),
    count(*) filter(where status='unused' and issue_index>o.paid_voucher_count)
  into used_count,paid_remaining,unused_bonus from vouchers where order_id=o.id;
  if paid_remaining=0 and unused_bonus=0 then raise exception 'PAID_VOUCHERS_EXHAUSTED' using errcode='P0001'; end if;
  if o.pay_type='subsidized' then
  used_paid:=o.paid_voucher_count-paid_remaining;
  burden_base:=floor(o.total_employee_burden::numeric/o.paid_voucher_count)::int;
  burden_remainder:=o.total_employee_burden-(burden_base*o.paid_voucher_count);
  refundable_burden:=o.total_employee_burden-
    (burden_base*used_paid+least(used_paid,burden_remainder));

  point_refund:=least(greatest(
    o.point_amount-floor(o.point_amount::numeric*used_paid/o.paid_voucher_count)::int,0),
    o.point_amount,refundable_burden);
  card_refund:=refundable_burden-point_refund;
  if card_refund>o.amount then
   point_refund:=point_refund+(card_refund-o.amount);
   card_refund:=o.amount;
  end if;
  point_refund:=least(point_refund,o.point_amount);
  card_refund:=greatest(refundable_burden-point_refund,0);
 else
  point_refund:=0;
  -- Count and identity checks plus unique(order_id,issue_index) prove this is
  -- exactly the complete issue set. Paid rows total the charge; bonuses are zero.
  select count(*),
    count(*) filter(where issue_index between 1 and o.paid_voucher_count),
    count(*) filter(where issue_index>o.paid_voucher_count and issue_index<=o.voucher_count),
    count(*) filter(where issue_index<1 or issue_index>o.voucher_count
      or purchase_price_won is null or purchase_price_won<0
      or user_id is distinct from o.user_id or merchant_id is distinct from o.merchant_id
      or product_id is distinct from o.voucher_product_id or company_id is not null
      or company_subsidy_amount is not null or restaurant_subsidy_amount is not null
      or pg_transaction_id is distinct from o.provider_payment_key),
    coalesce(sum(purchase_price_won) filter(where issue_index<=o.paid_voucher_count),-1),
    coalesce(sum(purchase_price_won) filter(where issue_index>o.paid_voucher_count),-1)
  into snapshot_count,snapshot_paid_count,snapshot_bonus_count,snapshot_invalid_count,
    snapshot_paid_total,snapshot_bonus_total
  from vouchers where order_id=o.id;
  if snapshot_count<>o.voucher_count
    or snapshot_paid_count<>o.paid_voucher_count
    or snapshot_bonus_count<>o.bonus_voucher_count
    or snapshot_invalid_count<>0
    or snapshot_paid_total<>o.amount
    or snapshot_bonus_total<>0
  then raise exception 'VOUCHER_REFUND_SNAPSHOT_INCOMPLETE' using errcode='P0001'; end if;
  select coalesce(sum(purchase_price_won),0) into card_refund
  from vouchers
  where order_id=o.id and status='unused' and issue_index<=o.paid_voucher_count;
  end if;
 end if;
 new_token:=gen_random_uuid();
 insert into refund_requests(order_id,merchant_id,user_id,requested_by,status,refund_amount,point_amount,
   refunded_voucher_count,forfeited_voucher_count,refund_account,processing_token,lease_expires_at)
 values(o.id,p_merchant_id,p_user_id,p_requested_by,'processing',card_refund,point_refund,
   paid_remaining,unused_bonus,p_refund_account,new_token,now()+interval '5 minutes') returning * into r;
 update payment_orders set status='refund_processing',refund_account=p_refund_account,updated_at=now() where id=o.id;
 return jsonb_build_object('refund_request_id',r.id,'order_id',o.order_id,'provider_payment_key',o.provider_payment_key,
   'pay_type',o.pay_type,'refund_amount',card_refund,'point_amount',point_refund,
   'refunded_voucher_count',paid_remaining,'forfeited_voucher_count',unused_bonus,
   'provider_succeeded',false,'acquired',true,'processing_token',new_token,'duplicate',false);
end $$;
revoke all on function public.claim_purchase_order_refund(uuid,uuid,uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function public.claim_purchase_order_refund(uuid,uuid,uuid,uuid,jsonb) to service_role;

commit;
