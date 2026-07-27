-- Runtime tax classification and immutable transaction snapshots.
-- Existing rows stay unclassified. New money movement requires explicit classification.

-- Supabase normally grants this already, but the migration makes the RPC
-- execution prerequisite explicit without granting direct table mutation.
grant usage on schema public to service_role;

alter table payment_orders add column if not exists tax_type text not null default 'unclassified';
alter table vouchers add column if not exists tax_type text not null default 'unclassified';

-- Migration 0032 is immutable. Evolve its complete order-shape constraint here.
-- Ordinary package pricing is based on paid vouchers; bonus vouchers are free.
alter table public.payment_orders
  drop constraint if exists payment_orders_voucher_columns_check;

-- Migration 0028 recorded pre-bonus ordinary orders as though every issued voucher
-- were paid. Narrowly repair only an exact provider-ready or completed legacy shape
-- before enforcing the paid-count formula. Anything ambiguous fails closed before a
-- rewrite: ready orders must have no vouchers, while done orders must have exactly the
-- complete issue-index set and every voucher must still carry the old order snapshot
-- and the authoritative order ownership, tenant, product, and ordinary-order identity.
-- Used vouchers are included, but their status and used_at are deliberately preserved.
alter table public.vouchers add column if not exists purchase_price_won integer;

do $legacy_bonus_voucher_shape$
begin
 -- Non-fulfillable terminal/in-flight states are never migration targets. They cannot
 -- satisfy the new order formula while retaining their legacy snapshot, so abort the
 -- migration rather than silently changing refund or failure history.
 if exists (
   select 1
   from public.payment_orders o
   where o.pay_type='voucher'
     and o.voucher_count is not null and o.paid_voucher_count is not null
     and o.bonus_voucher_count is not null
     and o.voucher_count>0 and o.paid_voucher_count>0 and o.bonus_voucher_count>0
     and o.paid_voucher_count+o.bonus_voucher_count=o.voucher_count
     and o.amount>0
     and o.voucher_purchase_price=round(o.amount::numeric/o.voucher_count,4)
     and o.voucher_purchase_price<>round(o.amount::numeric/o.paid_voucher_count,4)
     and o.status not in ('ready','done')
 ) then
   raise exception 'LEGACY_BONUS_VOUCHER_STATUS_UNSUPPORTED' using errcode='P0001';
 end if;

 if exists (
   select 1
   from public.payment_orders o
   where o.pay_type='voucher'
     and o.voucher_count is not null and o.paid_voucher_count is not null
     and o.bonus_voucher_count is not null
     and o.voucher_count>0 and o.paid_voucher_count>0 and o.bonus_voucher_count>0
     and o.paid_voucher_count+o.bonus_voucher_count=o.voucher_count
     and o.amount>0
     and o.voucher_purchase_price=round(o.amount::numeric/o.voucher_count,4)
     and o.voucher_purchase_price<>round(o.amount::numeric/o.paid_voucher_count,4)
     and o.status='ready'
     and exists (select 1 from public.vouchers v where v.order_id=o.id)
 ) then
   raise exception 'LEGACY_BONUS_READY_ORDER_HAS_VOUCHERS' using errcode='P0001';
 end if;

 if exists (
   select 1
   from public.payment_orders o
   where o.pay_type='voucher'
     and o.voucher_count is not null and o.paid_voucher_count is not null
     and o.bonus_voucher_count is not null
     and o.voucher_count>0 and o.paid_voucher_count>0 and o.bonus_voucher_count>0
     and o.paid_voucher_count+o.bonus_voucher_count=o.voucher_count
     and o.amount>0
     and o.voucher_purchase_price=round(o.amount::numeric/o.voucher_count,4)
     and o.voucher_purchase_price<>round(o.amount::numeric/o.paid_voucher_count,4)
     and o.status='done'
     and (
       (select count(*) from public.vouchers v where v.order_id=o.id)<>o.voucher_count
       or exists (
         select 1 from generate_series(1,o.voucher_count) expected(issue_index)
         where not exists (
           select 1 from public.vouchers v
           where v.order_id=o.id and v.issue_index=expected.issue_index
         )
       )
       or exists (
         select 1 from public.vouchers v
         where v.order_id=o.id
           and (
             v.purchase_price is distinct from round(o.amount::numeric/o.voucher_count,4)
             or v.user_id is distinct from o.user_id
             or v.merchant_id is distinct from o.merchant_id
             or v.product_id is distinct from o.voucher_product_id
             or v.company_id is not null
             or v.company_subsidy_amount is not null
             or v.restaurant_subsidy_amount is not null
             -- Legacy ordinary fulfillment copied the provider key to every issued
             -- voucher. IS DISTINCT FROM also safely accepts genuinely keyless rows
             -- only when the authoritative order is keyless.
             or v.pg_transaction_id is distinct from o.provider_payment_key
           )
       )
     )
 ) then
   raise exception 'LEGACY_BONUS_DONE_ORDER_MALFORMED' using errcode='P0001';
 end if;
end $legacy_bonus_voucher_shape$;

with legacy_bonus_orders as (
 select o.id,o.amount,o.voucher_count,o.paid_voucher_count
 from public.payment_orders o
 where o.pay_type='voucher'
   and o.voucher_count is not null and o.paid_voucher_count is not null
   and o.bonus_voucher_count is not null
   and o.voucher_count>0 and o.paid_voucher_count>0 and o.bonus_voucher_count>0
   and o.paid_voucher_count+o.bonus_voucher_count=o.voucher_count
   and o.amount>0
   and o.voucher_purchase_price=round(o.amount::numeric/o.voucher_count,4)
   and o.voucher_purchase_price<>round(o.amount::numeric/o.paid_voucher_count,4)
   and o.status='done'
), allocations as (
 select v.id,
   case when v.issue_index<=o.paid_voucher_count
     then (o.amount/o.paid_voucher_count)
       + case when v.issue_index<=o.amount%o.paid_voucher_count then 1 else 0 end
     else 0 end as exact_price
 from public.vouchers v
 join legacy_bonus_orders o on o.id=v.order_id
)
update public.vouchers v
set purchase_price=a.exact_price,
    purchase_price_won=a.exact_price
from allocations a
where v.id=a.id;

update public.payment_orders o
set voucher_purchase_price=round(o.amount::numeric/o.paid_voucher_count,4)
where o.pay_type='voucher'
  and o.voucher_count is not null and o.paid_voucher_count is not null
  and o.bonus_voucher_count is not null
  and o.voucher_count>0 and o.paid_voucher_count>0 and o.bonus_voucher_count>0
  and o.paid_voucher_count+o.bonus_voucher_count=o.voucher_count
  and o.amount>0
  and o.voucher_purchase_price=round(o.amount::numeric/o.voucher_count,4)
  and o.voucher_purchase_price<>round(o.amount::numeric/o.paid_voucher_count,4)
  and o.status in ('ready','done');

