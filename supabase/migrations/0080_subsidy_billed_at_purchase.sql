-- 0080: company subsidies are billed when the voucher is BOUGHT, not when it is used.
--
-- Scope: subsidized companies only (merchant_companies.subsidy_enabled). Ledger and
-- prepurchase companies, personal vouchers and every settlement function are untouched.
--
-- Before: consume_subsidized_voucher wrote one company-billed row (pay_type 'subsidized')
--         when the employee used the voucher; settlements sum those rows.
-- After:  1. When a subsidized voucher is issued, a "charge" row is written for the company
--            (pay_type 'subsidized', kind 'spend', the company subsidy as the settlement
--            amount, dated at the purchase). The existing settlement triggers pick it up, so
--            the month's settlement and tax invoice are on the purchase basis.
--         2. When such a voucher is used, the meal row is written as before but with a
--            settlement amount of 0, so the company is not billed twice.
--         3. When such a voucher is refunded or forfeited unused, a reversal row points at
--            the charge. It lands in the purchase's period (same mechanism as 0079 cancels);
--            if that period was already sent or invoiced, in the current period instead.
--
-- Transition: vouchers issued before this migration have no charge row and keep the old
-- behaviour (billed when used). Nothing is backfilled.
--
-- Safety: issuing and refunding vouchers must never fail because of billing. Both triggers
-- catch every error, record it in subsidy_charge_issues and let the voucher change through;
-- a voucher without a charge row is then simply billed when used, as before.
--
-- Changes: one new table, two triggers on vouchers, the voucher index on meal_transactions
-- narrowed to meal rows (plus one for charge rows), two replaced functions
-- (consume_subsidized_voucher and merchant_ledger_summary; the changed lines are marked).

create table if not exists public.subsidy_charge_issues (
  id bigint generated always as identity primary key,
  voucher_id uuid,
  stage text not null check (stage in ('charge', 'reversal')),
  detail text,
  created_at timestamptz not null default now()
);
alter table public.subsidy_charge_issues enable row level security;
revoke all on table public.subsidy_charge_issues from public, anon, authenticated;

-- "One meal per voucher" (0015) stays, but a purchase charge and its reversal also point at
-- the voucher, so they get their own rule: at most one charge and one reversal per voucher.
drop index if exists public.idx_meal_transactions_voucher_unique;
create unique index idx_meal_transactions_voucher_unique on public.meal_transactions(voucher_id)
  where voucher_id is not null and not (coalesce(flags, '{}'::jsonb) ? 'subsidy_charge');
create unique index if not exists idx_meal_transactions_subsidy_charge_unique on public.meal_transactions(voucher_id, kind)
  where voucher_id is not null and coalesce(flags, '{}'::jsonb) ? 'subsidy_charge';

-- 1. Charge the company when the voucher is issued.
create or replace function public.record_subsidy_charge_on_voucher_issue()
returns trigger language plpgsql security definer set search_path = pg_catalog, public as $$
declare
  o public.payment_orders%rowtype;
  sp record;
begin
  if new.company_id is null or coalesce(new.company_subsidy_amount, 0) <= 0
     or new.tax_type = 'unclassified' or new.status <> 'unused' then
    return new;
  end if;
  begin
    select * into o from public.payment_orders where id = new.order_id;
    if not found or o.pay_type <> 'subsidized' then
      return new;
    end if;
    select * into sp from public.split_tax_inclusive(new.company_subsidy_amount, new.tax_type);
    insert into public.meal_transactions(
      user_id, company_id, merchant_id, amount, kind, tx_code, meal_window, flags, idempotency_key, created_at,
      product_name, product_price, pay_type, voucher_id,
      employee_paid_amount, company_subsidy_amount, restaurant_subsidy_amount,
      tax_type, supply_amount, vat_amount, total_amount,
      settlement_tax_type, settlement_supply_amount, settlement_vat_amount, settlement_total_amount
    ) values (
      new.user_id, new.company_id, new.merchant_id, -new.company_subsidy_amount, 'spend',
      upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 10)), '보조금',
      jsonb_build_object('subsidized', true, 'subsidy_charge', true, 'order_id', new.order_id),
      'subsidy-charge:' || new.id::text, new.purchased_at,
      '보조금 식권 구매', new.company_subsidy_amount, 'subsidized', new.id,
      0, new.company_subsidy_amount, 0,
      new.tax_type, sp.supply_amount, sp.vat_amount, sp.total_amount,
      new.tax_type, sp.supply_amount, sp.vat_amount, sp.total_amount
    ) on conflict (idempotency_key) do nothing;
  exception when others then
    insert into public.subsidy_charge_issues(voucher_id, stage, detail) values (new.id, 'charge', sqlerrm);
  end;
  return new;
