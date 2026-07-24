-- Product-based subsidized voucher packages.
-- Apply after 0031_decouple_app_users_from_supabase_auth.sql.

alter table payment_orders
  add column if not exists total_employee_burden int,
  add column if not exists checkout_started_at timestamptz;

alter table payment_orders drop constraint if exists payment_orders_status_check;
alter table payment_orders add constraint payment_orders_status_check
  check (status in ('ready','done','failed','canceled','refund_processing','refunded'));

alter table refund_requests
  add column if not exists provider_succeeded_at timestamptz,
  add column if not exists processing_token uuid,
  add column if not exists lease_expires_at timestamptz,
  add column if not exists reconciliation_details jsonb;
alter table refund_requests drop constraint if exists refund_requests_status_check;
alter table refund_requests add constraint refund_requests_status_check
  check (status in ('processing','provider_in_flight','provider_succeeded','reconciliation_required','completed','failed'));
drop index if exists idx_refund_requests_one_active_order;
create unique index idx_refund_requests_one_active_order on refund_requests(order_id)
  where status in ('processing','provider_in_flight','provider_succeeded','reconciliation_required','completed');

-- Historical subsidized orders contained one paid voucher. Preserve their original
-- burden before replacing the package constraints below.
update payment_orders
set total_employee_burden = amount + coalesce(point_amount, 0)
where pay_type = 'subsidized' and total_employee_burden is null;

