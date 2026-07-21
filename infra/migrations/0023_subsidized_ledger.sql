-- Subsidized ledger vouchers: contract pricing, atomic KiwoomPay fulfillment/consumption, settlement.
-- Apply after 0022_push_notifications.sql.

alter table merchant_companies
  add column if not exists subsidy_enabled boolean not null default false,
  add column if not exists company_subsidy_amount int not null default 0,
  add column if not exists restaurant_subsidy_amount int not null default 0;
alter table merchant_companies drop constraint if exists merchant_companies_subsidy_amounts_check;
alter table merchant_companies add constraint merchant_companies_subsidy_amounts_check check (
  company_subsidy_amount >= 0 and restaurant_subsidy_amount >= 0 and
  (not subsidy_enabled or (unit_price is not null and unit_price > 0 and
    company_subsidy_amount + restaurant_subsidy_amount < unit_price))
);

alter table payment_orders
  add column if not exists company_id uuid references companies(id),
  add column if not exists company_subsidy_amount int,
  add column if not exists restaurant_subsidy_amount int;
alter table payment_orders drop constraint if exists payment_orders_pay_type_check;
alter table payment_orders add constraint payment_orders_pay_type_check
  check (pay_type in ('direct','voucher','subsidized'));
alter table payment_orders drop constraint if exists payment_orders_voucher_columns_check;
alter table payment_orders add constraint payment_orders_voucher_columns_check check (
  (pay_type = 'direct' and voucher_product_id is null and voucher_count is null and voucher_purchase_price is null and fulfilled_at is null and company_id is null)
  or (pay_type = 'voucher' and product_id is null and voucher_product_id is not null and voucher_count > 0 and voucher_purchase_price > 0 and amount > 0 and company_id is null and voucher_purchase_price = round(amount::numeric / voucher_count, 4))
  or (pay_type = 'subsidized' and product_id is null and voucher_product_id is null and voucher_count = 1 and voucher_purchase_price = amount and amount > 0 and company_id is not null and company_subsidy_amount >= 0 and restaurant_subsidy_amount >= 0)
);

alter table vouchers alter column product_id drop not null;
alter table vouchers
  add column if not exists company_id uuid references companies(id),
  add column if not exists company_subsidy_amount int;
alter table vouchers drop constraint if exists vouchers_subsidized_columns_check;
alter table vouchers add constraint vouchers_subsidized_columns_check check (
  (company_id is null and company_subsidy_amount is null and product_id is not null)
  or (company_id is not null and company_subsidy_amount >= 0 and product_id is null)
);
create index if not exists idx_vouchers_subsidized_fifo on vouchers(user_id, company_id, merchant_id, purchased_at, id) where status='unused' and company_id is not null;

alter table meal_transactions
  add column if not exists employee_paid_amount int,
  add column if not exists company_subsidy_amount int,
  add column if not exists restaurant_subsidy_amount int;
alter table meal_transactions drop constraint if exists meal_transactions_pay_type_check;
alter table meal_transactions add constraint meal_transactions_pay_type_check check (pay_type in ('ledger','voucher','subsidized'));
alter table meal_transactions drop constraint if exists meal_transactions_payment_columns_check;
alter table meal_transactions add constraint meal_transactions_payment_columns_check check (
  (pay_type='ledger' and company_id is not null and voucher_id is null)
  or (pay_type='voucher' and company_id is null and voucher_id is not null)
  or (pay_type='subsidized' and company_id is not null and voucher_id is not null and employee_paid_amount >= 0 and company_subsidy_amount >= 0 and restaurant_subsidy_amount >= 0 and employee_paid_amount + company_subsidy_amount + restaurant_subsidy_amount = abs(amount))
);

create or replace function fulfill_subsidized_order(p_order_id uuid,p_provider_payment_key text,p_payment_method text,p_provider_response jsonb,p_approved_at timestamptz) returns jsonb
language plpgsql security definer set search_path=public as $$
declare v_order payment_orders%rowtype; v_voucher vouchers%rowtype; v_duplicate boolean;
begin
 select * into v_order from payment_orders where id=p_order_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND' using errcode='P0001'; end if;
 if v_order.pay_type <> 'subsidized' or v_order.company_id is null or v_order.voucher_count <> 1 or v_order.amount <> v_order.voucher_purchase_price then raise exception 'NOT_SUBSIDIZED_ORDER' using errcode='P0001'; end if;
 if p_provider_payment_key is null or btrim(p_provider_payment_key)='' then raise exception 'PAYMENT_KEY_REQUIRED' using errcode='P0001'; end if;
 if v_order.status not in ('ready','done') then raise exception 'ORDER_NOT_FULFILLABLE' using errcode='P0001'; end if;
 if v_order.provider_payment_key is not null and v_order.provider_payment_key <> p_provider_payment_key then raise exception 'PAYMENT_KEY_MISMATCH' using errcode='P0001'; end if;
 v_duplicate := v_order.fulfilled_at is not null;
 update payment_orders set status='done',provider_payment_key=coalesce(provider_payment_key,p_provider_payment_key),payment_method=coalesce(p_payment_method,payment_method),provider_response=coalesce(p_provider_response,provider_response),approved_at=coalesce(approved_at,p_approved_at,now()),fulfilled_at=coalesce(fulfilled_at,now()),updated_at=now() where id=p_order_id returning * into v_order;
 insert into vouchers(user_id,merchant_id,product_id,order_id,issue_index,purchase_price,company_id,company_subsidy_amount,pg_transaction_id,purchased_at)
 values(v_order.user_id,v_order.merchant_id,null,v_order.id,1,v_order.amount,v_order.company_id,v_order.company_subsidy_amount,v_order.provider_payment_key,coalesce(v_order.approved_at,now())) on conflict(order_id,issue_index) do nothing;
 select * into v_voucher from vouchers where order_id=v_order.id and issue_index=1;
 return jsonb_build_object('order_id',v_order.order_id,'status','done','issued_count',1,'voucher_id',v_voucher.id,'duplicate',v_duplicate);
