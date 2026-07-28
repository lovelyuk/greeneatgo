-- Company-admin monthly usage read model.
-- Financial facts come from immutable transaction/settlement snapshots. The
-- service-role caller must pass both token-owned actor and company identifiers;
-- authorization is repeated inside this SECURITY DEFINER boundary.

drop function if exists public.company_monthly_usage(uuid, text);

create or replace function public.company_monthly_usage(
  p_actor_id uuid,
  p_company_id uuid,
  p_period_ym text
) returns jsonb
language plpgsql
stable
security definer
set search_path = pg_catalog, public
as $$
declare
  v_month date;
  v_from timestamptz;
  v_to timestamptz;
  v_result jsonb;
begin
  if p_actor_id is null or p_company_id is null then
    raise exception 'COMPANY_USAGE_INPUT_INVALID' using errcode = 'P0001';
  end if;
  if not exists (
    select 1
    from public.app_users u
    where u.id = p_actor_id
      and u.company_id = p_company_id
      and u.role = 'company_admin'
      and coalesce(u.status, '') = 'active'
  ) then
    raise exception 'COMPANY_USAGE_ACTOR_FORBIDDEN' using errcode = 'P0001';
  end if;
  if p_period_ym is null or p_period_ym !~ '^[0-9]{4}-(0[1-9]|1[0-2])$' then
    raise exception 'COMPANY_USAGE_MONTH_INVALID' using errcode = 'P0001';
  end if;

  v_month := pg_catalog.to_date(p_period_ym || '-01', 'YYYY-MM-DD');
  if pg_catalog.to_char(v_month, 'YYYY-MM') <> p_period_ym then
    raise exception 'COMPANY_USAGE_MONTH_INVALID' using errcode = 'P0001';
  end if;

  -- Half-open Seoul civil-month bounds correctly handle UTC storage and avoid
  -- session-timezone dependence.
  v_from := v_month::timestamp at time zone 'Asia/Seoul';
  v_to := (v_month + interval '1 month')::timestamp at time zone 'Asia/Seoul';

  with usage_rows as materialized (
    select
      t.id,
      t.user_id,
      (t.created_at at time zone 'Asia/Seoul')::date as usage_date,
      t.kind,
      case when t.kind = 'spend' then 1 else -1 end as direction,
      coalesce(t.total_amount, abs(t.amount), 0)::bigint as gross_amount,
      coalesce(
        t.settlement_total_amount,
        case when t.pay_type = 'subsidized' then t.company_subsidy_amount else abs(t.amount) end,
        0
      )::bigint as company_amount,
      coalesce(t.employee_paid_amount, 0)::bigint as employee_amount
    from public.meal_transactions t
    where t.company_id = p_company_id
      and t.pay_type in ('ledger', 'subsidized')
      and t.kind in ('spend', 'refund', 'cancel')
      and t.created_at >= v_from
      and t.created_at < v_to
  ),
  usage_summary as (
    select
      coalesce(sum(direction * gross_amount), 0)::bigint as gross_spend_amount,
      coalesce(sum(direction * company_amount), 0)::bigint as company_charge_amount,
      coalesce(sum(direction * employee_amount), 0)::bigint as employee_paid_amount,
      count(*)::int as transaction_count,
      count(*) filter (where kind = 'spend')::int as spend_count,
      count(*) filter (where kind in ('refund', 'cancel'))::int as reversal_count,
      count(distinct user_id) filter (where kind = 'spend')::int as unique_users
    from usage_rows
  ),
  employee_counts as (
    select
      (select count(*) from public.app_users u
       where u.company_id = p_company_id and u.role = 'employee')::int
      +
      (select count(*) from public.employee_bulk_invites i
       where i.company_id = p_company_id
         and i.status = 'invited'
         and i.claimed_by is null)::int as total_employee_count,
      (select count(*) from public.app_users u
       where u.company_id = p_company_id
         and u.role = 'employee'
         and coalesce(u.status, '') = 'active')::int as active_employee_count
  ),
  settlement_rows as materialized (
    select
      s.id,
      s.total_amount::bigint as total_amount,
      coalesce(p.confirmed_amount, 0)::bigint as confirmed_amount,
      greatest(s.total_amount::bigint - coalesce(p.confirmed_amount, 0), 0)::bigint as outstanding_amount
    from public.settlements s
    left join lateral (
      select sum(sp.amount)::bigint as confirmed_amount
      from public.settlement_payments sp
      where sp.settlement_id = s.id and sp.confirmed_at is not null
    ) p on true
    where s.company_id = p_company_id
      and s.period_ym = p_period_ym
      and coalesce(s.settlement_status, '') <> 'cancelled'
  ),
  settlement_summary as (
    select
      count(*)::int as settlement_count,
      coalesce(sum(total_amount), 0)::bigint as settlement_total_amount,
      coalesce(sum(confirmed_amount), 0)::bigint as confirmed_payment_amount,
      coalesce(sum(outstanding_amount), 0)::bigint as outstanding_amount
    from settlement_rows
  ),
  daily_json as (
    select coalesce(jsonb_agg(jsonb_build_object(
      'date', d.usage_date,
      'gross_spend_amount', d.gross_spend_amount,
      'company_charge_amount', d.company_charge_amount,
      'employee_paid_amount', d.employee_paid_amount,
      'transaction_count', d.transaction_count,
      'spend_count', d.spend_count,
      'reversal_count', d.reversal_count,
      'unique_users', d.unique_users
    ) order by d.usage_date), '[]'::jsonb) as value
    from (
      select usage_date,
        sum(direction * gross_amount)::bigint as gross_spend_amount,
        sum(direction * company_amount)::bigint as company_charge_amount,
        sum(direction * employee_amount)::bigint as employee_paid_amount,
        count(*)::int as transaction_count,
        count(*) filter (where kind = 'spend')::int as spend_count,
        count(*) filter (where kind in ('refund', 'cancel'))::int as reversal_count,
        count(distinct user_id) filter (where kind = 'spend')::int as unique_users
      from usage_rows group by usage_date
    ) d
  ),
  employee_usage as (
    select r.user_id,
      sum(r.direction * r.gross_amount)::bigint as gross_spend_amount,
      sum(r.direction * r.company_amount)::bigint as company_charge_amount,
      sum(r.direction * r.employee_amount)::bigint as employee_paid_amount,
      count(*)::int as transaction_count,
      count(*) filter (where r.kind = 'spend')::int as spend_count,
      count(*) filter (where r.kind in ('refund', 'cancel'))::int as reversal_count,
      count(distinct r.usage_date)::int as usage_days
    from usage_rows r
    group by r.user_id
  ),
  employee_json as (
    select coalesce(jsonb_agg(jsonb_build_object(
      'user_id', e.user_id,
      'display_name', coalesce(nullif(btrim(u.display_name), ''), '알 수 없는 사용자'),
      -- A user may since have moved tenants. Do not expose another tenant's
      -- employee number or department; the historical transaction remains visible.
      'employee_no', case when u.company_id = p_company_id then u.employee_no else null end,
      'department', case when u.company_id = p_company_id then u.department else null end,
      'status', case
        when u.id is null then 'unknown'
        when u.company_id is distinct from p_company_id then 'former'
        else coalesce(u.status, 'unknown')
      end,
      'gross_spend_amount', e.gross_spend_amount,
      'company_charge_amount', e.company_charge_amount,
      'employee_paid_amount', e.employee_paid_amount,
      'transaction_count', e.transaction_count,
      'spend_count', e.spend_count,
      'reversal_count', e.reversal_count,
      'usage_days', e.usage_days
    ) order by e.gross_spend_amount desc,
               coalesce(nullif(btrim(u.display_name), ''), '알 수 없는 사용자'),
               e.user_id), '[]'::jsonb) as value
    from employee_usage e
    left join public.app_users u on u.id = e.user_id
  )
  select jsonb_build_object(
    'period', jsonb_build_object(
      'ym', p_period_ym,
      'timezone', 'Asia/Seoul',
      'start_at', v_from,
      'end_at', v_to
    ),
    'summary', jsonb_build_object(
      'gross_spend_amount', us.gross_spend_amount,
      'company_charge_amount', us.company_charge_amount,
      'employee_paid_amount', us.employee_paid_amount,
      'transaction_count', us.transaction_count,
      'spend_count', us.spend_count,
      'reversal_count', us.reversal_count,
      'unique_users', us.unique_users,
      'used_employee_count', us.unique_users,
      'total_employee_count', ec.total_employee_count,
      'active_employee_count', ec.active_employee_count,
      'outstanding_settlement_amount', ss.outstanding_amount,
      'confirmed_payment_amount', ss.confirmed_payment_amount
    ),
    'daily', dj.value,
    'employees', ej.value,
    'settlements', jsonb_build_object(
      'count', ss.settlement_count,
      'total_amount', ss.settlement_total_amount,
      'confirmed_payment_amount', ss.confirmed_payment_amount,
      'outstanding_amount', ss.outstanding_amount
    )
  ) into v_result
  from usage_summary us
  cross join employee_counts ec
  cross join settlement_summary ss
  cross join daily_json dj
  cross join employee_json ej;

  return v_result;
end $$;

revoke all on function public.company_monthly_usage(uuid, uuid, text) from public, anon, authenticated, service_role;
grant execute on function public.company_monthly_usage(uuid, uuid, text) to service_role;