alter table public.payment_orders
  add constraint payment_orders_voucher_columns_check check (
    (pay_type = 'direct' and voucher_product_id is null and voucher_count is null
      and voucher_purchase_price is null and fulfilled_at is null and company_id is null
      and point_amount = 0 and total_employee_burden is null)
    or (pay_type = 'voucher' and product_id is null and voucher_product_id is not null
      and voucher_count > 0 and voucher_purchase_price > 0 and amount > 0
      and company_id is null and point_amount = 0 and total_employee_burden is null
      and paid_voucher_count > 0 and bonus_voucher_count >= 0
      and paid_voucher_count + bonus_voucher_count = voucher_count
      and voucher_purchase_price = round(amount::numeric / paid_voucher_count, 4))
    -- Preserve the explicit historical subsidized shape from 0032.
    or (pay_type = 'subsidized' and product_id is null and voucher_product_id is null
      and voucher_count = 1 and paid_voucher_count = 1 and bonus_voucher_count = 0
      and company_id is not null and company_subsidy_amount is not null
      and restaurant_subsidy_amount is not null and total_employee_burden is not null
      and amount is not null and point_amount is not null and voucher_purchase_price is not null
      and company_subsidy_amount >= 0 and restaurant_subsidy_amount >= 0
      and total_employee_burden > 0 and amount >= 0 and point_amount >= 0
      and amount + point_amount = total_employee_burden
      and voucher_purchase_price = round(total_employee_burden::numeric, 4))
    or (pay_type = 'subsidized' and product_id is null and voucher_product_id is not null
      and voucher_count is not null and paid_voucher_count is not null and bonus_voucher_count is not null
      and company_id is not null and company_subsidy_amount is not null
      and restaurant_subsidy_amount is not null and total_employee_burden is not null
      and amount is not null and point_amount is not null and voucher_purchase_price is not null
      and voucher_count > 0 and paid_voucher_count > 0 and bonus_voucher_count >= 0
      and paid_voucher_count + bonus_voucher_count = voucher_count
      and company_subsidy_amount >= 0 and restaurant_subsidy_amount >= 0
      and total_employee_burden > 0 and amount >= 0 and point_amount >= 0
      and amount + point_amount = total_employee_burden
      and voucher_purchase_price = round(total_employee_burden::numeric / paid_voucher_count, 4))
  );

-- First-apply cutover marker. Orders which were already provider-ready before
-- runtime tax classification existed are quarantined for explicit review. The
-- column test means migration replay cannot requeue newer orders.
do $cutover$
begin
 if not exists (
   select 1 from pg_catalog.pg_attribute
   where attrelid='public.payment_orders'::pg_catalog.regclass
     and attname='tax_review_required' and not attisdropped
 ) then
   alter table public.payment_orders
     add column tax_review_required boolean not null default false;
   update public.payment_orders set tax_review_required=true
   where status='ready' and tax_type='unclassified';
 end if;
end $cutover$;

-- Fractional legacy snapshots are intentionally not rounded.
update public.vouchers set purchase_price_won=purchase_price::integer
where purchase_price_won is null and purchase_price=pg_catalog.trunc(purchase_price);

-- Migration 0032 reconstructed ordinary package refunds from an order-level
-- ratio. That can exceed the unused vouchers by one won when the paid amount has
-- a remainder. For complete ordinary package shapes, the integer voucher rows
-- are now the authoritative refund ledger; ambiguous legacy shapes fail closed.
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
 if o.status<>'done' or o.pay_type not in ('voucher','subsidized') then raise exception 'ORDER_NOT_REFUNDABLE' using errcode='P0001'; end if;
 perform 1 from vouchers where order_id=o.id order by issue_index,id for update;
 select count(*) filter(where status='used'),
   count(*) filter(where status='unused' and issue_index<=o.paid_voucher_count),
   count(*) filter(where status='unused' and issue_index>o.paid_voucher_count)
 into used_count,paid_remaining,unused_bonus from vouchers where order_id=o.id;
 if paid_remaining=0 and unused_bonus=0 then raise exception 'PAID_VOUCHERS_EXHAUSTED' using errcode='P0001'; end if;
 select coalesce(sum(refund_amount),0) into already_refunded from refund_requests where order_id=o.id and status='completed';
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

alter table payment_orders drop constraint if exists payment_orders_tax_type_check;
alter table payment_orders add constraint payment_orders_tax_type_check
  check (tax_type in ('taxable','tax_free','unclassified'));
alter table vouchers drop constraint if exists vouchers_tax_type_check;
alter table vouchers add constraint vouchers_tax_type_check
  check (tax_type in ('taxable','tax_free','unclassified'));

-- PostgreSQL numeric round is half-away-from-zero. Monetary inputs are nonnegative.
create or replace function split_tax_inclusive(p_total int, p_tax_type text)
returns table(supply_amount int, vat_amount int, total_amount int)
language plpgsql immutable strict set search_path=public as $$
begin
 if p_total<0 then raise exception 'INVALID_TAX_TOTAL' using errcode='P0001'; end if;
 if p_tax_type='taxable' then
  supply_amount:=round(p_total::numeric/1.1)::int;
  vat_amount:=p_total-supply_amount;
 elsif p_tax_type='tax_free' then
  supply_amount:=p_total; vat_amount:=0;
 else
  raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode='P0001';
 end if;
 total_amount:=p_total;
 return next;
end $$;
revoke all on function split_tax_inclusive(int,text) from public,anon,authenticated;
grant execute on function split_tax_inclusive(int,text) to service_role;

-- Payment order tax comes only from its tenant-scoped product. Client values are ignored.
create or replace function snapshot_payment_order_tax() returns trigger
language plpgsql set search_path=public as $$
declare authoritative text;
begin
 if new.pay_type in ('voucher','subsidized') then
  select tax_type into authoritative from voucher_products
   where id=new.voucher_product_id and merchant_id=new.merchant_id;
 elsif new.pay_type='direct' then
  select tax_type into authoritative from merchant_products
   where id=new.product_id and merchant_id=new.merchant_id;
 else
  return new;
 end if;
 if not found then raise exception 'TAX_PRODUCT_NOT_FOUND' using errcode='P0001'; end if;
 if authoritative='unclassified' then raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode='P0001'; end if;
 new.tax_type:=authoritative;
 return new;
end $$;
revoke all on function snapshot_payment_order_tax() from public,anon,authenticated;
drop trigger if exists trg_snapshot_payment_order_tax on payment_orders;
create trigger trg_snapshot_payment_order_tax before insert on payment_orders
for each row execute function snapshot_payment_order_tax();

-- Once captured, order/voucher/transaction tax facts cannot drift with product edits.
create or replace function prevent_tax_snapshot_update() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 if new.tax_type is distinct from old.tax_type then
  if old.tax_type<>'unclassified' or new.tax_type not in ('taxable','tax_free') then
   raise exception 'IMMUTABLE_TAX_SNAPSHOT' using errcode='P0001';
  end if;
  if tg_table_name='payment_orders' and not exists (
   select 1 from public.tax_classification_audit a
   join public.payment_notification_inbox n on n.id=a.inbox_id
   where a.transaction_xid=pg_catalog.txid_current() and a.order_id=new.id
     and a.voucher_id is null and a.merchant_id=new.merchant_id
     and a.previous_tax_type=old.tax_type and a.selected_tax_type=new.tax_type
     and n.order_id=new.id and n.merchant_id=new.merchant_id
  ) then raise exception 'AUDITED_TAX_CLASSIFICATION_REQUIRED' using errcode='P0001';
  elsif tg_table_name='vouchers' and not exists (
   select 1 from public.tax_classification_audit a
   where a.transaction_xid=pg_catalog.txid_current() and a.voucher_id=new.id
     and a.order_id is null and a.inbox_id is null and a.merchant_id=new.merchant_id
     and a.previous_tax_type=old.tax_type and a.selected_tax_type=new.tax_type
  ) then raise exception 'AUDITED_TAX_CLASSIFICATION_REQUIRED' using errcode='P0001';
  end if;
 end if;
 return new;
end $$;
revoke all on function prevent_tax_snapshot_update() from public,anon,authenticated;

create or replace function prevent_transaction_tax_snapshot_update() returns trigger
language plpgsql set search_path=public as $$
begin
 if new.tax_type is distinct from old.tax_type
   or new.supply_amount is distinct from old.supply_amount or new.vat_amount is distinct from old.vat_amount
   or new.total_amount is distinct from old.total_amount
   or new.settlement_tax_type is distinct from old.settlement_tax_type
   or new.settlement_supply_amount is distinct from old.settlement_supply_amount
   or new.settlement_vat_amount is distinct from old.settlement_vat_amount
   or new.settlement_total_amount is distinct from old.settlement_total_amount
 then raise exception 'IMMUTABLE_TAX_SNAPSHOT' using errcode='P0001'; end if;
 return new;
