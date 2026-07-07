-- Atomic payment function placeholder.
-- Final implementation must re-check affiliation, policy, balance, idempotency, and insert spend row in one transaction.
create or replace function process_meal_pay(
  p_user_id uuid,
  p_company_id uuid,
  p_merchant_id uuid,
  p_amount int,
  p_tx_code text,
  p_meal_window text,
  p_flags jsonb,
  p_idempotency_key text
) returns bigint
language plpgsql
security definer
as $$
declare
  v_tx_id bigint;
begin
  insert into meal_transactions(user_id, company_id, merchant_id, amount, kind, tx_code, meal_window, flags, idempotency_key)
  values (p_user_id, p_company_id, p_merchant_id, -abs(p_amount), 'spend', p_tx_code, p_meal_window, coalesce(p_flags, '{}'::jsonb), p_idempotency_key)
  returning id into v_tx_id;

  return v_tx_id;
end;
$$;
