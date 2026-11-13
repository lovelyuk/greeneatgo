begin;

-- 0075: process_meal_pay re-validates the payer and the daily/monthly limits
-- inside the transaction, after the per-user advisory lock (audit M-1). Before,
-- the API computed usage and compared limits without a lock, so N concurrent
-- payments with different idempotency keys could all pass. Same rules as
-- services/api/app/routers/pay.py (KST day/month, normal_meal_transactions spend,
-- app_users.monthly_limit, company-wide meal_policies.daily_limit). Otherwise
-- identical to 0062.

create or replace function public.process_meal_pay(p_user_id uuid,p_company_id uuid,p_merchant_id uuid,p_amount int,p_tx_code text,
 p_meal_window text,p_flags jsonb,p_idempotency_key text,p_product_id uuid default null,p_product_name text default null,p_product_price int default null)
returns jsonb language plpgsql security definer set search_path=public as $$
declare existing meal_transactions%rowtype; company_status text; contract merchant_companies%rowtype; tx meal_transactions%rowtype; s record;
 batch merchant_company_prepurchase_batches%rowtype; remaining_total bigint; consumed_batch_id uuid;
 tx_flags jsonb; settlement_supply int; settlement_vat int; settlement_total int;
 actor app_users%rowtype; day_start timestamptz; month_start timestamptz; spent_month bigint; spent_day bigint; day_limit int;
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
  select c.batch_id into consumed_batch_id from merchant_company_prepurchase_consumptions c where c.meal_transaction_id=existing.id;
  if consumed_batch_id is not null then
   select coalesce(sum(remaining_quantity),0) into remaining_total from merchant_company_prepurchase_batches
    where merchant_id=p_merchant_id and company_id=p_company_id;
  end if;
  return jsonb_build_object('id',existing.id,'tx_code',existing.tx_code,'amount',existing.total_amount,'duplicate',true,'created_at',existing.created_at,
   'product_id',existing.product_id,'product_name',existing.product_name,'product_price',existing.product_price,'pay_type','ledger','tax_type',existing.tax_type,
   'supply_amount',existing.supply_amount,'vat_amount',existing.vat_amount,'total_amount',existing.total_amount,
   'settlement_tax_type',existing.settlement_tax_type,'settlement_supply_amount',existing.settlement_supply_amount,
   'settlement_vat_amount',existing.settlement_vat_amount,'settlement_total_amount',existing.settlement_total_amount,
   'prepurchase_batch_id',consumed_batch_id,'prepurchase_remaining',remaining_total);
 end if;
 perform pg_advisory_xact_lock(2,hashtext(p_user_id::text));
 -- 0075: membership and limits are re-checked under the per-user lock, so
 -- concurrent requests cannot all pass the API's pre-check (audit M-1).
 select * into actor from app_users where id=p_user_id;
 if not found or actor.company_id is distinct from p_company_id or actor.status is distinct from 'active' or actor.role<>'employee'
 then raise exception 'NOT_COMPANY_MEMBER' using errcode='P0001'; end if;
 day_start:=(date_trunc('day',now() at time zone 'Asia/Seoul')) at time zone 'Asia/Seoul';
 month_start:=(date_trunc('month',now() at time zone 'Asia/Seoul')) at time zone 'Asia/Seoul';
 select coalesce(sum(abs(amount)) filter (where created_at>=month_start),0),coalesce(sum(abs(amount)) filter (where created_at>=day_start),0)
   into spent_month,spent_day from normal_meal_transactions where user_id=p_user_id and kind='spend' and created_at>=least(month_start,day_start);
 if spent_month+p_amount>coalesce(actor.monthly_limit,200000) then raise exception 'MONTHLY_LIMIT' using errcode='P0001'; end if;
 select daily_limit into day_limit from meal_policies where company_id=p_company_id and group_id is null limit 1;
 if day_limit is not null and spent_day+p_amount>day_limit then raise exception 'DAILY_LIMIT' using errcode='P0001'; end if;
 select status into company_status from companies where id=p_company_id for share;
 if company_status is distinct from 'active' then raise exception 'COMPANY_NOT_ACTIVE' using errcode='P0001'; end if;
 select * into contract from merchant_companies where merchant_id=p_merchant_id and company_id=p_company_id and status='active' for update;
 if not found then raise exception 'NOT_AFFILIATED' using errcode='P0001'; end if;
 if contract.unit_price is null or contract.unit_price<=0 then raise exception 'PRICE_NOT_CONFIGURED' using errcode='P0001'; end if;
 if p_amount<>contract.unit_price then raise exception 'CONTRACT_PRICE_MISMATCH' using errcode='P0001'; end if;
 if contract.tax_type='unclassified' then raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode='P0001'; end if;
 if contract.prepurchase_enabled then
  select * into batch from merchant_company_prepurchase_batches
   where merchant_id=p_merchant_id and company_id=p_company_id and remaining_quantity>0
   order by purchased_at,id limit 1 for update;
  if not found then raise exception 'PREPURCHASE_INVENTORY_EMPTY' using errcode='P0001'; end if;
  update merchant_company_prepurchase_batches set remaining_quantity=remaining_quantity-1
   where id=batch.id and remaining_quantity>0 returning * into batch;
  if not found then raise exception 'PREPURCHASE_INVENTORY_EMPTY' using errcode='P0001'; end if;
  consumed_batch_id:=batch.id;
 end if;
 select * into s from split_tax_inclusive(p_amount,contract.tax_type);
 tx_flags:=coalesce(p_flags,'{}'::jsonb);
 settlement_supply:=s.supply_amount; settlement_vat:=s.vat_amount; settlement_total:=s.total_amount;
 if consumed_batch_id is not null then
  tx_flags:=tx_flags||jsonb_build_object('prepurchase',true,'prepurchase_batch_id',consumed_batch_id);
  settlement_supply:=0; settlement_vat:=0; settlement_total:=0;
 end if;
 insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,flags,idempotency_key,product_id,product_name,product_price,pay_type,
  tax_type,supply_amount,vat_amount,total_amount,settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount)
 values(p_user_id,p_company_id,p_merchant_id,-p_amount,'spend',p_tx_code,p_meal_window,tx_flags,p_idempotency_key,p_product_id,p_product_name,
  p_product_price,'ledger',contract.tax_type,s.supply_amount,s.vat_amount,s.total_amount,contract.tax_type,settlement_supply,settlement_vat,settlement_total) returning * into tx;
 if consumed_batch_id is not null then
  insert into merchant_company_prepurchase_consumptions(batch_id,meal_transaction_id) values(consumed_batch_id,tx.id);
  select coalesce(sum(remaining_quantity),0) into remaining_total from merchant_company_prepurchase_batches
   where merchant_id=p_merchant_id and company_id=p_company_id;
 end if;
 return jsonb_build_object('id',tx.id,'tx_code',tx.tx_code,'amount',tx.total_amount,'duplicate',false,'created_at',tx.created_at,'product_id',tx.product_id,
  'product_name',tx.product_name,'product_price',tx.product_price,'pay_type','ledger','tax_type',tx.tax_type,'supply_amount',tx.supply_amount,'vat_amount',tx.vat_amount,
  'total_amount',tx.total_amount,'settlement_tax_type',tx.settlement_tax_type,'settlement_supply_amount',tx.settlement_supply_amount,
  'settlement_vat_amount',tx.settlement_vat_amount,'settlement_total_amount',tx.settlement_total_amount,
  'prepurchase_batch_id',consumed_batch_id,'prepurchase_remaining',remaining_total);
end $$;

revoke all on function public.process_meal_pay(uuid,uuid,uuid,int,text,text,jsonb,text,uuid,text,int) from public,anon,authenticated;
grant execute on function public.process_meal_pay(uuid,uuid,uuid,int,text,text,jsonb,text,uuid,text,int) to service_role;

commit;