alter table payment_orders drop constraint if exists payment_orders_voucher_columns_check;
alter table payment_orders add constraint payment_orders_voucher_columns_check check (
  (pay_type = 'direct' and voucher_product_id is null and voucher_count is null
    and voucher_purchase_price is null and fulfilled_at is null and company_id is null
    and point_amount = 0 and total_employee_burden is null)
  or (pay_type = 'voucher' and product_id is null and voucher_product_id is not null
    and voucher_count > 0 and voucher_purchase_price > 0 and amount > 0
    and company_id is null and point_amount = 0 and total_employee_burden is null
    and voucher_purchase_price = round(amount::numeric / voucher_count, 4))
  -- Explicit historical shape. Keep it separate from the hardened package
  -- branch so SQL CHECK's NULL=unknown behavior cannot admit partial snapshots.
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

alter table vouchers
  add column if not exists restaurant_subsidy_amount int;

-- Existing subsidized voucher rows can derive the restaurant snapshot from the
-- immutable order snapshot. Legacy one-voucher orders had no product reference.
update vouchers v set
  product_id = coalesce(v.product_id, o.voucher_product_id),
  restaurant_subsidy_amount = coalesce(v.restaurant_subsidy_amount, o.restaurant_subsidy_amount, 0)
from payment_orders o
where v.order_id = o.id and o.pay_type = 'subsidized';

alter table vouchers drop constraint if exists vouchers_subsidized_columns_check;
alter table vouchers add constraint vouchers_subsidized_columns_check check (
  (company_id is null and company_subsidy_amount is null and restaurant_subsidy_amount is null
    and product_id is not null)
  or (company_id is not null and company_subsidy_amount >= 0
    and restaurant_subsidy_amount >= 0)
);

drop index if exists idx_vouchers_subsidized_fifo;
create index idx_vouchers_subsidized_fifo
  on vouchers(user_id, company_id, merchant_id, purchased_at, issue_index, id)
  where status = 'unused' and company_id is not null;

-- Reserve points against the full package employee burden. payment_orders.amount
-- remains the card portion after reservation, preserving mixed and point-only flow.
create or replace function reserve_subsidized_order_points(p_order_id uuid) returns jsonb
language plpgsql security definer set search_path=public as $$
declare o payment_orders%rowtype; u app_users%rowtype; employee_due bigint; points bigint;
begin
 select * into o from payment_orders where id=p_order_id for update;
 if not found or o.pay_type<>'subsidized' or o.status<>'ready' then raise exception 'ORDER_NOT_RESERVABLE' using errcode='P0001'; end if;
 if o.point_reserved then return jsonb_build_object('point_amount',o.point_amount,'card_amount',o.amount,'duplicate',true); end if;
 select * into u from app_users where id=o.user_id and role='employee' and company_id=o.company_id for update;
 if not found then raise exception 'EMPLOYEE_NOT_FOUND' using errcode='P0001'; end if;
 employee_due:=o.total_employee_burden;
 if employee_due is null or employee_due<=0 then raise exception 'INVALID_EMPLOYEE_BURDEN' using errcode='P0001'; end if;
 points:=greatest(least(employee_due,u.point_balance-u.point_reserved),0);
 update app_users set point_reserved=point_reserved+points where id=u.id;
 update payment_orders set point_amount=points,point_reserved=(points>0),amount=employee_due-points,updated_at=now() where id=o.id returning * into o;
 return jsonb_build_object('point_amount',points,'card_amount',o.amount,'duplicate',false);
end $$;
revoke all on function reserve_subsidized_order_points(uuid) from public,anon,authenticated;
grant execute on function reserve_subsidized_order_points(uuid) to service_role;

-- The checkout endpoint calls this immediately before returning the provider
-- form. Persist once under the order lock; this is the reconciliation boundary.
create or replace function mark_subsidized_checkout_started(p_order_id uuid) returns jsonb
language plpgsql security definer set search_path=public as $$
declare o payment_orders%rowtype;
begin
 select * into o from payment_orders where id=p_order_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND' using errcode='P0001'; end if;
 if o.pay_type<>'subsidized' or o.status<>'ready' then raise exception 'ORDER_NOT_READY' using errcode='P0001'; end if;
 if o.amount<=0 then raise exception 'POINT_ONLY_ORDER' using errcode='P0001'; end if;
 update payment_orders set checkout_started_at=coalesce(checkout_started_at,now()),updated_at=now()
 where id=o.id returning * into o;
 return jsonb_build_object('order_id',o.order_id,'status',o.status,
   'checkout_started_at',o.checkout_started_at,'reconciliation_required',true);
end $$;
revoke all on function mark_subsidized_checkout_started(uuid) from public,anon,authenticated;
grant execute on function mark_subsidized_checkout_started(uuid) to service_role;

-- Ordinary client abandonment can release points only before provider entry.
-- A started unresolved checkout remains ready/reconciliation-required.
create or replace function release_subsidized_order_points(p_order_id uuid,p_user_id uuid) returns jsonb
language plpgsql security definer set search_path=public as $$
declare o payment_orders%rowtype; u app_users%rowtype;
begin
 select * into o from payment_orders where id=p_order_id and user_id=p_user_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND' using errcode='P0001'; end if;
 if o.status='done' then return jsonb_build_object('released',false,'done',true); end if;
 if o.checkout_started_at is not null then raise exception 'CHECKOUT_ALREADY_STARTED' using errcode='P0001'; end if;
 if o.status<>'ready' then return jsonb_build_object('released',false,'status',o.status); end if;
 select * into u from app_users where id=o.user_id for update;
 if o.point_reserved and o.point_amount>0 then
  update app_users set point_reserved=greatest(point_reserved-o.point_amount,0) where id=u.id;
 end if;
 update payment_orders set point_reserved=false,status='canceled',updated_at=now() where id=o.id;
 return jsonb_build_object('released',true,'point_amount',o.point_amount);
end $$;
revoke all on function release_subsidized_order_points(uuid,uuid) from public,anon,authenticated;
grant execute on function release_subsidized_order_points(uuid,uuid) to service_role;

-- A provider approval can be uncertain for several minutes, so clients must not
-- release reservations immediately. On a later catalog/purchase retry, expire
-- only subsidized orders that have remained ready for at least 30 minutes. Row
-- locks plus the ready predicate make release exactly-once against fulfillment,
-- while done/processing/new orders are deliberately outside this bounded sweep.
create or replace function expire_stale_subsidized_orders(p_user_id uuid) returns jsonb
language plpgsql security definer set search_path=public as $$
declare u app_users%rowtype; stale record; stale_ids uuid[]:=array[]::uuid[];
  released_points bigint:=0; expired_count int:=0;
begin
 -- Lock every candidate in deterministic order before the wallet row. A
 -- concurrent fulfillment either wins and removes its order from this ready-only
 -- set, or waits and then observes canceled; it can never spend released points.
 for stale in
   select id,point_reserved,point_amount from payment_orders
   where user_id=p_user_id and pay_type='subsidized' and status='ready'
     and checkout_started_at is null
     and created_at<=now()-interval '30 minutes'
   order by created_at,id for update
 loop
  stale_ids:=array_append(stale_ids,stale.id);
  expired_count:=expired_count+1;
  if stale.point_reserved then released_points:=released_points+stale.point_amount; end if;
 end loop;
 if expired_count=0 then
  return jsonb_build_object('expired_count',0,'released_point_amount',0);
 end if;
 select * into u from app_users where id=p_user_id for update;
 if not found then raise exception 'USER_NOT_FOUND' using errcode='P0001'; end if;
 if released_points>0 then
  -- Reservations do not change point_balance, so (like the explicit cancel RPC)
  -- no point_transactions balance entry is emitted for this release.
  update app_users set point_reserved=greatest(point_reserved-released_points,0) where id=u.id;
 end if;
 update payment_orders set point_reserved=false,status='canceled',updated_at=now()
 where id=any(stale_ids) and status='ready';
 return jsonb_build_object('expired_count',expired_count,'released_point_amount',released_points);
end $$;
revoke all on function expire_stale_subsidized_orders(uuid) from public,anon,authenticated;
grant execute on function expire_stale_subsidized_orders(uuid) to service_role;

-- Issues paid vouchers first, then bonus vouchers. Every issued row carries the
-- product and economic snapshots needed for future FIFO consumption.
create or replace function fulfill_subsidized_order(p_order_id uuid,p_provider_payment_key text,p_payment_method text,p_provider_response jsonb,p_approved_at timestamptz) returns jsonb
language plpgsql security definer set search_path=public as $$
declare o payment_orders%rowtype; first_voucher vouchers%rowtype; u app_users%rowtype;
  duplicate boolean; legacy boolean; i int; paid_price int; burden_remainder int;
begin
 select * into o from payment_orders where id=p_order_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND' using errcode='P0001'; end if;
 legacy:=coalesce(o.voucher_product_id is null and o.voucher_count=1
   and o.paid_voucher_count=1 and o.bonus_voucher_count=0,false);
 if o.pay_type<>'subsidized' or o.company_id is null
    or (o.voucher_product_id is null and not legacy)
    or o.paid_voucher_count<=0 or o.bonus_voucher_count<0
    or o.voucher_count<>o.paid_voucher_count+o.bonus_voucher_count
    or o.total_employee_burden<=0 then raise exception 'NOT_SUBSIDIZED_ORDER' using errcode='P0001'; end if;
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
 update payment_orders set status='done',provider_payment_key=coalesce(provider_payment_key,p_provider_payment_key),
   payment_method=coalesce(p_payment_method,payment_method),provider_response=coalesce(p_provider_response,provider_response),
   approved_at=coalesce(approved_at,p_approved_at,now()),fulfilled_at=coalesce(fulfilled_at,now()),
   point_reserved=false,updated_at=now() where id=o.id returning * into o;
 if legacy then
  -- Preserve the pre-0032 voucher shape and immutable order economics. The
  -- conflict key makes retries return the same single null-product voucher.
  insert into vouchers(user_id,merchant_id,product_id,order_id,issue_index,purchase_price,
    company_id,company_subsidy_amount,restaurant_subsidy_amount,pg_transaction_id,purchased_at)
  values(o.user_id,o.merchant_id,null,o.id,1,o.voucher_purchase_price,
    o.company_id,o.company_subsidy_amount,o.restaurant_subsidy_amount,
    o.provider_payment_key,coalesce(o.approved_at,now()))
  on conflict(order_id,issue_index) do nothing;
 else
  -- Keep every voucher snapshot in integer KRW while conserving the order burden
  -- exactly. The deterministic lowest paid issue indexes receive the remainder.
  paid_price:=floor(o.total_employee_burden::numeric/o.paid_voucher_count)::int;
  burden_remainder:=o.total_employee_burden-(paid_price*o.paid_voucher_count);
  for i in 1..o.voucher_count loop
   insert into vouchers(user_id,merchant_id,product_id,order_id,issue_index,purchase_price,
     company_id,company_subsidy_amount,restaurant_subsidy_amount,pg_transaction_id,purchased_at)
   values(o.user_id,o.merchant_id,o.voucher_product_id,o.id,i,
     case when i<=o.paid_voucher_count then paid_price+case when i<=burden_remainder then 1 else 0 end else 0 end,
     o.company_id,case when i<=o.paid_voucher_count then o.company_subsidy_amount else 0 end,
     case when i<=o.paid_voucher_count then o.restaurant_subsidy_amount else 0 end,
     o.provider_payment_key,coalesce(o.approved_at,now()))
   on conflict(order_id,issue_index) do nothing;
  end loop;
 end if;
 select * into first_voucher from vouchers where order_id=o.id order by issue_index limit 1;
 if not duplicate and o.point_amount>0 then
  insert into point_transactions(user_id,company_id,type,amount,balance_after,reason,processed_by,related_voucher_id,related_order_id)
  values(o.user_id,o.company_id,'use',-o.point_amount,u.point_balance,'보조금 식권 구매',o.user_id,first_voucher.id,o.id);
 end if;
 return jsonb_build_object('order_id',o.order_id,'status','done','issued_count',o.voucher_count,
   'voucher_id',first_voucher.id,'duplicate',duplicate,'point_amount',o.point_amount,'card_amount',o.amount);
end $$;
revoke all on function fulfill_subsidized_order(uuid,text,text,jsonb,timestamptz) from public,anon,authenticated;
grant execute on function fulfill_subsidized_order(uuid,text,text,jsonb,timestamptz) to service_role;

-- Ordinary voucher scans and refund claims share this exact queue-lock domain.
-- Taking the queue lock before any order/voucher row lock gives strict FIFO and
-- prevents a scan from consuming a voucher while its order is being claimed.
create or replace function consume_voucher(
  p_user_id uuid, p_merchant_id uuid, p_idempotency_key text,
  p_tx_code text default null
) returns jsonb language plpgsql security definer set search_path=public as $$
declare existing meal_transactions%rowtype; v vouchers%rowtype; tx meal_transactions%rowtype;
  candidate_id uuid; candidate_order_id uuid; order_status text; remaining_count int;
begin
 if p_idempotency_key is null or btrim(p_idempotency_key)='' then raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode='P0001'; end if;
 perform pg_advisory_xact_lock(hashtextextended(
   'voucher-refund-queue:'||p_user_id::text||':ordinary:'||p_merchant_id::text,0));
 perform pg_advisory_xact_lock(1,hashtext(p_idempotency_key));
 select * into existing from meal_transactions where idempotency_key=p_idempotency_key limit 1;
 if found then
  if existing.user_id<>p_user_id or existing.merchant_id<>p_merchant_id
     or existing.pay_type<>'voucher' or existing.kind<>'spend' or existing.voucher_id is null
     or (p_tx_code is not null and existing.tx_code is distinct from p_tx_code)
  then raise exception 'IDEMPOTENCY_CONFLICT' using errcode='P0001'; end if;
  select count(*) into remaining_count from vouchers vq join payment_orders o on o.id=vq.order_id
   where vq.user_id=p_user_id and vq.company_id is null and vq.merchant_id=p_merchant_id
     and vq.status='unused' and o.status='done' and o.pay_type='voucher';
  return jsonb_build_object('id',existing.id,'amount',abs(existing.amount),
    'voucher_id',existing.voucher_id,'remaining',remaining_count,'duplicate',true,
    'created_at',existing.created_at);
 end if;
 select vq.id,vq.order_id into candidate_id,candidate_order_id
 from vouchers vq join payment_orders o on o.id=vq.order_id
 where vq.user_id=p_user_id and vq.company_id is null and vq.merchant_id=p_merchant_id
   and vq.status='unused' and o.status='done' and o.pay_type='voucher'
 order by vq.purchased_at,vq.issue_index,vq.id limit 1;
 if not found then raise exception 'NO_VOUCHER' using errcode='P0001'; end if;
 select status into order_status from payment_orders where id=candidate_order_id for update;
 if order_status<>'done' then raise exception 'NO_VOUCHER' using errcode='P0001'; end if;
 select * into v from vouchers where id=candidate_id and status='unused' for update;
 if not found then raise exception 'NO_VOUCHER' using errcode='P0001'; end if;
 update vouchers set status='used',used_at=now() where id=v.id;
 insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,
   flags,idempotency_key,product_name,product_price,pay_type,voucher_id)
 values(p_user_id,null,p_merchant_id,-round(v.purchase_price)::int,'spend',
   coalesce(p_tx_code,upper(substr(replace(gen_random_uuid()::text,'-',''),1,10))),
   '식권',jsonb_build_object('voucher_product_id',v.product_id),p_idempotency_key,
   '식권 사용',round(v.purchase_price)::int,'voucher',v.id) returning * into tx;
 select count(*) into remaining_count from vouchers vq join payment_orders o on o.id=vq.order_id
 where vq.user_id=p_user_id and vq.company_id is null and vq.merchant_id=p_merchant_id
   and vq.status='unused' and o.status='done' and o.pay_type='voucher';
 return jsonb_build_object('id',tx.id,'amount',abs(tx.amount),'voucher_id',v.id,
   'remaining',remaining_count,'duplicate',false,'created_at',tx.created_at);