end $$;
revoke all on function prevent_transaction_tax_snapshot_update() from public,anon,authenticated;
drop trigger if exists trg_payment_orders_immutable_tax on payment_orders;
create trigger trg_payment_orders_immutable_tax before update on payment_orders for each row execute function prevent_tax_snapshot_update();
drop trigger if exists trg_vouchers_immutable_tax on vouchers;
create trigger trg_vouchers_immutable_tax before update on vouchers for each row execute function prevent_tax_snapshot_update();
drop trigger if exists trg_meal_transactions_immutable_tax on meal_transactions;
create trigger trg_meal_transactions_immutable_tax before update on meal_transactions for each row execute function prevent_transaction_tax_snapshot_update();

-- Ordinary fulfillment copies the immutable order snapshot, never the current product.
create or replace function fulfill_voucher_order(p_order_id uuid,p_provider_payment_key text,p_payment_method text,p_provider_response jsonb,p_approved_at timestamptz)
returns jsonb language plpgsql security definer set search_path=public as $$
declare o payment_orders%rowtype; issued int; balance int; duplicate boolean; base_price int; remainder int;
begin
 select * into o from payment_orders where id=p_order_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND' using errcode='P0001'; end if;
 if o.pay_type<>'voucher' or o.product_id is not null or o.voucher_product_id is null
    or o.voucher_count<=0 or o.paid_voucher_count<=0 or o.bonus_voucher_count<0
    or o.paid_voucher_count+o.bonus_voucher_count<>o.voucher_count
    or o.voucher_purchase_price<=0 or o.amount<=0
    or o.voucher_purchase_price<>round(o.amount::numeric/o.paid_voucher_count,4)
 then raise exception 'NOT_VOUCHER_ORDER' using errcode='P0001'; end if;
 if o.tax_type='unclassified' then raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode='P0001'; end if;
 if o.tax_review_required then raise exception 'TAX_REVIEW_REQUIRED' using errcode='P0001'; end if;
 if p_provider_payment_key is null or btrim(p_provider_payment_key)='' then raise exception 'PAYMENT_KEY_REQUIRED' using errcode='P0001'; end if;
 if o.status not in ('ready','done') then raise exception 'ORDER_NOT_FULFILLABLE' using errcode='P0001'; end if;
 if o.provider_payment_key is not null and o.provider_payment_key<>p_provider_payment_key then raise exception 'PAYMENT_KEY_MISMATCH' using errcode='P0001'; end if;
 duplicate:=o.fulfilled_at is not null;
 update payment_orders set status='done',provider_payment_key=coalesce(provider_payment_key,p_provider_payment_key),
  payment_method=coalesce(p_payment_method,payment_method),provider_response=coalesce(p_provider_response,provider_response),
  approved_at=coalesce(approved_at,p_approved_at,now()),updated_at=now()
 where id=o.id returning * into o;
 base_price:=o.amount/o.paid_voucher_count; remainder:=o.amount-(base_price*o.paid_voucher_count);
 insert into vouchers(user_id,merchant_id,product_id,order_id,issue_index,purchase_price,purchase_price_won,pg_transaction_id,purchased_at,tax_type)
 select o.user_id,o.merchant_id,o.voucher_product_id,o.id,n,
   case when n<=o.paid_voucher_count then base_price+case when n<=remainder then 1 else 0 end else 0 end,
   case when n<=o.paid_voucher_count then base_price+case when n<=remainder then 1 else 0 end else 0 end,
   o.provider_payment_key,coalesce(o.approved_at,now()),o.tax_type
 from generate_series(1,o.voucher_count) n on conflict(order_id,issue_index) do nothing;
 select count(*) into issued from vouchers where order_id=o.id and tax_type=o.tax_type;
 if issued<>o.voucher_count then raise exception 'VOUCHER_ISSUE_INCOMPLETE' using errcode='P0001'; end if;
 if (select coalesce(sum(purchase_price_won),-1) from vouchers where order_id=o.id)<>o.amount
 then raise exception 'VOUCHER_ALLOCATION_MISMATCH' using errcode='P0001'; end if;
 update payment_orders set fulfilled_at=coalesce(fulfilled_at,now()) where id=o.id;
 select count(*) into balance from vouchers where user_id=o.user_id and merchant_id=o.merchant_id and status='unused';
 return jsonb_build_object('order_id',o.order_id,'status','done','issued_count',issued,'voucher_balance',balance,'duplicate',duplicate,'tax_type',o.tax_type);
end $$;
revoke all on function fulfill_voucher_order(uuid,text,text,jsonb,timestamptz) from public,anon,authenticated;
grant execute on function fulfill_voucher_order(uuid,text,text,jsonb,timestamptz) to service_role;

-- Keep the 0032 subsidized fulfillment semantics and add tax copying/blocking.
create or replace function fulfill_subsidized_order(p_order_id uuid,p_provider_payment_key text,p_payment_method text,p_provider_response jsonb,p_approved_at timestamptz) returns jsonb
language plpgsql security definer set search_path=public as $$
declare o payment_orders%rowtype; first_voucher vouchers%rowtype; u app_users%rowtype;
 duplicate boolean; legacy boolean; i int; paid_price int; burden_remainder int;
