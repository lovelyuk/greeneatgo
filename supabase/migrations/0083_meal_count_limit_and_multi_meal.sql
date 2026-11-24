-- 0083: a daily meal-count limit for company-paid meals, and several meals in one scan.
--
-- 1. meal_policies.daily_count_limit: how many company-ledger meals one employee may have
--    per day (null = no limit). Set by the company admin. Personal vouchers are never limited.
-- 2. Three wrapper functions that take a quantity. Each runs the EXISTING single-meal
--    function once per meal inside one transaction, so either every meal is recorded or
--    none is (a failure on the third of three undoes the first two). The single-meal
--    functions themselves are not changed.
--       process_meal_pay_many              company ledger (also enforces the count limit)
--       consume_vouchers_many              ordinary vouchers
--       consume_subsidized_vouchers_many   subsidized vouchers
--    Idempotency: meal 1 uses the caller's key unchanged, meal n uses "<key>#n", so a
--    repeated request (the same QR read twice) finds every meal already recorded.
--
-- Additive: one nullable column and three new functions. Safe to run before the server
-- deploy; the server uses the single-meal functions for one meal when these are missing.

alter table public.meal_policies add column if not exists daily_count_limit integer;
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'meal_policies_daily_count_limit_check') then
    alter table public.meal_policies add constraint meal_policies_daily_count_limit_check
      check (daily_count_limit is null or daily_count_limit between 1 and 20);
  end if;
end $$;

create or replace function public.process_meal_pay_many(
  p_user_id uuid, p_company_id uuid, p_merchant_id uuid, p_amount int, p_tx_code text,
  p_meal_window text, p_flags jsonb, p_idempotency_key text, p_quantity int)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare
  v_limit int;
  v_today bigint;
  v_day_start timestamptz;
  v_item jsonb;
  v_items jsonb := '[]'::jsonb;
  v_all_duplicate boolean := true;
  v_replay boolean;
  i int;
begin
  if p_quantity is null or p_quantity < 1 or p_quantity > 10 then
    raise exception 'INVALID_QUANTITY' using errcode = 'P0001';
  end if;
  if p_idempotency_key is null or btrim(p_idempotency_key) = '' then
    raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode = 'P0001';
  end if;
  -- One count check at a time per employee, so two scans cannot both pass it.
  perform pg_advisory_xact_lock(7, hashtext('meal-count:' || p_user_id::text));
  select exists(select 1 from public.meal_transactions where idempotency_key = p_idempotency_key) into v_replay;
  if not v_replay then
    select daily_count_limit into v_limit from public.meal_policies
      where company_id = p_company_id and group_id is null limit 1;
    if v_limit is not null then
      v_day_start := date_trunc('day', now() at time zone 'Asia/Seoul') at time zone 'Asia/Seoul';
      -- A cancelled meal gives its turn back (the reversal row carries the meal's timestamp).
      select coalesce(sum(case when kind = 'spend' then 1 else -1 end), 0) into v_today
      from public.meal_transactions
      where user_id = p_user_id and company_id = p_company_id and pay_type = 'ledger'
        and kind in ('spend', 'cancel', 'refund') and not is_demo and created_at >= v_day_start;
      if v_today + p_quantity > v_limit then
        raise exception 'DAILY_COUNT_LIMIT' using errcode = 'P0001';
      end if;
    end if;
  end if;
  for i in 1..p_quantity loop
    -- All eleven arguments by name: an older eight-argument overload also exists.
    v_item := public.process_meal_pay(
      p_user_id => p_user_id, p_company_id => p_company_id, p_merchant_id => p_merchant_id, p_amount => p_amount,
      p_tx_code => case when i = 1 then p_tx_code else upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 10)) end,
      p_meal_window => p_meal_window, p_flags => p_flags,
      p_idempotency_key => case when i = 1 then p_idempotency_key else p_idempotency_key || '#' || i end,
      p_product_id => null, p_product_name => null, p_product_price => null);
    v_all_duplicate := v_all_duplicate and coalesce((v_item->>'duplicate')::boolean, false);
    v_items := v_items || jsonb_build_array(v_item);
  end loop;
  return (v_items->0) || jsonb_build_object(
    'quantity', p_quantity, 'duplicate', v_all_duplicate, 'unit_amount', p_amount,
    'amount', p_amount * p_quantity, 'items', v_items);