end $$;
revoke all on function consume_voucher(uuid,uuid,text,text) from public,anon,authenticated;
grant execute on function consume_voucher(uuid,uuid,text,text) to service_role;

-- Contract state still controls whether subsidized scanning is enabled, but all
-- money values come from the purchased voucher snapshot, never today's contract.
create or replace function consume_subsidized_voucher(p_user_id uuid,p_company_id uuid,p_merchant_id uuid,p_idempotency_key text) returns jsonb
language plpgsql security definer set search_path=public as $$
declare existing meal_transactions%rowtype; v vouchers%rowtype; tx meal_transactions%rowtype;
  candidate_id uuid; candidate_order_id uuid; order_status text;
  employee_amount int; total_amount int; remaining_count int;
begin
 if p_idempotency_key is null or btrim(p_idempotency_key)='' then raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode='P0001'; end if;
 -- Serialize the whole FIFO queue, not an individual candidate row. The stable
 -- user/company/merchant key prevents a concurrent scan from skipping the head.
 perform pg_advisory_xact_lock(hashtextextended(
   'voucher-refund-queue:'||p_user_id::text||':'||p_company_id::text||':'||p_merchant_id::text,0));
 perform pg_advisory_xact_lock(1,hashtext(p_idempotency_key));
 select * into existing from meal_transactions where idempotency_key=p_idempotency_key limit 1;
 if found then
  if existing.user_id<>p_user_id or existing.company_id<>p_company_id or existing.merchant_id<>p_merchant_id or existing.pay_type<>'subsidized' then raise exception 'IDEMPOTENCY_CONFLICT' using errcode='P0001'; end if;
  select count(*) into remaining_count from vouchers vq join payment_orders o on o.id=vq.order_id
   where vq.user_id=p_user_id and vq.company_id=p_company_id and vq.merchant_id=p_merchant_id
     and vq.status='unused' and o.status='done';
  return jsonb_build_object('id',existing.id,'amount',abs(existing.amount),'remaining',remaining_count,'duplicate',true,'company_subsidy_amount',existing.company_subsidy_amount);
 end if;
 if not exists(select 1 from merchant_companies where merchant_id=p_merchant_id and company_id=p_company_id and status='active' and subsidy_enabled) then raise exception 'SUBSIDY_NOT_ACTIVE' using errcode='P0001'; end if;
 select vq.id,vq.order_id into candidate_id,candidate_order_id
 from vouchers vq join payment_orders o on o.id=vq.order_id
 where vq.user_id=p_user_id and vq.company_id=p_company_id and vq.merchant_id=p_merchant_id
   and vq.status='unused' and o.status='done'
 order by vq.purchased_at,vq.issue_index,vq.id limit 1;
 if not found then raise exception 'NO_VOUCHER' using errcode='P0001'; end if;
 -- Global lock order is payment_orders -> vouchers. Refund claim/finalize use
 -- the same order, avoiding deadlocks while closing the provider-call window.
 select status into order_status from payment_orders where id=candidate_order_id for update;
 if order_status<>'done' then raise exception 'NO_VOUCHER' using errcode='P0001'; end if;
 select * into v from vouchers where id=candidate_id and status='unused' for update;
 if not found then raise exception 'NO_VOUCHER' using errcode='P0001'; end if;
 if v.purchase_price<>trunc(v.purchase_price) then raise exception 'INVALID_SUBSIDY_SNAPSHOT' using errcode='P0001'; end if;
 employee_amount:=v.purchase_price::int;
 total_amount:=employee_amount+v.company_subsidy_amount+v.restaurant_subsidy_amount;
 if employee_amount<0 then raise exception 'INVALID_SUBSIDY_SNAPSHOT' using errcode='P0001'; end if;
 update vouchers set status='used',used_at=now() where id=v.id;
 insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,flags,idempotency_key,
   product_name,product_price,pay_type,voucher_id,employee_paid_amount,company_subsidy_amount,restaurant_subsidy_amount)
 values(p_user_id,p_company_id,p_merchant_id,-total_amount,'spend',upper(substr(replace(gen_random_uuid()::text,'-',''),1,10)),
   '보조금',jsonb_build_object('subsidized',true),p_idempotency_key,'보조금 식권 사용',total_amount,'subsidized',v.id,
   employee_amount,v.company_subsidy_amount,v.restaurant_subsidy_amount) returning * into tx;
 select count(*) into remaining_count from vouchers vq join payment_orders o on o.id=vq.order_id
 where vq.user_id=p_user_id and vq.company_id=p_company_id and vq.merchant_id=p_merchant_id
   and vq.status='unused' and o.status='done';
 return jsonb_build_object('id',tx.id,'amount',abs(tx.amount),'remaining',remaining_count,'duplicate',false,'voucher_id',v.id,
   'employee_paid_amount',tx.employee_paid_amount,'company_subsidy_amount',tx.company_subsidy_amount,
   'restaurant_subsidy_amount',tx.restaurant_subsidy_amount,'created_at',tx.created_at);