end $$;
revoke all on function public.record_subsidy_charge_on_voucher_issue() from public, anon, authenticated, service_role;
drop trigger if exists trg_voucher_subsidy_charge on public.vouchers;
create trigger trg_voucher_subsidy_charge after insert on public.vouchers
  for each row execute function public.record_subsidy_charge_on_voucher_issue();

-- 3. Take the charge back when the voucher is refunded or forfeited unused.
create or replace function public.reverse_subsidy_charge_on_voucher_refund()
returns trigger language plpgsql security definer set search_path = pg_catalog, public as $$
declare
  charge public.meal_transactions%rowtype;
  v_closed boolean;
begin
  if old.status <> 'unused' or new.status not in ('refunded', 'forfeited') or new.company_id is null then
    return new;
  end if;
  begin
    select * into charge from public.meal_transactions
    where voucher_id = new.id and kind = 'spend' and pay_type = 'subsidized'
      and coalesce(flags, '{}'::jsonb) ? 'subsidy_charge'
    limit 1;
    if not found then
      return new;  -- voucher from before 0080: nothing was charged at purchase
    end if;
    -- Normally the reversal carries the charge's timestamp, so it nets to zero inside the
    -- charge's own period. If that period's settlement was already sent or invoiced it must
    -- not change: the reversal is then dated now and comes off the current period instead.
    select exists(
      select 1 from public.settlements s
      where s.merchant_id = charge.merchant_id and s.company_id = charge.company_id and not s.is_demo
        and s.period_ym = to_char(charge.created_at at time zone 'Asia/Seoul', 'YYYY-MM')
        and (s.settlement_status not in ('draft', 'calculating', 'revising') or s.tax_invoice_status <> 'not_requested')
    ) into v_closed;
    if v_closed then
      begin
      insert into public.meal_transactions(
        user_id, company_id, merchant_id, amount, kind, tx_code, meal_window, flags, idempotency_key, created_at,
        product_name, product_price, pay_type, voucher_id,
        employee_paid_amount, company_subsidy_amount, restaurant_subsidy_amount,
        tax_type, supply_amount, vat_amount, total_amount,
        settlement_tax_type, settlement_supply_amount, settlement_vat_amount, settlement_total_amount,
        original_transaction_id
      ) values (
        charge.user_id, charge.company_id, charge.merchant_id, abs(charge.amount), 'refund',
        'SR-' || charge.id::text, charge.meal_window,
        jsonb_build_object('subsidized', true, 'subsidy_charge', true, 'subsidy_charge_reversal', true,
                           'voucher_status', new.status, 'refunded_at', clock_timestamp(),
                           'after_settlement_closed', v_closed, 'carried_to_current_period', true, 'order_id', new.order_id),
        'subsidy-charge-reversal:' || new.id::text, clock_timestamp(),
        '보조금 식권 환불', charge.product_price, 'subsidized', new.id,
        0, charge.company_subsidy_amount, 0,
        charge.tax_type, charge.supply_amount, charge.vat_amount, charge.total_amount,
        charge.settlement_tax_type, charge.settlement_supply_amount, charge.settlement_vat_amount, charge.settlement_total_amount,
        charge.id
      ) on conflict (idempotency_key) do nothing;
      exception when others then
        -- The current period cannot absorb it (for example nothing was bought this month, so
        -- it would go negative). Keep the record in the purchase's period, which stays frozen:
        -- the restaurant has to correct that settlement by hand. Logged so it is not missed.
        insert into public.subsidy_charge_issues(voucher_id, stage, detail)
          values (new.id, 'reversal', 'not carried to the current period: ' || sqlerrm);
      insert into public.meal_transactions(
        user_id, company_id, merchant_id, amount, kind, tx_code, meal_window, flags, idempotency_key, created_at,
        product_name, product_price, pay_type, voucher_id,
        employee_paid_amount, company_subsidy_amount, restaurant_subsidy_amount,
        tax_type, supply_amount, vat_amount, total_amount,
        settlement_tax_type, settlement_supply_amount, settlement_vat_amount, settlement_total_amount,
        original_transaction_id
      ) values (
        charge.user_id, charge.company_id, charge.merchant_id, abs(charge.amount), 'refund',
        'SR-' || charge.id::text, charge.meal_window,
        jsonb_build_object('subsidized', true, 'subsidy_charge', true, 'subsidy_charge_reversal', true,
                           'voucher_status', new.status, 'refunded_at', clock_timestamp(),
                           'after_settlement_closed', v_closed, 'carried_to_current_period', false, 'order_id', new.order_id),
        'subsidy-charge-reversal:' || new.id::text, charge.created_at,
        '보조금 식권 환불', charge.product_price, 'subsidized', new.id,
        0, charge.company_subsidy_amount, 0,
        charge.tax_type, charge.supply_amount, charge.vat_amount, charge.total_amount,
        charge.settlement_tax_type, charge.settlement_supply_amount, charge.settlement_vat_amount, charge.settlement_total_amount,
        charge.id
      ) on conflict (idempotency_key) do nothing;
      end;
    else
      insert into public.meal_transactions(
        user_id, company_id, merchant_id, amount, kind, tx_code, meal_window, flags, idempotency_key, created_at,
        product_name, product_price, pay_type, voucher_id,
        employee_paid_amount, company_subsidy_amount, restaurant_subsidy_amount,
        tax_type, supply_amount, vat_amount, total_amount,
        settlement_tax_type, settlement_supply_amount, settlement_vat_amount, settlement_total_amount,
        original_transaction_id
      ) values (
        charge.user_id, charge.company_id, charge.merchant_id, abs(charge.amount), 'refund',
        'SR-' || charge.id::text, charge.meal_window,
        jsonb_build_object('subsidized', true, 'subsidy_charge', true, 'subsidy_charge_reversal', true,
                           'voucher_status', new.status, 'refunded_at', clock_timestamp(),
                           'after_settlement_closed', false, 'carried_to_current_period', false, 'order_id', new.order_id),
        'subsidy-charge-reversal:' || new.id::text, charge.created_at,
        '보조금 식권 환불', charge.product_price, 'subsidized', new.id,
        0, charge.company_subsidy_amount, 0,
        charge.tax_type, charge.supply_amount, charge.vat_amount, charge.total_amount,
        charge.settlement_tax_type, charge.settlement_supply_amount, charge.settlement_vat_amount, charge.settlement_total_amount,
        charge.id
      ) on conflict (idempotency_key) do nothing;
    end if;
  exception when others then
    insert into public.subsidy_charge_issues(voucher_id, stage, detail) values (new.id, 'reversal', sqlerrm);
  end;
  return new;
