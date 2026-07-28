begin;

-- Demo meal transactions are operationally inert but intentionally visible in
-- admin read models. Restore only display aggregates to the base table; the
-- normal_* views remain the mandatory boundary for limits, reviews and all
-- settlement creation/mutation paths.
do $restore_display_read_models$
declare
  ddl text;
  source_count int;
  pair text[];
begin
  foreach pair slice 1 in array array[
    array['public.company_monthly_usage(uuid,uuid,text)',
          'from public.normal_meal_transactions t',
          'from public.meal_transactions t'],
    array['public.merchant_ledger_summary(uuid,uuid,date,date)',
          'from public.normal_meal_transactions',
          'from public.meal_transactions'],
    array['public.merchant_transaction_count(uuid)',
          'from public.normal_meal_transactions where',
          'from public.meal_transactions where']
  ] loop
    ddl := pg_get_functiondef(pair[1]::regprocedure);
    if position(pair[3] in ddl) > 0 then
      continue;
    end if;
    source_count := (length(ddl)-length(replace(ddl,pair[2],'')))/length(pair[2]);
    if source_count <> 1 then
      raise exception '0047 display read source assertion failed: %', pair[1];
    end if;
    ddl := replace(ddl,pair[2],pair[3]);
    if position(pair[2] in ddl) > 0 or position(pair[3] in ddl) = 0 then
      raise exception '0047 display read rewrite failed: %', pair[1];
    end if;
    execute ddl;
  end loop;
end $restore_display_read_models$;

-- Demo seeds keep amount=0 so they cannot alter a customer wallet. Merchant
-- display totals therefore use the immutable settlement snapshot for marked
-- rows, while ordinary rows retain the established ledger/subsidy formula.
create or replace function public.merchant_ledger_summary(
  p_merchant_id uuid,p_company_id uuid,p_period_from date,p_period_to date
) returns jsonb language plpgsql stable security definer set search_path=pg_catalog,public as $$
declare v_result jsonb;
begin
  if p_period_from is null or p_period_to is null or p_period_from>p_period_to then
    raise exception 'INVALID_DATE_RANGE' using errcode='P0001';
  end if;
  select jsonb_build_object(
    'total_amount',coalesce(sum(case
      when kind='spend' then case when is_demo then coalesce(settlement_total_amount,0)
        when pay_type='subsidized' then company_subsidy_amount else abs(amount) end
      when kind in ('refund','cancel') then -(case when is_demo then coalesce(settlement_total_amount,0)
        when pay_type='subsidized' then company_subsidy_amount else abs(amount) end)
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

-- The visible feed is the union of meal transactions and completed direct
-- payment orders, so its reported total must count that same population.
create or replace function public.merchant_payment_feed_count(p_merchant_id uuid)
returns bigint language sql stable security definer set search_path=pg_catalog,public as $$
  select
    (select count(*) from public.meal_transactions where merchant_id=p_merchant_id)
    +
    (select count(*) from public.payment_orders
      where merchant_id=p_merchant_id and status='done' and pay_type='direct');
$$;
revoke all on function public.merchant_payment_feed_count(uuid) from public,anon,authenticated;
grant execute on function public.merchant_payment_feed_count(uuid) to service_role;

-- Customers (including employees) still cannot receive synthetic rows. Admin
-- subscriptions may receive them only inside their original merchant/company
-- tenant boundary.
drop policy if exists merchant_admin_read_own_transactions on public.meal_transactions;
create policy merchant_admin_read_own_transactions on public.meal_transactions for select to authenticated
using (merchant_id in (
  select coalesce(u.merchant_id,ma.merchant_id)
  from public.app_users u left join public.merchant_admins ma on ma.user_id=u.id
  where u.id=auth.uid() and u.role='merchant_admin' and u.status='active'
));

drop policy if exists company_admin_read_own_transactions on public.meal_transactions;
create policy company_admin_read_own_transactions on public.meal_transactions for select to authenticated
using (company_id in (
  select u.company_id from public.app_users u
  where u.id=auth.uid() and u.role='company_admin' and u.status='active'
    and u.company_id is not null
));

notify pgrst,'reload schema';
commit;