end $$;
revoke all on function consume_subsidized_voucher(uuid,uuid,uuid,text) from public,anon,authenticated;
grant execute on function consume_subsidized_voucher(uuid,uuid,uuid,text) to service_role;

-- Multi-voucher subsidized refunds mirror ordinary package behavior: only unused
-- paid indexes are refundable; unused bonuses are forfeited. Subsidies are never
-- included because the refund is calculated solely from total_employee_burden.
create or replace function claim_purchase_order_refund(
  p_order_id uuid, p_merchant_id uuid, p_user_id uuid,
  p_requested_by uuid, p_refund_account jsonb default null
) returns jsonb language plpgsql security definer set search_path=public as $$
declare o payment_orders%rowtype; r refund_requests%rowtype; v_order payment_orders%rowtype;
  new_token uuid;
  used_count int; used_paid int; paid_remaining int; unused_bonus int; card_refund int; point_refund int;
  already_refunded int; burden_base int; burden_remainder int; refundable_burden int;
begin
 -- Discover the queue identity without a row lock, then serialize consumption
 -- and refunds before following the global order -> request -> voucher order.
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
 -- Lock every voucher only after the order. Consumption uses the same ordering.
 perform 1 from vouchers where order_id=o.id order by issue_index,id for update;
 select count(*) filter(where status='used'),
   count(*) filter(where status='unused' and issue_index<=o.paid_voucher_count),
   count(*) filter(where status='unused' and issue_index>o.paid_voucher_count)
 into used_count,paid_remaining,unused_bonus from vouchers where order_id=o.id;
 if paid_remaining=0 and unused_bonus=0 then raise exception 'PAID_VOUCHERS_EXHAUSTED' using errcode='P0001'; end if;
 select coalesce(sum(refund_amount),0) into already_refunded from refund_requests where order_id=o.id and status='completed';
 if o.pay_type='subsidized' then
  used_paid:=o.paid_voucher_count-paid_remaining;
  -- Paid snapshots are base+1 for the first remainder indexes and base after
  -- that. Since consumption is FIFO, this reconstructs their exact unused sum.
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
  used_paid:=o.paid_voucher_count-paid_remaining;
  card_refund:=least(o.amount-floor(o.amount::numeric*used_paid/o.paid_voucher_count)::int,
    greatest(o.amount-already_refunded,0));
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
revoke all on function claim_purchase_order_refund(uuid,uuid,uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function claim_purchase_order_refund(uuid,uuid,uuid,uuid,jsonb) to service_role;

-- Cross the durable point-of-no-return before making Kiwoom's non-idempotent
-- cancellation request. This state deliberately has no reclaimable lease: a
-- crash after this write must be reconciled against Kiwoom by an operator.
create or replace function mark_purchase_order_refund_provider_attempt_started(
 p_refund_request_id uuid,p_merchant_id uuid,p_processing_token uuid
) returns jsonb language plpgsql security definer set search_path=public as $$
declare r refund_requests%rowtype;
begin
 select * into r from refund_requests where id=p_refund_request_id for update;
 if not found or r.merchant_id<>p_merchant_id then raise exception 'REFUND_NOT_FOUND' using errcode='P0001'; end if;
 if p_processing_token is null or r.processing_token is distinct from p_processing_token then raise exception 'REFUND_LEASE_NOT_OWNED' using errcode='P0001'; end if;
 if r.status='provider_in_flight' then return to_jsonb(r); end if;
 if r.status<>'processing' then raise exception 'REFUND_NOT_PROCESSING' using errcode='P0001'; end if;
 update refund_requests set status='provider_in_flight',lease_expires_at=null,updated_at=now()
 where id=r.id returning * into r;
 return to_jsonb(r);
end $$;
revoke all on function mark_purchase_order_refund_provider_attempt_started(uuid,uuid,uuid) from public,anon,authenticated;
grant execute on function mark_purchase_order_refund_provider_attempt_started(uuid,uuid,uuid) to service_role;

-- Persist a successful provider cancellation before touching vouchers/points.
-- Retried API requests observe this state and skip a duplicate provider call.
create or replace function record_purchase_order_refund_provider_success(
 p_refund_request_id uuid,p_merchant_id uuid,p_processing_token uuid,p_pg_response jsonb
) returns jsonb language plpgsql security definer set search_path=public as $$
declare r refund_requests%rowtype;
begin
 select * into r from refund_requests where id=p_refund_request_id for update;
 if not found or r.merchant_id<>p_merchant_id then raise exception 'REFUND_NOT_FOUND' using errcode='P0001'; end if;
 if p_processing_token is null or r.processing_token is distinct from p_processing_token then raise exception 'REFUND_LEASE_NOT_OWNED' using errcode='P0001'; end if;
 if r.status in ('provider_succeeded','completed') then return to_jsonb(r); end if;
 if r.status<>'provider_in_flight' then raise exception 'REFUND_PROVIDER_ATTEMPT_NOT_STARTED' using errcode='P0001'; end if;
 update refund_requests set status='provider_succeeded',pg_response=p_pg_response,
   provider_succeeded_at=now(),lease_expires_at=null,failure_code=null,failure_message=null,updated_at=now()
 where id=r.id returning * into r;
 return to_jsonb(r);
end $$;
revoke all on function record_purchase_order_refund_provider_success(uuid,uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function record_purchase_order_refund_provider_success(uuid,uuid,uuid,jsonb) to service_role;

-- Kiwoom has no cancellation status lookup or idempotency key. If the actual
-- cancel POST has an ambiguous outcome, freeze the refund for manual Kiwoom
-- transaction reconciliation. The order deliberately remains refund_processing,
-- so vouchers and points remain blocked and no caller can retry the provider.
create or replace function mark_purchase_order_refund_reconciliation_required(
 p_refund_request_id uuid,p_merchant_id uuid,p_processing_token uuid,
 p_failure_code text,p_failure_message text,p_reconciliation_details jsonb default null
) returns jsonb language plpgsql security definer set search_path=public as $$
declare r refund_requests%rowtype;
begin
 select * into r from refund_requests where id=p_refund_request_id for update;
 if not found or r.merchant_id<>p_merchant_id then raise exception 'REFUND_NOT_FOUND' using errcode='P0001'; end if;
 if p_processing_token is null or r.processing_token is distinct from p_processing_token then raise exception 'REFUND_LEASE_NOT_OWNED' using errcode='P0001'; end if;
 if r.status='reconciliation_required' then return to_jsonb(r); end if;
 if r.status<>'provider_in_flight' then raise exception 'REFUND_PROVIDER_ATTEMPT_NOT_STARTED' using errcode='P0001'; end if;
 update refund_requests set status='reconciliation_required',failure_code=p_failure_code,
   failure_message=p_failure_message,reconciliation_details=p_reconciliation_details,
   processing_token=null,lease_expires_at=null,updated_at=now()
 where id=r.id returning * into r;
 return to_jsonb(r);
end $$;
revoke all on function mark_purchase_order_refund_reconciliation_required(uuid,uuid,uuid,text,text,jsonb) from public,anon,authenticated;
grant execute on function mark_purchase_order_refund_reconciliation_required(uuid,uuid,uuid,text,text,jsonb) to service_role;

-- Provider rejection is safe to release: no money moved. Restore both durable
-- states atomically so a later request can make a fresh claim.
create or replace function fail_purchase_order_refund(
 p_refund_request_id uuid,p_merchant_id uuid,p_processing_token uuid,p_failure_code text,p_failure_message text
) returns jsonb language plpgsql security definer set search_path=public as $$
declare r refund_requests%rowtype; o payment_orders%rowtype; v_order_id uuid;
begin
 select order_id into v_order_id from refund_requests where id=p_refund_request_id and merchant_id=p_merchant_id;
 if not found then raise exception 'REFUND_NOT_FOUND' using errcode='P0001'; end if;
 select * into o from payment_orders where id=v_order_id for update;
 select * into r from refund_requests where id=p_refund_request_id for update;
 if p_processing_token is null or r.processing_token is distinct from p_processing_token then raise exception 'REFUND_LEASE_NOT_OWNED' using errcode='P0001'; end if;
 if r.status<>'provider_in_flight' then return to_jsonb(r); end if;
 update refund_requests set status='failed',failure_code=p_failure_code,
   failure_message=p_failure_message,lease_expires_at=null,updated_at=now() where id=r.id returning * into r;
 update payment_orders set status='done',updated_at=now() where id=o.id and status='refund_processing';
 return to_jsonb(r);
end $$;
revoke all on function fail_purchase_order_refund(uuid,uuid,uuid,text,text) from public,anon,authenticated;
grant execute on function fail_purchase_order_refund(uuid,uuid,uuid,text,text) to service_role;

create or replace function finalize_purchase_order_refund(
  p_refund_request_id uuid, p_merchant_id uuid, p_pg_response jsonb default null
) returns jsonb language plpgsql security definer set search_path=public as $$
declare r refund_requests%rowtype; o payment_orders%rowtype; u app_users%rowtype;
begin
 -- Read identity without a lock, then follow global order -> request -> voucher.
 select * into r from refund_requests where id=p_refund_request_id;
 if not found or r.merchant_id<>p_merchant_id then raise exception 'REFUND_NOT_FOUND' using errcode='P0001'; end if;
 select * into o from payment_orders where id=r.order_id for update;
 select * into r from refund_requests where id=p_refund_request_id for update;
 if r.status='completed' then return to_jsonb(r); end if;
 if r.status<>'provider_succeeded' then raise exception 'PROVIDER_REFUND_NOT_SUCCEEDED' using errcode='P0001'; end if;
 if o.status<>'refund_processing' then raise exception 'ORDER_NOT_REFUND_PROCESSING' using errcode='P0001'; end if;
 update vouchers set status='refunded' where id in (
   select id from vouchers where order_id=o.id and status='unused' and issue_index<=o.paid_voucher_count
   order by issue_index limit r.refunded_voucher_count);
 update vouchers set status='forfeited' where order_id=o.id and status='unused' and issue_index>o.paid_voucher_count;
 if r.point_amount>0 then
  select * into u from app_users where id=o.user_id for update;
  update app_users set point_balance=point_balance+r.point_amount where id=u.id returning * into u;
  insert into point_transactions(user_id,company_id,type,amount,balance_after,reason,processed_by,related_order_id)
  values(o.user_id,o.company_id,'refund',r.point_amount,u.point_balance,'보조금 식권 환불',r.requested_by,o.id);
 end if;
 update refund_requests set status='completed',pg_response=coalesce(pg_response,p_pg_response),completed_at=now(),updated_at=now() where id=r.id returning * into r;
 update payment_orders set status='refunded',updated_at=now() where id=o.id;
 return jsonb_build_object('refund_request_id',r.id,'status','completed','refund_amount',r.refund_amount,
   'point_amount',r.point_amount,'refunded_voucher_count',r.refunded_voucher_count,
   'forfeited_voucher_count',r.forfeited_voucher_count);
end $$;
revoke all on function finalize_purchase_order_refund(uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function finalize_purchase_order_refund(uuid,uuid,jsonb) to service_role;