end $$;
revoke all on function public.reverse_subsidy_charge_on_voucher_refund() from public, anon, authenticated, service_role;
drop trigger if exists trg_voucher_subsidy_charge_reversal on public.vouchers;
create trigger trg_voucher_subsidy_charge_reversal after update of status on public.vouchers
  for each row execute function public.reverse_subsidy_charge_on_voucher_refund();

-- 2. Using a voucher that was charged at purchase: the meal row is written exactly as before
--    (same pay_type, company, amounts), except that it carries a settlement amount of 0.
--    Only the lines marked 0080 differ from infra/migrations/0036.
create or replace function public.consume_subsidized_voucher(p_user_id uuid, p_company_id uuid, p_merchant_id uuid, p_idempotency_key text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare existing meal_transactions%rowtype; v vouchers%rowtype; tx meal_transactions%rowtype; full_split record; settlement_split record;
 candidate_id uuid; candidate_order_id uuid; order_status text; employee_amount int; full_total int; remaining_count int;
 charge_id bigint;  -- 0080
begin
 if p_idempotency_key is null or btrim(p_idempotency_key)='' then raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode='P0001'; end if;
 perform pg_advisory_xact_lock(hashtextextended('voucher-refund-queue:'||p_user_id::text||':'||p_company_id::text||':'||p_merchant_id::text,0));
 perform pg_advisory_xact_lock(1,hashtext(p_idempotency_key));
 select * into existing from meal_transactions where idempotency_key=p_idempotency_key limit 1;
 if found then
  if existing.user_id<>p_user_id or existing.company_id<>p_company_id or existing.merchant_id<>p_merchant_id or existing.pay_type<>'subsidized'
   or existing.tax_type='unclassified' or existing.total_amount is null or existing.settlement_total_amount is null
   or coalesce(existing.flags,'{}'::jsonb) ? 'subsidy_charge'  -- 0080: a charge row is not a meal
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
 -- 0080: was the company already charged when this voucher was bought? Then this meal bills 0.
 select id into charge_id from meal_transactions
  where voucher_id=v.id and kind='spend' and pay_type='subsidized' and coalesce(flags,'{}'::jsonb) ? 'subsidy_charge' limit 1;
 select * into settlement_split from split_tax_inclusive(case when charge_id is null then v.company_subsidy_amount else 0 end,v.tax_type);
 update vouchers set status='used',used_at=now() where id=v.id;
 insert into meal_transactions(user_id,company_id,merchant_id,amount,kind,tx_code,meal_window,flags,idempotency_key,product_name,product_price,pay_type,voucher_id,
  employee_paid_amount,company_subsidy_amount,restaurant_subsidy_amount,tax_type,supply_amount,vat_amount,total_amount,
  settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount)
 values(p_user_id,p_company_id,p_merchant_id,-full_total,'spend',upper(substr(replace(gen_random_uuid()::text,'-',''),1,10)),'보조금',
  case when charge_id is null then jsonb_build_object('subsidized',true)
   else jsonb_build_object('subsidized',true,'charged_at_purchase',true,'subsidy_charge_transaction_id',charge_id) end,  -- 0080
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
revoke all on function public.consume_subsidized_voucher(uuid,uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.consume_subsidized_voucher(uuid,uuid,uuid,text) to service_role;

-- The restaurant's ledger summary read the subsidy column directly; a meal that was charged
-- at purchase must count 0 there too, so it now prefers the settlement amount.
-- Same as infra/migrations/0062 except the subsidized branch (old rows give the same number,
-- because their settlement amount equals the subsidy).
create or replace function public.merchant_ledger_summary(p_merchant_id uuid, p_company_id uuid, p_period_from date, p_period_to date)
returns jsonb language plpgsql stable security definer set search_path = pg_catalog, public as $$
declare v_result jsonb;
begin
  if p_period_from is null or p_period_to is null or p_period_from>p_period_to then
    raise exception 'INVALID_DATE_RANGE' using errcode='P0001';
  end if;
  select jsonb_build_object(
    'total_amount',coalesce(sum(case
      when kind='spend' then case when is_demo then coalesce(settlement_total_amount,0)
        when pay_type='subsidized' then coalesce(settlement_total_amount,company_subsidy_amount) else abs(amount) end
      when kind in ('refund','cancel') then -(case when is_demo then coalesce(settlement_total_amount,0)
        when pay_type='subsidized' then coalesce(settlement_total_amount,company_subsidy_amount) else abs(amount) end)
      else 0 end),0),
    'total_count',count(*),
    'cancel_count',count(*) filter(where kind in ('refund','cancel')),
    'restaurant_subsidy_amount',coalesce(sum(case
      when kind='spend' and pay_type='subsidized' then restaurant_subsidy_amount
      when kind in ('refund','cancel') and pay_type='subsidized' then -restaurant_subsidy_amount
      else 0 end),0)
  ) into v_result
  from public.meal_transactions
  where merchant_id=p_merchant_id and company_id=p_company_id
    and pay_type in ('ledger','subsidized')
    and created_at >= (p_period_from::timestamp at time zone 'Asia/Seoul')
    and created_at < ((p_period_to+1)::timestamp at time zone 'Asia/Seoul');
  return v_result;
end $$;
revoke all on function public.merchant_ledger_summary(uuid,uuid,date,date) from public,anon,authenticated;
grant execute on function public.merchant_ledger_summary(uuid,uuid,date,date) to service_role;

notify pgrst, 'reload schema';
