-- Switch payment from prepaid balance to monthly-limit ledger mode.
-- greeneatGo/MealLedger does not hold company funds; companies settle directly with restaurants.
-- The API enforces app_users.monthly_limit before calling this atomic insert function.

create or replace function process_meal_pay(
  p_user_id uuid,
  p_company_id uuid,
  p_merchant_id uuid,
  p_amount int,
  p_tx_code text,
  p_meal_window text,
  p_flags jsonb,
  p_idempotency_key text,
  p_product_id uuid default null,
  p_product_name text default null,
  p_product_price int default null
) returns jsonb
language plpgsql
security definer
as $$
declare
  v_existing meal_transactions%rowtype;
  v_company_status text;
  v_tx meal_transactions%rowtype;
begin
  if p_amount is null or p_amount <= 0 then
    raise exception 'INVALID_AMOUNT' using errcode = 'P0001';
  end if;

  select * into v_existing
  from meal_transactions
  where idempotency_key = p_idempotency_key
  limit 1;

  if found then
    return jsonb_build_object(
      'id', v_existing.id,
      'tx_code', v_existing.tx_code,
      'amount', abs(v_existing.amount),
      'duplicate', true,
      'created_at', v_existing.created_at
    );
  end if;

  perform pg_advisory_xact_lock(hashtext(p_user_id::text));

  select status into v_company_status
  from companies
  where id = p_company_id
  for share;

  if v_company_status is distinct from 'active' then
    raise exception 'COMPANY_NOT_ACTIVE' using errcode = 'P0001';
  end if;

  if not exists (
    select 1 from merchant_companies
    where merchant_id = p_merchant_id
      and company_id = p_company_id
      and status = 'active'
  ) and not exists (
    select 1 from company_merchants
    where merchant_id = p_merchant_id
      and company_id = p_company_id
      and is_active = true
  ) then
    raise exception 'NOT_AFFILIATED' using errcode = 'P0001';
  end if;

  insert into meal_transactions(
    user_id, company_id, merchant_id, amount, kind, tx_code, meal_window, flags,
    idempotency_key, product_id, product_name, product_price
  ) values (
    p_user_id, p_company_id, p_merchant_id, -abs(p_amount), 'spend', p_tx_code, p_meal_window,
    coalesce(p_flags, '{}'::jsonb), p_idempotency_key, p_product_id, p_product_name, p_product_price
  ) returning * into v_tx;

  return jsonb_build_object(
    'id', v_tx.id,
    'tx_code', v_tx.tx_code,
    'amount', abs(v_tx.amount),
    'duplicate', false,
    'created_at', v_tx.created_at,
    'product_id', v_tx.product_id,
    'product_name', v_tx.product_name,
    'product_price', v_tx.product_price
  );
end;
$$;