begin
 select * into o from payment_orders where id=p_order_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND' using errcode='P0001'; end if;
 legacy:=coalesce(o.voucher_product_id is null and o.voucher_count=1 and o.paid_voucher_count=1 and o.bonus_voucher_count=0,false);
 if o.pay_type<>'subsidized' or o.company_id is null or (o.voucher_product_id is null and not legacy)
  or o.paid_voucher_count<=0 or o.bonus_voucher_count<0 or o.voucher_count<>o.paid_voucher_count+o.bonus_voucher_count
  or o.total_employee_burden<=0 then raise exception 'NOT_SUBSIDIZED_ORDER' using errcode='P0001'; end if;
 if o.tax_type='unclassified' then raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode='P0001'; end if;
 if o.tax_review_required then raise exception 'TAX_REVIEW_REQUIRED' using errcode='P0001'; end if;
 if o.amount>0 and (p_provider_payment_key is null or btrim(p_provider_payment_key)='') then raise exception 'PAYMENT_KEY_REQUIRED' using errcode='P0001'; end if;
 if o.amount>0 and o.checkout_started_at is null and not legacy then raise exception 'CHECKOUT_NOT_STARTED' using errcode='P0001'; end if;
 if o.amount=0 and p_provider_payment_key is not null then raise exception 'POINT_ONLY_PAYMENT_KEY_FORBIDDEN' using errcode='P0001'; end if;
 if o.status not in ('ready','done') then raise exception 'ORDER_NOT_FULFILLABLE' using errcode='P0001'; end if;
 if o.provider_payment_key is not null and o.provider_payment_key<>p_provider_payment_key then raise exception 'PAYMENT_KEY_MISMATCH' using errcode='P0001'; end if;
 duplicate:=o.fulfilled_at is not null;
 if not duplicate and o.point_amount>0 then
  select * into u from app_users where id=o.user_id for update;
  if not o.point_reserved or u.point_reserved<o.point_amount or u.point_balance<o.point_amount then raise exception 'POINT_RESERVATION_CONFLICT' using errcode='P0001'; end if;
  update app_users set point_balance=point_balance-o.point_amount,point_reserved=point_reserved-o.point_amount where id=u.id returning * into u;
 end if;
 update payment_orders set status='done',provider_payment_key=coalesce(provider_payment_key,p_provider_payment_key),payment_method=coalesce(p_payment_method,payment_method),
  provider_response=coalesce(p_provider_response,provider_response),approved_at=coalesce(approved_at,p_approved_at,now()),
  fulfilled_at=coalesce(fulfilled_at,now()),point_reserved=false,updated_at=now() where id=o.id returning * into o;
 if legacy then
  insert into vouchers(user_id,merchant_id,product_id,order_id,issue_index,purchase_price,purchase_price_won,company_id,company_subsidy_amount,restaurant_subsidy_amount,pg_transaction_id,purchased_at,tax_type)
  values(o.user_id,o.merchant_id,null,o.id,1,o.voucher_purchase_price,o.total_employee_burden,o.company_id,o.company_subsidy_amount,o.restaurant_subsidy_amount,o.provider_payment_key,coalesce(o.approved_at,now()),o.tax_type)
  on conflict(order_id,issue_index) do nothing;
 else
  paid_price:=floor(o.total_employee_burden::numeric/o.paid_voucher_count)::int;
  burden_remainder:=o.total_employee_burden-(paid_price*o.paid_voucher_count);
  for i in 1..o.voucher_count loop
   insert into vouchers(user_id,merchant_id,product_id,order_id,issue_index,purchase_price,purchase_price_won,company_id,company_subsidy_amount,restaurant_subsidy_amount,pg_transaction_id,purchased_at,tax_type)
   values(o.user_id,o.merchant_id,o.voucher_product_id,o.id,i,
    case when i<=o.paid_voucher_count then paid_price+case when i<=burden_remainder then 1 else 0 end else 0 end,
    case when i<=o.paid_voucher_count then paid_price+case when i<=burden_remainder then 1 else 0 end else 0 end,
    o.company_id,case when i<=o.paid_voucher_count then o.company_subsidy_amount else 0 end,
    case when i<=o.paid_voucher_count then o.restaurant_subsidy_amount else 0 end,o.provider_payment_key,coalesce(o.approved_at,now()),o.tax_type)
   on conflict(order_id,issue_index) do nothing;
  end loop;
 end if;
 select * into first_voucher from vouchers where order_id=o.id order by issue_index limit 1;
 if first_voucher.tax_type is distinct from o.tax_type then raise exception 'VOUCHER_TAX_SNAPSHOT_CONFLICT' using errcode='P0001'; end if;
 if not duplicate and o.point_amount>0 then
  insert into point_transactions(user_id,company_id,type,amount,balance_after,reason,processed_by,related_voucher_id,related_order_id)
  values(o.user_id,o.company_id,'use',-o.point_amount,u.point_balance,'보조금 식권 구매',o.user_id,first_voucher.id,o.id);
 end if;
 return jsonb_build_object('order_id',o.order_id,'status','done','issued_count',o.voucher_count,'voucher_id',first_voucher.id,
  'duplicate',duplicate,'point_amount',o.point_amount,'card_amount',o.amount,'tax_type',o.tax_type);
end $$;
revoke all on function fulfill_subsidized_order(uuid,text,text,jsonb,timestamptz) from public,anon,authenticated;
grant execute on function fulfill_subsidized_order(uuid,text,text,jsonb,timestamptz) to service_role;

create or replace function consume_voucher(p_user_id uuid,p_merchant_id uuid,p_idempotency_key text,p_tx_code text default null)
returns jsonb language plpgsql security definer set search_path=public as $$
declare existing meal_transactions%rowtype; v vouchers%rowtype; tx meal_transactions%rowtype; s record;
 candidate_id uuid; candidate_order_id uuid; order_status text; remaining_count int; total int;
begin
 if p_idempotency_key is null or btrim(p_idempotency_key)='' then raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode='P0001'; end if;
 perform pg_advisory_xact_lock(hashtextextended('voucher-refund-queue:'||p_user_id::text||':ordinary:'||p_merchant_id::text,0));
 perform pg_advisory_xact_lock(1,hashtext(p_idempotency_key));
 select * into existing from meal_transactions where idempotency_key=p_idempotency_key limit 1;
 if found then
  if existing.user_id<>p_user_id or existing.merchant_id<>p_merchant_id or existing.pay_type<>'voucher' or existing.kind<>'spend'
   or existing.voucher_id is null or existing.tax_type='unclassified' or existing.total_amount is null
   or (p_tx_code is not null and existing.tx_code is distinct from p_tx_code)
  then raise exception 'IDEMPOTENCY_CONFLICT' using errcode='P0001'; end if;
  select count(*) into remaining_count from vouchers vq join payment_orders o on o.id=vq.order_id
   where vq.user_id=p_user_id and vq.company_id is null and vq.merchant_id=p_merchant_id and vq.status='unused' and o.status='done' and o.pay_type='voucher';
  return jsonb_build_object('id',existing.id,'amount',existing.total_amount,'voucher_id',existing.voucher_id,'remaining',remaining_count,
   'duplicate',true,'created_at',existing.created_at,'tax_type',existing.tax_type,'supply_amount',existing.supply_amount,'vat_amount',existing.vat_amount,'total_amount',existing.total_amount);
 end if;
 select vq.id,vq.order_id into candidate_id,candidate_order_id from vouchers vq join payment_orders o on o.id=vq.order_id
  where vq.user_id=p_user_id and vq.company_id is null and vq.merchant_id=p_merchant_id and vq.status='unused' and o.status='done' and o.pay_type='voucher'
  order by vq.purchased_at,vq.issue_index,vq.id limit 1;
 if not found then raise exception 'NO_VOUCHER' using errcode='P0001'; end if;
 select status into order_status from payment_orders where id=candidate_order_id for update;
 if order_status<>'done' then raise exception 'NO_VOUCHER' using errcode='P0001'; end if;
 select * into v from vouchers where id=candidate_id and status='unused' for update;
 if not found then raise exception 'NO_VOUCHER' using errcode='P0001'; end if;
 if v.tax_type='unclassified' then raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode='P0001'; end if;
 if v.purchase_price_won is null then raise exception 'VOUCHER_EXACT_PRICE_REQUIRED' using errcode='P0001'; end if;
 total:=v.purchase_price_won; select * into s from split_tax_inclusive(total,v.tax_type);
 update vouchers set status='used',used_at=now() where id=v.id;
 insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,flags,idempotency_key,product_name,product_price,pay_type,voucher_id,
  tax_type,supply_amount,vat_amount,total_amount,settlement_tax_type)
 values(p_user_id,null,p_merchant_id,-total,'spend',coalesce(p_tx_code,upper(substr(replace(gen_random_uuid()::text,'-',''),1,10))),
  '식권',jsonb_build_object('voucher_product_id',v.product_id),p_idempotency_key,'식권 사용',total,'voucher',v.id,
  v.tax_type,s.supply_amount,s.vat_amount,s.total_amount,'unclassified') returning * into tx;
 select count(*) into remaining_count from vouchers vq join payment_orders o on o.id=vq.order_id
  where vq.user_id=p_user_id and vq.company_id is null and vq.merchant_id=p_merchant_id and vq.status='unused' and o.status='done' and o.pay_type='voucher';
 return jsonb_build_object('id',tx.id,'amount',tx.total_amount,'voucher_id',v.id,'remaining',remaining_count,'duplicate',false,'created_at',tx.created_at,
  'tax_type',tx.tax_type,'supply_amount',tx.supply_amount,'vat_amount',tx.vat_amount,'total_amount',tx.total_amount);
end $$;
revoke all on function consume_voucher(uuid,uuid,text,text) from public,anon,authenticated;
grant execute on function consume_voucher(uuid,uuid,text,text) to service_role;

create or replace function consume_subsidized_voucher(p_user_id uuid,p_company_id uuid,p_merchant_id uuid,p_idempotency_key text) returns jsonb
language plpgsql security definer set search_path=public as $$
declare existing meal_transactions%rowtype; v vouchers%rowtype; tx meal_transactions%rowtype; full_split record; settlement_split record;
 candidate_id uuid; candidate_order_id uuid; order_status text; employee_amount int; full_total int; remaining_count int;
