begin;

-- 0079: the restaurant corrects a disputed settlement by cancelling single meals.
--
-- 1) merchant_cancel_settlement_transaction: while a settlement is being
--    prepared or revised (draft / revising, no tax invoice requested) the
--    restaurant cancels one company-ledger meal in it. The original row is kept;
--    a 'cancel' row pointing at it (original_transaction_id) is inserted with the
--    original's timestamp, so it lands in the same settlement period. The
--    existing after-insert trigger then recalculates the settlement, and the
--    existing prepurchase triggers give a prepaid meal back.
-- 2) process_meal_pay: a cancelled meal no longer counts toward the employee's
--    monthly/daily limit. Only the limit sum changes; otherwise identical to 0077.

create or replace function public.merchant_cancel_settlement_transaction(
  p_actor_id uuid, p_merchant_id uuid, p_settlement_id uuid, p_transaction_id bigint, p_reason text
) returns jsonb
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  s public.settlements%rowtype;
  t public.meal_transactions%rowtype;
  c public.meal_transactions%rowtype;
  v_reason text := nullif(pg_catalog.btrim(p_reason), '');
  v_now timestamptz := pg_catalog.clock_timestamp();
  v_day date;
begin
  if not exists (
    select 1 from public.app_users u
    where u.id=p_actor_id and u.merchant_id=p_merchant_id
      and u.role='merchant_admin' and u.status='active'
  ) then
    raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001';
  end if;
  if v_reason is null or char_length(v_reason) > 300 or p_transaction_id is null then
    raise exception 'SETTLEMENT_INPUT_INVALID' using errcode='P0001';
  end if;

  select * into s from public.settlements
   where id=p_settlement_id and merchant_id=p_merchant_id and not is_demo for update;
  if not found then
    raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001';
  end if;

  select * into t from public.meal_transactions
   where id=p_transaction_id and merchant_id=p_merchant_id and company_id=s.company_id and not is_demo
   for update;
  if not found then
    raise exception 'SETTLEMENT_TRANSACTION_NOT_FOUND' using errcode='P0001';
  end if;
  v_day := (t.created_at at time zone 'Asia/Seoul')::date;
  if v_day < s.period_from or v_day > s.period_to then
    raise exception 'SETTLEMENT_TRANSACTION_NOT_FOUND' using errcode='P0001';
  end if;

  -- Asked twice (double click, retry): the meal is already cancelled.
  select * into c from public.meal_transactions
   where original_transaction_id=t.id and kind in ('cancel','refund') order by id limit 1;
  if found then
    return jsonb_build_object('settlement', to_jsonb(s), 'cancel_transaction_id', c.id, 'idempotent', true);
  end if;

  if s.settlement_status not in ('draft','revising') or s.tax_invoice_status<>'not_requested' then
    raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001';
  end if;
  -- Subsidized meals used a voucher the employee paid part of; giving that
  -- back is a different flow and is not offered here.
  if t.kind<>'spend' or t.pay_type<>'ledger' then
    raise exception 'SETTLEMENT_TRANSACTION_NOT_CANCELLABLE' using errcode='P0001';
  end if;

  insert into public.meal_transactions(
    user_id, company_id, merchant_id, amount, kind, tx_code, meal_window, flags, idempotency_key, created_at,
    product_id, product_name, product_price, pay_type, tax_type, settlement_tax_type,
    supply_amount, vat_amount, total_amount,
    settlement_supply_amount, settlement_vat_amount, settlement_total_amount, original_transaction_id
  ) values (
    t.user_id, t.company_id, t.merchant_id, abs(t.amount), 'cancel', 'CX-'||t.id::text, t.meal_window,
    jsonb_build_object('cancel_reason', v_reason, 'cancelled_by', p_actor_id, 'cancelled_at', v_now,
                       'settlement_id', s.id),
    'settlement-cancel:'||t.id::text, t.created_at,
    t.product_id, t.product_name, t.product_price, 'ledger', t.tax_type, t.settlement_tax_type,
    t.supply_amount, t.vat_amount, t.total_amount,
    t.settlement_supply_amount, t.settlement_vat_amount, t.settlement_total_amount, t.id
  ) returning * into c;

  -- The after-insert trigger recalculated the settlement over its saved period.
  select * into s from public.settlements where id=s.id;
  insert into public.settlement_events(
    settlement_id, company_id, merchant_id, event_type, payload, idempotency_key, actor_id
  ) values (
    s.id, s.company_id, s.merchant_id, 'merchant_transaction_cancelled',
    jsonb_build_object('transaction_id', t.id, 'cancel_transaction_id', c.id, 'reason', v_reason,
                       'amount', coalesce(c.settlement_total_amount, abs(t.amount)),
                       'used_at', t.created_at, 'total_amount', s.total_amount, 'tx_count', s.tx_count),
    'tx-cancel-'||t.id::text, p_actor_id
  );
  return jsonb_build_object('settlement', to_jsonb(s), 'cancel_transaction_id', c.id, 'idempotent', false);
end $$;

revoke all on function public.merchant_cancel_settlement_transaction(uuid,uuid,uuid,bigint,text)
  from public, anon, authenticated;
grant execute on function public.merchant_cancel_settlement_transaction(uuid,uuid,uuid,bigint,text) to service_role;

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
 select coalesce(sum(case when kind='spend' then abs(amount) else -abs(amount) end) filter (where created_at>=month_start),0),
        coalesce(sum(case when kind='spend' then abs(amount) else -abs(amount) end) filter (where created_at>=day_start),0)
   into spent_month,spent_day from normal_meal_transactions where user_id=p_user_id and kind in ('spend','cancel','refund') and pay_type<>'voucher'
    and created_at>=least(month_start,day_start);
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

notify pgrst, 'reload schema';

commit;