end $$;
revoke all on function public.process_meal_pay_many(uuid,uuid,uuid,int,text,text,jsonb,text,int) from public, anon, authenticated;
grant execute on function public.process_meal_pay_many(uuid,uuid,uuid,int,text,text,jsonb,text,int) to service_role;

create or replace function public.consume_vouchers_many(
  p_user_id uuid, p_merchant_id uuid, p_idempotency_key text, p_quantity int)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare
  v_item jsonb;
  v_items jsonb := '[]'::jsonb;
  v_all_duplicate boolean := true;
  v_total bigint := 0;
  i int;
begin
  if p_quantity is null or p_quantity < 1 or p_quantity > 10 then
    raise exception 'INVALID_QUANTITY' using errcode = 'P0001';
  end if;
  if p_idempotency_key is null or btrim(p_idempotency_key) = '' then
    raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode = 'P0001';
  end if;
  for i in 1..p_quantity loop
    v_item := public.consume_voucher(
      p_user_id => p_user_id, p_merchant_id => p_merchant_id,
      p_idempotency_key => case when i = 1 then p_idempotency_key else p_idempotency_key || '#' || i end);
    v_all_duplicate := v_all_duplicate and coalesce((v_item->>'duplicate')::boolean, false);
    v_total := v_total + coalesce((v_item->>'total_amount')::bigint, (v_item->>'amount')::bigint, 0);
    v_items := v_items || jsonb_build_array(v_item);
  end loop;
  -- The last meal carries the final remaining count.
  return (v_items->0) || jsonb_build_object(
    'quantity', p_quantity, 'duplicate', v_all_duplicate, 'remaining', (v_item->>'remaining')::int,
    'total_amount', v_total, 'amount', v_total, 'items', v_items);
end $$;
revoke all on function public.consume_vouchers_many(uuid,uuid,text,int) from public, anon, authenticated;
grant execute on function public.consume_vouchers_many(uuid,uuid,text,int) to service_role;

create or replace function public.consume_subsidized_vouchers_many(
  p_user_id uuid, p_company_id uuid, p_merchant_id uuid, p_idempotency_key text, p_quantity int)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare
  v_item jsonb;
  v_items jsonb := '[]'::jsonb;
  v_all_duplicate boolean := true;
  v_total bigint := 0;
  i int;
begin
  if p_quantity is null or p_quantity < 1 or p_quantity > 10 then
    raise exception 'INVALID_QUANTITY' using errcode = 'P0001';
  end if;
  if p_idempotency_key is null or btrim(p_idempotency_key) = '' then
    raise exception 'INVALID_IDEMPOTENCY_KEY' using errcode = 'P0001';
  end if;
  for i in 1..p_quantity loop
    v_item := public.consume_subsidized_voucher(
      p_user_id => p_user_id, p_company_id => p_company_id, p_merchant_id => p_merchant_id,
      p_idempotency_key => case when i = 1 then p_idempotency_key else p_idempotency_key || '#' || i end);
    v_all_duplicate := v_all_duplicate and coalesce((v_item->>'duplicate')::boolean, false);
    v_total := v_total + coalesce((v_item->>'total_amount')::bigint, (v_item->>'amount')::bigint, 0);
    v_items := v_items || jsonb_build_array(v_item);
  end loop;
  return (v_items->0) || jsonb_build_object(
    'quantity', p_quantity, 'duplicate', v_all_duplicate, 'remaining', (v_item->>'remaining')::int,
    'total_amount', v_total, 'amount', v_total, 'items', v_items);
end $$;
revoke all on function public.consume_subsidized_vouchers_many(uuid,uuid,uuid,text,int) from public, anon, authenticated;
grant execute on function public.consume_subsidized_vouchers_many(uuid,uuid,uuid,text,int) to service_role;

notify pgrst, 'reload schema';