begin
 if p_idempotency_key is null or btrim(p_idempotency_key)='' then raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode='P0001'; end if;
 perform pg_advisory_xact_lock(hashtextextended('voucher-refund-queue:'||p_user_id::text||':'||p_company_id::text||':'||p_merchant_id::text,0));
 perform pg_advisory_xact_lock(1,hashtext(p_idempotency_key));
 select * into existing from meal_transactions where idempotency_key=p_idempotency_key limit 1;
 if found then
  if existing.user_id<>p_user_id or existing.company_id<>p_company_id or existing.merchant_id<>p_merchant_id or existing.pay_type<>'subsidized'
   or existing.tax_type='unclassified' or existing.total_amount is null or existing.settlement_total_amount is null
  then raise exception 'IDEMPOTENCY_CONFLICT' using errcode='P0001'; end if;
  select count(*) into remaining_count from vouchers vq join payment_orders o on o.id=vq.order_id where vq.user_id=p_user_id and vq.company_id=p_company_id
   and vq.merchant_id=p_merchant_id and vq.status='unused' and o.status='done';
  return jsonb_build_object('id',existing.id,'amount',existing.total_amount,'remaining',remaining_count,'duplicate',true,
   'company_subsidy_amount',existing.company_subsidy_amount,'tax_type',existing.tax_type,'supply_amount',existing.supply_amount,'vat_amount',existing.vat_amount,
   'total_amount',existing.total_amount,'settlement_tax_type',existing.settlement_tax_type,'settlement_supply_amount',existing.settlement_supply_amount,
   'settlement_vat_amount',existing.settlement_vat_amount,'settlement_total_amount',existing.settlement_total_amount);
 end if;
 if not exists(select 1 from merchant_companies where merchant_id=p_merchant_id and company_id=p_company_id and status='active' and subsidy_enabled)
  then raise exception 'SUBSIDY_NOT_ACTIVE' using errcode='P0001'; end if;
 select vq.id,vq.order_id into candidate_id,candidate_order_id from vouchers vq join payment_orders o on o.id=vq.order_id
  where vq.user_id=p_user_id and vq.company_id=p_company_id and vq.merchant_id=p_merchant_id and vq.status='unused' and o.status='done'
  order by vq.purchased_at,vq.issue_index,vq.id limit 1;
 if not found then raise exception 'NO_VOUCHER' using errcode='P0001'; end if;
 select status into order_status from payment_orders where id=candidate_order_id for update;
 if order_status<>'done' then raise exception 'NO_VOUCHER' using errcode='P0001'; end if;
 select * into v from vouchers where id=candidate_id and status='unused' for update;
 if not found then raise exception 'NO_VOUCHER' using errcode='P0001'; end if;
 if v.tax_type='unclassified' then raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode='P0001'; end if;
 if v.purchase_price_won is null then raise exception 'INVALID_SUBSIDY_SNAPSHOT' using errcode='P0001'; end if;
 employee_amount:=v.purchase_price_won; full_total:=employee_amount+v.company_subsidy_amount+v.restaurant_subsidy_amount;
 if employee_amount<0 then raise exception 'INVALID_SUBSIDY_SNAPSHOT' using errcode='P0001'; end if;
 select * into full_split from split_tax_inclusive(full_total,v.tax_type);
 select * into settlement_split from split_tax_inclusive(v.company_subsidy_amount,v.tax_type);
 update vouchers set status='used',used_at=now() where id=v.id;
 insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,flags,idempotency_key,product_name,product_price,pay_type,voucher_id,
  employee_paid_amount,company_subsidy_amount,restaurant_subsidy_amount,tax_type,supply_amount,vat_amount,total_amount,
  settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount)
 values(p_user_id,p_company_id,p_merchant_id,-full_total,'spend',upper(substr(replace(gen_random_uuid()::text,'-',''),1,10)),'보조금',jsonb_build_object('subsidized',true),
  p_idempotency_key,'보조금 식권 사용',full_total,'subsidized',v.id,employee_amount,v.company_subsidy_amount,v.restaurant_subsidy_amount,
  v.tax_type,full_split.supply_amount,full_split.vat_amount,full_split.total_amount,v.tax_type,
  settlement_split.supply_amount,settlement_split.vat_amount,settlement_split.total_amount) returning * into tx;
 select count(*) into remaining_count from vouchers vq join payment_orders o on o.id=vq.order_id where vq.user_id=p_user_id and vq.company_id=p_company_id
  and vq.merchant_id=p_merchant_id and vq.status='unused' and o.status='done';
 return jsonb_build_object('id',tx.id,'amount',tx.total_amount,'remaining',remaining_count,'duplicate',false,'voucher_id',v.id,
  'employee_paid_amount',tx.employee_paid_amount,'company_subsidy_amount',tx.company_subsidy_amount,'restaurant_subsidy_amount',tx.restaurant_subsidy_amount,
  'created_at',tx.created_at,'tax_type',tx.tax_type,'supply_amount',tx.supply_amount,'vat_amount',tx.vat_amount,'total_amount',tx.total_amount,
  'settlement_tax_type',tx.settlement_tax_type,'settlement_supply_amount',tx.settlement_supply_amount,'settlement_vat_amount',tx.settlement_vat_amount,
  'settlement_total_amount',tx.settlement_total_amount);
end $$;
revoke all on function consume_subsidized_voucher(uuid,uuid,uuid,text) from public,anon,authenticated;
grant execute on function consume_subsidized_voucher(uuid,uuid,uuid,text) to service_role;

create or replace function process_meal_pay(p_user_id uuid,p_company_id uuid,p_merchant_id uuid,p_amount int,p_tx_code text,
 p_meal_window text,p_flags jsonb,p_idempotency_key text,p_product_id uuid default null,p_product_name text default null,p_product_price int default null)
returns jsonb language plpgsql security definer set search_path=public as $$
declare existing meal_transactions%rowtype; company_status text; contract merchant_companies%rowtype; tx meal_transactions%rowtype; s record;
begin
 if p_idempotency_key is null or btrim(p_idempotency_key)='' then raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode='P0001'; end if;
 if p_amount is null or p_amount<=0 then raise exception 'INVALID_AMOUNT' using errcode='P0001'; end if;
 perform pg_advisory_xact_lock(1,hashtext(p_idempotency_key));
 select * into existing from meal_transactions where idempotency_key=p_idempotency_key limit 1;
 if found then
  if existing.user_id<>p_user_id or existing.company_id is distinct from p_company_id or existing.merchant_id<>p_merchant_id or existing.pay_type<>'ledger'
   or existing.kind<>'spend' or abs(existing.amount)<>p_amount or existing.product_id is distinct from p_product_id
   or existing.product_name is distinct from p_product_name or existing.product_price is distinct from p_product_price
   or existing.tax_type='unclassified' or existing.total_amount is null or existing.settlement_total_amount is null
  then raise exception 'IDEMPOTENCY_CONFLICT' using errcode='P0001'; end if;
  return jsonb_build_object('id',existing.id,'tx_code',existing.tx_code,'amount',existing.total_amount,'duplicate',true,'created_at',existing.created_at,
   'product_id',existing.product_id,'product_name',existing.product_name,'product_price',existing.product_price,'pay_type','ledger','tax_type',existing.tax_type,
   'supply_amount',existing.supply_amount,'vat_amount',existing.vat_amount,'total_amount',existing.total_amount,
   'settlement_tax_type',existing.settlement_tax_type,'settlement_supply_amount',existing.settlement_supply_amount,
   'settlement_vat_amount',existing.settlement_vat_amount,'settlement_total_amount',existing.settlement_total_amount);
 end if;
 perform pg_advisory_xact_lock(2,hashtext(p_user_id::text));
 select status into company_status from companies where id=p_company_id for share;
 if company_status is distinct from 'active' then raise exception 'COMPANY_NOT_ACTIVE' using errcode='P0001'; end if;
 select * into contract from merchant_companies where merchant_id=p_merchant_id and company_id=p_company_id and status='active' for share;
 if not found then raise exception 'NOT_AFFILIATED' using errcode='P0001'; end if;
 if contract.unit_price is null or contract.unit_price<=0 then raise exception 'PRICE_NOT_CONFIGURED' using errcode='P0001'; end if;
 if p_amount<>contract.unit_price then raise exception 'CONTRACT_PRICE_MISMATCH' using errcode='P0001'; end if;
 if contract.tax_type='unclassified' then raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode='P0001'; end if;
 select * into s from split_tax_inclusive(p_amount,contract.tax_type);
 insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,flags,idempotency_key,product_id,product_name,product_price,pay_type,
  tax_type,supply_amount,vat_amount,total_amount,settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount)
 values(p_user_id,p_company_id,p_merchant_id,-p_amount,'spend',p_tx_code,p_meal_window,coalesce(p_flags,'{}'::jsonb),p_idempotency_key,p_product_id,p_product_name,
  p_product_price,'ledger',contract.tax_type,s.supply_amount,s.vat_amount,s.total_amount,contract.tax_type,s.supply_amount,s.vat_amount,s.total_amount) returning * into tx;
 return jsonb_build_object('id',tx.id,'tx_code',tx.tx_code,'amount',tx.total_amount,'duplicate',false,'created_at',tx.created_at,'product_id',tx.product_id,
  'product_name',tx.product_name,'product_price',tx.product_price,'pay_type','ledger','tax_type',tx.tax_type,'supply_amount',tx.supply_amount,'vat_amount',tx.vat_amount,
  'total_amount',tx.total_amount,'settlement_tax_type',tx.settlement_tax_type,'settlement_supply_amount',tx.settlement_supply_amount,
  'settlement_vat_amount',tx.settlement_vat_amount,'settlement_total_amount',tx.settlement_total_amount);
