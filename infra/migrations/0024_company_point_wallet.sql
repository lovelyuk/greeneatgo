-- Direct company-admin employee point wallet and mixed point/card subsidized checkout.
-- Apply after 0023_subsidized_ledger.sql.
alter table app_users
  add column if not exists point_balance bigint not null default 0,
  add column if not exists point_reserved bigint not null default 0;
alter table app_users drop constraint if exists app_users_point_balance_check;
alter table app_users add constraint app_users_point_balance_check check (point_balance >= 0 and point_reserved >= 0 and point_reserved <= point_balance);

create table if not exists point_transactions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references app_users(id),
  company_id uuid not null references companies(id),
  type text not null check (type in ('charge','use','adjust')),
  amount bigint not null check (amount <> 0),
  balance_after bigint not null check (balance_after >= 0),
  reason text not null check (length(btrim(reason)) > 0),
  processed_by uuid references app_users(id),
  related_voucher_id uuid references vouchers(id),
  related_order_id uuid references toss_payment_orders(id),
  created_at timestamptz not null default now()
);
create index if not exists idx_point_transactions_user_created on point_transactions(user_id,created_at desc);
create index if not exists idx_point_transactions_company_created on point_transactions(company_id,created_at desc);

-- Audit rows are append-only, including to service clients.
create or replace function reject_point_transaction_mutation() returns trigger language plpgsql as $$ begin raise exception 'POINT_TRANSACTION_IMMUTABLE' using errcode='P0001'; end $$;
drop trigger if exists point_transactions_immutable on point_transactions;
create trigger point_transactions_immutable before update or delete on point_transactions for each row execute function reject_point_transaction_mutation();

alter table toss_payment_orders
  add column if not exists point_amount bigint not null default 0,
  add column if not exists point_reserved boolean not null default false;
alter table toss_payment_orders drop constraint if exists toss_payment_orders_voucher_columns_check;
alter table toss_payment_orders add constraint toss_payment_orders_voucher_columns_check check (
  (pay_type='direct' and voucher_product_id is null and voucher_count is null and voucher_purchase_price is null and fulfilled_at is null and company_id is null and point_amount=0)
  or (pay_type='voucher' and product_id is null and voucher_product_id is not null and voucher_count>0 and voucher_purchase_price>0 and amount>0 and company_id is null and point_amount=0 and voucher_purchase_price=round(amount::numeric/voucher_count,4))
  or (pay_type='subsidized' and product_id is null and voucher_product_id is null and voucher_count=1 and voucher_purchase_price>0 and amount>=0 and company_id is not null and company_subsidy_amount>=0 and restaurant_subsidy_amount>=0 and point_amount>=0 and amount+point_amount=round(voucher_purchase_price)::bigint)
);

create or replace function company_admin_change_points(p_admin_id uuid,p_employee_id uuid,p_mode text,p_value bigint,p_reason text,p_confirmed boolean default false) returns jsonb
language plpgsql security definer set search_path=public as $$
declare a app_users%rowtype; e app_users%rowtype; delta bigint; tx point_transactions%rowtype;
begin
 select * into a from app_users where id=p_admin_id and role='company_admin' and status='active';
 if not found or a.company_id is null then raise exception 'FORBIDDEN' using errcode='P0001'; end if;
 select * into e from app_users where id=p_employee_id and company_id=a.company_id and role='employee' for update;
 if not found then raise exception 'EMPLOYEE_NOT_FOUND' using errcode='P0001'; end if;
 if p_reason is null or length(btrim(p_reason))=0 then raise exception 'REASON_REQUIRED' using errcode='P0001'; end if;
 if p_mode='charge' then
  if not p_confirmed then raise exception 'WELFARE_DEDUCTION_CONFIRMATION_REQUIRED' using errcode='P0001'; end if;
  if p_value<=0 then raise exception 'INVALID_AMOUNT' using errcode='P0001'; end if; delta:=p_value;
 elsif p_mode='adjust' then
  if p_value<0 or p_value<e.point_reserved then raise exception 'INVALID_TARGET_BALANCE' using errcode='P0001'; end if; delta:=p_value-e.point_balance;
  if delta=0 then raise exception 'NO_CHANGE' using errcode='P0001'; end if;
 else raise exception 'INVALID_POINT_MODE' using errcode='P0001'; end if;
 update app_users set point_balance=point_balance+delta where id=e.id returning * into e;
 insert into point_transactions(user_id,company_id,type,amount,balance_after,reason,processed_by)
 values(e.id,e.company_id,case when p_mode='charge' then 'charge' else 'adjust' end,delta,e.point_balance,btrim(p_reason),a.id) returning * into tx;
 return jsonb_build_object('employee_id',e.id,'point_balance',e.point_balance,'transaction',to_jsonb(tx));
end $$;
revoke all on function company_admin_change_points(uuid,uuid,text,bigint,text,boolean) from public,anon,authenticated;
grant execute on function company_admin_change_points(uuid,uuid,text,bigint,text,boolean) to service_role;