end $$;
revoke all on function fulfill_subsidized_order(uuid,text,text,jsonb,timestamptz) from public,anon,authenticated;
grant execute on function fulfill_subsidized_order(uuid,text,text,jsonb,timestamptz) to service_role;

create or replace function consume_subsidized_voucher(p_user_id uuid,p_company_id uuid,p_merchant_id uuid,p_idempotency_key text) returns jsonb
language plpgsql security definer set search_path=public as $$
declare v_existing meal_transactions%rowtype; v_voucher vouchers%rowtype; v_tx meal_transactions%rowtype; v_contract merchant_companies%rowtype; v_restaurant int; v_remaining int;
begin
 if p_idempotency_key is null or btrim(p_idempotency_key)='' then raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode='P0001'; end if;
 perform pg_advisory_xact_lock(1,hashtext(p_idempotency_key));
 select * into v_existing from meal_transactions where idempotency_key=p_idempotency_key limit 1;
 if found then
  if v_existing.user_id<>p_user_id or v_existing.company_id<>p_company_id or v_existing.merchant_id<>p_merchant_id or v_existing.pay_type<>'subsidized' then raise exception 'IDEMPOTENCY_CONFLICT' using errcode='P0001'; end if;
  select count(*) into v_remaining from vouchers where user_id=p_user_id and company_id=p_company_id and merchant_id=p_merchant_id and status='unused';
  return jsonb_build_object('id',v_existing.id,'amount',abs(v_existing.amount),'remaining',v_remaining,'duplicate',true,'company_subsidy_amount',v_existing.company_subsidy_amount);
 end if;
 select * into v_contract from merchant_companies where merchant_id=p_merchant_id and company_id=p_company_id and status='active' and subsidy_enabled for share;
 if not found then raise exception 'SUBSIDY_NOT_ACTIVE' using errcode='P0001'; end if;
 select * into v_voucher from vouchers where user_id=p_user_id and company_id=p_company_id and merchant_id=p_merchant_id and status='unused' order by purchased_at,id for update skip locked limit 1;
 if not found then raise exception 'NO_VOUCHER' using errcode='P0001'; end if;
 v_restaurant := v_contract.unit_price-round(v_voucher.purchase_price)::int-v_voucher.company_subsidy_amount;
 if v_restaurant < 0 then raise exception 'INVALID_SUBSIDY_SNAPSHOT' using errcode='P0001'; end if;
 update vouchers set status='used',used_at=now() where id=v_voucher.id;
 insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,flags,idempotency_key,product_name,product_price,pay_type,voucher_id,employee_paid_amount,company_subsidy_amount,restaurant_subsidy_amount)
 values(p_user_id,p_company_id,p_merchant_id,-v_contract.unit_price,'spend',upper(substr(replace(gen_random_uuid()::text,'-',''),1,10)),'보조금',jsonb_build_object('subsidized',true),p_idempotency_key,'보조금 식권 사용',v_contract.unit_price,'subsidized',v_voucher.id,round(v_voucher.purchase_price)::int,v_voucher.company_subsidy_amount,v_restaurant) returning * into v_tx;
 select count(*) into v_remaining from vouchers where user_id=p_user_id and company_id=p_company_id and merchant_id=p_merchant_id and status='unused';
 return jsonb_build_object('id',v_tx.id,'amount',abs(v_tx.amount),'remaining',v_remaining,'duplicate',false,'voucher_id',v_voucher.id,'employee_paid_amount',v_tx.employee_paid_amount,'company_subsidy_amount',v_tx.company_subsidy_amount,'restaurant_subsidy_amount',v_tx.restaurant_subsidy_amount,'created_at',v_tx.created_at);
end $$;
revoke all on function consume_subsidized_voucher(uuid,uuid,uuid,text) from public,anon,authenticated;
grant execute on function consume_subsidized_voucher(uuid,uuid,uuid,text) to service_role;

create or replace function merchant_ledger_summary(p_merchant_id uuid,p_company_id uuid,p_period_from date,p_period_to date) returns jsonb
language plpgsql stable security definer set search_path=public as $$ declare v_result jsonb; begin
 if p_period_from is null or p_period_to is null or p_period_from>p_period_to then raise exception 'INVALID_DATE_RANGE' using errcode='P0001'; end if;
 select jsonb_build_object('total_amount',coalesce(sum(case when kind='spend' then case when pay_type='subsidized' then company_subsidy_amount else abs(amount) end when kind in ('refund','cancel') then -(case when pay_type='subsidized' then company_subsidy_amount else abs(amount) end) else 0 end),0),'total_count',count(*),'cancel_count',count(*) filter(where kind in ('refund','cancel')),'restaurant_subsidy_amount',coalesce(sum(case when kind='spend' and pay_type='subsidized' then restaurant_subsidy_amount when kind in ('refund','cancel') and pay_type='subsidized' then -restaurant_subsidy_amount else 0 end),0)) into v_result from meal_transactions where merchant_id=p_merchant_id and company_id=p_company_id and pay_type in ('ledger','subsidized') and created_at >= (p_period_from::timestamp at time zone 'Asia/Seoul') and created_at < ((p_period_to+1)::timestamp at time zone 'Asia/Seoul'); return v_result; end $$;

create or replace function merchant_transaction_count(p_merchant_id uuid) returns bigint language sql stable security definer set search_path=public as $$ select count(*) from meal_transactions where merchant_id=p_merchant_id and pay_type in ('ledger','voucher','subsidized') $$;