end $$;
revoke all on function process_meal_pay(uuid,uuid,uuid,int,text,text,jsonb,text,uuid,text,int) from public,anon,authenticated;
grant execute on function process_meal_pay(uuid,uuid,uuid,int,text,text,jsonb,text,uuid,text,int) to service_role;

-- Durable legacy approval inbox. Provider identity and money facts are immutable;
-- only the audited release path may advance review state.
create table if not exists public.payment_notification_inbox (
 id uuid primary key default gen_random_uuid(),
 order_id uuid not null references public.payment_orders(id),
 merchant_id uuid not null references public.merchants(id),
 provider_transaction_id text not null,
 provider_order_id text not null,
 cpid text not null,
 amount integer not null check(amount>0),
 payment_method text not null,
 normalized_payload jsonb not null,
 source_ip inet not null,
 received_at timestamptz not null default now(),
 review_status text not null default 'pending' check(review_status in ('pending','released')),
 processed_at timestamptz,
 processed_by uuid,
 unique(provider_transaction_id),
 unique(order_id),
 check((review_status='pending' and processed_at is null and processed_by is null)
    or (review_status='released' and processed_at is not null and processed_by is not null))
);
create index if not exists payment_notification_inbox_merchant_pending_idx
 on public.payment_notification_inbox(merchant_id,received_at,id) where review_status='pending';
alter table public.payment_notification_inbox enable row level security;
revoke all on table public.payment_notification_inbox from public,anon,authenticated;
revoke all on table public.payment_notification_inbox from service_role;
grant select on table public.payment_notification_inbox to service_role;

create table if not exists public.tax_classification_audit (
 id uuid primary key default gen_random_uuid(),
 merchant_id uuid not null references public.merchants(id),
 order_id uuid references public.payment_orders(id),
 voucher_id uuid references public.vouchers(id),
 inbox_id uuid references public.payment_notification_inbox(id),
 actor_id uuid not null,
 previous_tax_type text not null,
 selected_tax_type text not null check(selected_tax_type in ('taxable','tax_free')),
 reason text not null check(length(btrim(reason)) between 3 and 1000),
 transaction_xid bigint not null default pg_catalog.txid_current(),
 created_at timestamptz not null default now(),
 check((order_id is not null)::int+(voucher_id is not null)::int=1),
 check((order_id is not null and inbox_id is not null) or (voucher_id is not null and inbox_id is null))
);
alter table public.tax_classification_audit
 add column if not exists transaction_xid bigint not null default pg_catalog.txid_current();
do $audit_shape$
begin
 if not exists (
  select 1 from pg_catalog.pg_constraint
  where conrelid='public.tax_classification_audit'::pg_catalog.regclass
    and conname='tax_classification_audit_target_shape'
 ) then
  alter table public.tax_classification_audit add constraint tax_classification_audit_target_shape
   check((order_id is not null and voucher_id is null and inbox_id is not null)
      or (order_id is null and voucher_id is not null and inbox_id is null)) not valid;
  alter table public.tax_classification_audit validate constraint tax_classification_audit_target_shape;
 end if;
end $audit_shape$;
alter table public.tax_classification_audit enable row level security;
revoke all on table public.tax_classification_audit from public,anon,authenticated;
revoke all on table public.tax_classification_audit from service_role;
grant select on table public.tax_classification_audit to service_role;

create or replace function public.prevent_tax_classification_audit_mutation() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 raise exception 'IMMUTABLE_TAX_CLASSIFICATION_AUDIT' using errcode='P0001';
end $$;
revoke all on function public.prevent_tax_classification_audit_mutation() from public,anon,authenticated,service_role;
drop trigger if exists trg_tax_classification_audit_append_only on public.tax_classification_audit;
create trigger trg_tax_classification_audit_append_only
 before update or delete or truncate on public.tax_classification_audit
 for each statement execute function public.prevent_tax_classification_audit_mutation();

create or replace function public.prevent_notification_identity_update() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 if new.order_id is distinct from old.order_id or new.merchant_id is distinct from old.merchant_id
  or new.provider_transaction_id is distinct from old.provider_transaction_id
  or new.provider_order_id is distinct from old.provider_order_id or new.cpid is distinct from old.cpid
  or new.amount is distinct from old.amount or new.payment_method is distinct from old.payment_method
  or new.normalized_payload is distinct from old.normalized_payload or new.source_ip is distinct from old.source_ip
  or new.received_at is distinct from old.received_at
 then raise exception 'IMMUTABLE_NOTIFICATION_IDENTITY' using errcode='P0001'; end if;
 return new;
end $$;
revoke all on function public.prevent_notification_identity_update() from public,anon,authenticated;
drop trigger if exists trg_payment_notification_identity on public.payment_notification_inbox;
create trigger trg_payment_notification_identity before update on public.payment_notification_inbox
 for each row execute function public.prevent_notification_identity_update();

create or replace function public.prevent_unaudited_notification_release() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 if (new.review_status,new.processed_at,new.processed_by) is distinct from
    (old.review_status,old.processed_at,old.processed_by) then
  if old.review_status<>'pending' or new.review_status<>'released'
    or new.processed_at is null or new.processed_by is null
    or not exists (
      select 1 from public.tax_classification_audit a
      join public.payment_orders o on o.id=a.order_id
      where a.transaction_xid=pg_catalog.txid_current() and a.inbox_id=new.id
        and a.order_id=new.order_id and a.merchant_id=new.merchant_id
        and a.actor_id=new.processed_by and a.selected_tax_type=o.tax_type
    )
  then raise exception 'AUDITED_NOTIFICATION_RELEASE_REQUIRED' using errcode='P0001'; end if;
 end if;
 return new;
end $$;
revoke all on function public.prevent_unaudited_notification_release() from public,anon,authenticated,service_role;
drop trigger if exists trg_payment_notification_audited_release on public.payment_notification_inbox;
create trigger trg_payment_notification_audited_release before update on public.payment_notification_inbox
 for each row execute function public.prevent_unaudited_notification_release();