-- Locks the employee row and reserves the best available point amount for this exact order.
create or replace function reserve_subsidized_order_points(p_order_id uuid) returns jsonb
language plpgsql security definer set search_path=public as $$
declare o toss_payment_orders%rowtype; u app_users%rowtype; employee_due bigint; points bigint;
begin
 select * into o from toss_payment_orders where id=p_order_id for update;
 if not found or o.pay_type<>'subsidized' or o.status<>'ready' then raise exception 'ORDER_NOT_RESERVABLE' using errcode='P0001'; end if;
 if o.point_reserved then return jsonb_build_object('point_amount',o.point_amount,'card_amount',o.amount,'duplicate',true); end if;
 select * into u from app_users where id=o.user_id and role='employee' and company_id=o.company_id for update;
 if not found then raise exception 'EMPLOYEE_NOT_FOUND' using errcode='P0001'; end if;
 employee_due:=round(o.voucher_purchase_price)::bigint;
 points:=least(employee_due,u.point_balance-u.point_reserved);
 update app_users set point_reserved=point_reserved+points where id=u.id;
 update toss_payment_orders set point_amount=points,point_reserved=(points>0),amount=employee_due-points,updated_at=now() where id=o.id returning * into o;
 return jsonb_build_object('point_amount',points,'card_amount',o.amount,'duplicate',false);
end $$;
revoke all on function reserve_subsidized_order_points(uuid) from public,anon,authenticated;
grant execute on function reserve_subsidized_order_points(uuid) to service_role;

create or replace function release_subsidized_order_points(p_order_id uuid,p_user_id uuid) returns jsonb
language plpgsql security definer set search_path=public as $$
declare o toss_payment_orders%rowtype; u app_users%rowtype;
begin
 select * into o from toss_payment_orders where id=p_order_id and user_id=p_user_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND' using errcode='P0001'; end if;
 if o.status='done' then return jsonb_build_object('released',false,'done',true); end if;
 select * into u from app_users where id=o.user_id for update;
 if o.point_reserved and o.point_amount>0 then update app_users set point_reserved=greatest(point_reserved-o.point_amount,0) where id=u.id; end if;
 update toss_payment_orders set point_reserved=false,status='canceled',updated_at=now() where id=o.id;
 return jsonb_build_object('released',true,'point_amount',o.point_amount);
end $$;
revoke all on function release_subsidized_order_points(uuid,uuid) from public,anon,authenticated;
grant execute on function release_subsidized_order_points(uuid,uuid) to service_role;

-- Handles both point-only (no payment key) and verified mixed Toss fulfillment atomically/idempotently.
create or replace function fulfill_subsidized_order(p_order_id uuid,p_payment_key text,p_payment_method text,p_toss_response jsonb,p_approved_at timestamptz) returns jsonb
language plpgsql security definer set search_path=public as $$
declare o toss_payment_orders%rowtype; v vouchers%rowtype; u app_users%rowtype; duplicate boolean; employee_due bigint;
begin
 select * into o from toss_payment_orders where id=p_order_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND' using errcode='P0001'; end if;
 if o.pay_type<>'subsidized' or o.company_id is null or o.voucher_count<>1 then raise exception 'NOT_SUBSIDIZED_ORDER' using errcode='P0001'; end if;
 if o.amount>0 and (p_payment_key is null or btrim(p_payment_key)='') then raise exception 'PAYMENT_KEY_REQUIRED' using errcode='P0001'; end if;
 if o.amount=0 and p_payment_key is not null then raise exception 'POINT_ONLY_PAYMENT_KEY_FORBIDDEN' using errcode='P0001'; end if;
 if o.status not in ('ready','done') then raise exception 'ORDER_NOT_FULFILLABLE' using errcode='P0001'; end if;
 if o.payment_key is not null and o.payment_key<>p_payment_key then raise exception 'PAYMENT_KEY_MISMATCH' using errcode='P0001'; end if;
 duplicate:=o.fulfilled_at is not null;
 if not duplicate and o.point_amount>0 then
  select * into u from app_users where id=o.user_id for update;
  if not o.point_reserved or u.point_reserved<o.point_amount or u.point_balance<o.point_amount then raise exception 'POINT_RESERVATION_CONFLICT' using errcode='P0001'; end if;
  update app_users set point_balance=point_balance-o.point_amount,point_reserved=point_reserved-o.point_amount where id=u.id returning * into u;
 end if;
 update toss_payment_orders set status='done',payment_key=coalesce(payment_key,p_payment_key),payment_method=coalesce(p_payment_method,payment_method),toss_response=coalesce(p_toss_response,toss_response),approved_at=coalesce(approved_at,p_approved_at,now()),fulfilled_at=coalesce(fulfilled_at,now()),point_reserved=false,updated_at=now() where id=o.id returning * into o;
 employee_due:=round(o.voucher_purchase_price)::bigint;
 insert into vouchers(user_id,merchant_id,product_id,order_id,issue_index,purchase_price,company_id,company_subsidy_amount,pg_transaction_id,purchased_at)
 values(o.user_id,o.merchant_id,null,o.id,1,employee_due,o.company_id,o.company_subsidy_amount,o.payment_key,coalesce(o.approved_at,now())) on conflict(order_id,issue_index) do nothing;
 select * into v from vouchers where order_id=o.id and issue_index=1;
 if not duplicate and o.point_amount>0 then
  insert into point_transactions(user_id,company_id,type,amount,balance_after,reason,processed_by,related_voucher_id,related_order_id)
  values(o.user_id,o.company_id,'use',-o.point_amount,u.point_balance,'보조금 식권 구매',o.user_id,v.id,o.id);
 end if;
 return jsonb_build_object('order_id',o.order_id,'status','done','issued_count',1,'voucher_id',v.id,'duplicate',duplicate,'point_amount',o.point_amount,'card_amount',o.amount);
end $$;
revoke all on function fulfill_subsidized_order(uuid,text,text,jsonb,timestamptz) from public,anon,authenticated;
grant execute on function fulfill_subsidized_order(uuid,text,text,jsonb,timestamptz) to service_role;