create or replace function public.enqueue_legacy_payment_notification(
 p_order_id uuid,p_provider_order_id text,p_cpid text,p_amount int,p_payment_method text,
 p_provider_transaction_id text,p_payload jsonb,p_source_ip inet)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare o public.payment_orders%rowtype; n public.payment_notification_inbox%rowtype; inserted boolean:=false;
begin
 select * into o from public.payment_orders where id=p_order_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND' using errcode='P0001'; end if;
 if not o.tax_review_required or o.tax_type<>'unclassified' or o.status<>'ready'
 then raise exception 'ORDER_NOT_IN_TAX_REVIEW' using errcode='P0001'; end if;
 if p_provider_order_id is distinct from o.order_id or p_amount is distinct from o.amount
   or p_provider_transaction_id is null or btrim(p_provider_transaction_id)=''
   or p_cpid is null or btrim(p_cpid)='' or p_payment_method is null or btrim(p_payment_method)=''
 then raise exception 'NOTIFICATION_IDENTITY_MISMATCH' using errcode='P0001'; end if;
 insert into public.payment_notification_inbox(order_id,merchant_id,provider_transaction_id,
  provider_order_id,cpid,amount,payment_method,normalized_payload,source_ip)
 values(o.id,o.merchant_id,p_provider_transaction_id,p_provider_order_id,p_cpid,p_amount,
  p_payment_method,coalesce(p_payload,'{}'::jsonb),p_source_ip)
 on conflict(provider_transaction_id) do nothing returning * into n;
 inserted:=found;
 select * into n from public.payment_notification_inbox
 where provider_transaction_id=p_provider_transaction_id;
 if not found or n.order_id<>o.id or n.amount<>o.amount or n.provider_order_id<>o.order_id
   or n.cpid<>p_cpid or n.payment_method<>p_payment_method
 then raise exception 'NOTIFICATION_IDEMPOTENCY_CONFLICT' using errcode='P0001'; end if;
 return jsonb_build_object('id',n.id,'status',n.review_status,'duplicate',not inserted);
end $$;
revoke all on function public.enqueue_legacy_payment_notification(uuid,text,text,int,text,text,jsonb,inet) from public,anon,authenticated;
grant execute on function public.enqueue_legacy_payment_notification(uuid,text,text,int,text,text,jsonb,inet) to service_role;

do $remove_unbounded_review_rpc$
begin
 if pg_catalog.to_regprocedure('public.list_legacy_tax_reviews(uuid)') is not null then
  revoke all on function public.list_legacy_tax_reviews(uuid) from public,anon,authenticated,service_role;
 end if;
end $remove_unbounded_review_rpc$;
drop function if exists public.list_legacy_tax_reviews(uuid);
create or replace function public.list_legacy_tax_reviews(p_merchant_id uuid,p_limit int,p_offset int) returns jsonb
language sql stable security definer set search_path=pg_catalog,public as $$
 with bounds as (
  select greatest(1,least(coalesce(p_limit,50),100)) as page_limit,
         greatest(coalesce(p_offset,0),0) as page_offset
 ), eligible as (
  select n.id as inbox_id,o.id as order_id,n.provider_order_id,n.amount,n.payment_method,
   n.provider_transaction_id,n.received_at,o.pay_type,o.product_name,
   coalesce(o.product_id,o.voucher_product_id) as product_id,
   coalesce(mp.tax_type,vp.tax_type) as suggested_tax_type
  from public.payment_notification_inbox n join public.payment_orders o on o.id=n.order_id
  left join public.merchant_products mp on mp.id=o.product_id and mp.merchant_id=o.merchant_id
  left join public.voucher_products vp on vp.id=o.voucher_product_id and vp.merchant_id=o.merchant_id
  where n.merchant_id=p_merchant_id and n.review_status='pending' and o.tax_review_required
 ), page as (
  select e.* from eligible e,bounds b order by e.received_at,e.inbox_id
  limit (select page_limit from bounds) offset (select page_offset from bounds)
 )
 select jsonb_build_object(
  'items',coalesce((select jsonb_agg(to_jsonb(page) order by received_at,inbox_id) from page),'[]'::jsonb),
  'total',(select count(*) from eligible),
  'limit',(select page_limit from bounds),'offset',(select page_offset from bounds),
  'has_more',(select page_offset+page_limit < (select count(*) from eligible) from bounds)
 )
$$;
revoke all on function public.list_legacy_tax_reviews(uuid,int,int) from public,anon,authenticated;
grant execute on function public.list_legacy_tax_reviews(uuid,int,int) to service_role;

create or replace function public.release_legacy_tax_review(
 p_inbox_id uuid,p_merchant_id uuid,p_actor_id uuid,p_tax_type text,p_reason text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare n public.payment_notification_inbox%rowtype; o public.payment_orders%rowtype; result jsonb;
begin
 if p_tax_type not in ('taxable','tax_free') then raise exception 'INVALID_TAX_TYPE' using errcode='P0001'; end if;
 if p_reason is null or length(btrim(p_reason))<3 then raise exception 'REVIEW_REASON_REQUIRED' using errcode='P0001'; end if;
 select * into n from public.payment_notification_inbox where id=p_inbox_id and merchant_id=p_merchant_id for update;
 if not found then raise exception 'TAX_REVIEW_NOT_FOUND' using errcode='P0001'; end if;
 select * into o from public.payment_orders where id=n.order_id and merchant_id=p_merchant_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND' using errcode='P0001'; end if;
 if n.review_status='released' then
  if o.tax_type<>p_tax_type then raise exception 'TAX_REVIEW_ALREADY_RELEASED' using errcode='P0001'; end if;
  return jsonb_build_object('order_id',o.order_id,'status',o.status,'duplicate',true,'tax_type',o.tax_type);
 end if;
 if not o.tax_review_required or o.status<>'ready' or o.tax_type<>'unclassified'
 then raise exception 'ORDER_NOT_IN_TAX_REVIEW' using errcode='P0001'; end if;
 if n.provider_order_id<>o.order_id or n.amount<>o.amount or n.provider_transaction_id is null
 then raise exception 'NOTIFICATION_IDENTITY_MISMATCH' using errcode='P0001'; end if;
 insert into public.tax_classification_audit(merchant_id,order_id,inbox_id,actor_id,previous_tax_type,selected_tax_type,reason,transaction_xid)
 values(p_merchant_id,o.id,n.id,p_actor_id,'unclassified',p_tax_type,btrim(p_reason),pg_catalog.txid_current());
 update public.payment_orders set tax_type=p_tax_type,tax_review_required=false where id=o.id;
 if o.pay_type='voucher' then
  result:=public.fulfill_voucher_order(o.id,n.provider_transaction_id,n.payment_method,n.normalized_payload,n.received_at);
 elsif o.pay_type='subsidized' then
  result:=public.fulfill_subsidized_order(o.id,n.provider_transaction_id,n.payment_method,n.normalized_payload,n.received_at);
 else
  update public.payment_orders set status='done',provider_payment_key=n.provider_transaction_id,
   payment_method=n.payment_method,provider_response=n.normalized_payload,approved_at=n.received_at,updated_at=now()
  where id=o.id and status='ready';
  result:=jsonb_build_object('order_id',o.order_id,'status','done','tax_type',p_tax_type);
 end if;
 update public.payment_notification_inbox set review_status='released',processed_at=now(),processed_by=p_actor_id where id=n.id;
 return result||jsonb_build_object('duplicate',false,'tax_type',p_tax_type);
end $$;
revoke all on function public.release_legacy_tax_review(uuid,uuid,uuid,text,text) from public,anon,authenticated;
grant execute on function public.release_legacy_tax_review(uuid,uuid,uuid,text,text) to service_role;

-- Active legacy vouchers are never inferred. This one-way audited operation is
-- the only route from unclassified to classified before consumption.
create or replace function public.classify_legacy_voucher(
 p_voucher_id uuid,p_merchant_id uuid,p_actor_id uuid,p_tax_type text,p_reason text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare v public.vouchers%rowtype;
begin
 if p_tax_type not in ('taxable','tax_free') or p_reason is null or length(btrim(p_reason))<3
 then raise exception 'INVALID_TAX_CLASSIFICATION' using errcode='P0001'; end if;
 select * into v from public.vouchers where id=p_voucher_id and merchant_id=p_merchant_id for update;
 if not found then raise exception 'VOUCHER_NOT_FOUND' using errcode='P0001'; end if;
 if v.tax_type=p_tax_type then return jsonb_build_object('id',v.id,'tax_type',v.tax_type,'duplicate',true); end if;
 if v.tax_type<>'unclassified' or v.status<>'unused' or v.purchase_price_won is null
 then raise exception 'VOUCHER_NOT_CLASSIFIABLE' using errcode='P0001'; end if;
 insert into public.tax_classification_audit(merchant_id,voucher_id,actor_id,previous_tax_type,selected_tax_type,reason,transaction_xid)
 values(p_merchant_id,v.id,p_actor_id,'unclassified',p_tax_type,btrim(p_reason),pg_catalog.txid_current());
 update public.vouchers set tax_type=p_tax_type where id=v.id;
 return jsonb_build_object('id',v.id,'tax_type',p_tax_type,'duplicate',false);
end $$;
revoke all on function public.classify_legacy_voucher(uuid,uuid,uuid,text,text) from public,anon,authenticated;
grant execute on function public.classify_legacy_voucher(uuid,uuid,uuid,text,text) to service_role;

-- Merchant-scoped, PII-free and bounded operational view for active legacy vouchers.
create or replace function public.list_active_legacy_vouchers(
 p_merchant_id uuid,p_limit int default 50,p_offset int default 0)
returns jsonb language sql stable security definer set search_path=pg_catalog,public as $$
 select jsonb_build_object(
  'items',coalesce(jsonb_agg(jsonb_build_object(
    'id',q.id,'product_id',q.product_id,'order_id',q.order_id,
    'purchase_price_won',q.purchase_price_won,'purchased_at',q.purchased_at,
    'company_id',q.company_id,'status',q.status,'tax_type',q.tax_type
  ) order by q.purchased_at,q.id),'[]'::jsonb),
  'limit',greatest(1,least(coalesce(p_limit,50),100)),
  'offset',greatest(coalesce(p_offset,0),0)
 ) from (
  select v.id,v.product_id,v.order_id,v.purchase_price_won,v.purchased_at,
         v.company_id,v.status,v.tax_type
  from public.vouchers v
  where v.merchant_id=p_merchant_id and v.status='unused' and v.tax_type='unclassified'
  order by v.purchased_at,v.id
  limit greatest(1,least(coalesce(p_limit,50),100))
  offset greatest(coalesce(p_offset,0),0)
 ) q
$$;
revoke all on function public.list_active_legacy_vouchers(uuid,int,int) from public,anon,authenticated;
grant execute on function public.list_active_legacy_vouchers(uuid,int,int) to service_role;

-- Semantic snapshots: classified rows are complete and mathematically exact;
-- unclassified rows carry no derived money facts. NOT VALID preserves dirty
-- history while enforcing every new/changed row. Validate automatically only
-- when the existing table is clean.
alter table public.meal_transactions drop constraint if exists meal_transactions_exact_tax_snapshot;
alter table public.meal_transactions add constraint meal_transactions_exact_tax_snapshot check (
 (tax_type='unclassified' and supply_amount is null and vat_amount is null and total_amount is null)
 or (tax_type='tax_free' and num_nonnulls(supply_amount,vat_amount,total_amount)=3
     and supply_amount is not null and vat_amount is not null and total_amount is not null
     and supply_amount=total_amount and vat_amount=0 and total_amount>=0)
 or (tax_type='taxable' and num_nonnulls(supply_amount,vat_amount,total_amount)=3
     and supply_amount is not null and vat_amount is not null and total_amount is not null
     and supply_amount=round(total_amount::numeric/1.1)::int
     and vat_amount=total_amount-supply_amount and total_amount>=0)
) not valid;
alter table public.meal_transactions drop constraint if exists meal_transactions_exact_settlement_tax_snapshot;
alter table public.meal_transactions add constraint meal_transactions_exact_settlement_tax_snapshot check (
 (settlement_tax_type='unclassified' and settlement_supply_amount is null and settlement_vat_amount is null and settlement_total_amount is null)
 or (settlement_tax_type='tax_free' and num_nonnulls(settlement_supply_amount,settlement_vat_amount,settlement_total_amount)=3
     and settlement_supply_amount is not null and settlement_vat_amount is not null and settlement_total_amount is not null
     and settlement_supply_amount=settlement_total_amount and settlement_vat_amount=0 and settlement_total_amount>=0)
 or (settlement_tax_type='taxable' and num_nonnulls(settlement_supply_amount,settlement_vat_amount,settlement_total_amount)=3
     and settlement_supply_amount is not null and settlement_vat_amount is not null and settlement_total_amount is not null
     and settlement_supply_amount=round(settlement_total_amount::numeric/1.1)::int
     and settlement_vat_amount=settlement_total_amount-settlement_supply_amount and settlement_total_amount>=0)
) not valid;
alter table public.payment_orders drop constraint if exists payment_orders_tax_review_shape;
alter table public.payment_orders add constraint payment_orders_tax_review_shape
 check(not tax_review_required or (status='ready' and tax_type='unclassified')) not valid;

do $validate$
begin
 if not exists(select 1 from public.meal_transactions where not coalesce((
  (tax_type='unclassified' and supply_amount is null and vat_amount is null and total_amount is null)
  or (tax_type='tax_free' and num_nonnulls(supply_amount,vat_amount,total_amount)=3 and supply_amount is not null and vat_amount is not null and total_amount is not null and supply_amount=total_amount and vat_amount=0 and total_amount>=0)
  or (tax_type='taxable' and num_nonnulls(supply_amount,vat_amount,total_amount)=3 and supply_amount is not null and vat_amount is not null and total_amount is not null and supply_amount=round(total_amount::numeric/1.1)::int and vat_amount=total_amount-supply_amount and total_amount>=0)),false))
 then alter table public.meal_transactions validate constraint meal_transactions_exact_tax_snapshot; end if;
 if not exists(select 1 from public.meal_transactions where not coalesce((
  (settlement_tax_type='unclassified' and settlement_supply_amount is null and settlement_vat_amount is null and settlement_total_amount is null)
  or (settlement_tax_type='tax_free' and num_nonnulls(settlement_supply_amount,settlement_vat_amount,settlement_total_amount)=3 and settlement_supply_amount is not null and settlement_vat_amount is not null and settlement_total_amount is not null and settlement_supply_amount=settlement_total_amount and settlement_vat_amount=0 and settlement_total_amount>=0)
  or (settlement_tax_type='taxable' and num_nonnulls(settlement_supply_amount,settlement_vat_amount,settlement_total_amount)=3 and settlement_supply_amount is not null and settlement_vat_amount is not null and settlement_total_amount is not null and settlement_supply_amount=round(settlement_total_amount::numeric/1.1)::int and settlement_vat_amount=settlement_total_amount-settlement_supply_amount and settlement_total_amount>=0)),false))
 then alter table public.meal_transactions validate constraint meal_transactions_exact_settlement_tax_snapshot; end if;
 if not exists(select 1 from public.payment_orders where tax_review_required and (status<>'ready' or tax_type<>'unclassified'))
 then alter table public.payment_orders validate constraint payment_orders_tax_review_shape; end if;
end $validate$;

-- Function overloads changed above; make PostgREST discard the unbounded signature.
notify pgrst, 'reload schema';
