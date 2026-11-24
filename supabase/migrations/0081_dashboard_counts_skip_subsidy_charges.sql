-- 0081: dashboards count meals, not purchase charges.
--
-- After 0080 a subsidized voucher writes a charge row for the company when it is bought.
-- Its AMOUNT belongs on the purchase day (unchanged here), but it is not a meal, so it must
-- not add to any count. Two read-only functions are replaced; only the lines marked 0081
-- (and the count expressions next to them) differ from the current definitions
-- (infra/migrations/0057, and 0040 as rewritten by 0045/0047 to read normal_settlements).
--
--   admin_dashboard_summary : total/meal-type/series/top-company COUNTS skip charge rows.
--   company_monthly_usage   : counts, used-employee numbers and usage days skip charge rows,
--                             and a charge row adds no gross meal value (the meal row does).
--
-- No table, trigger, settlement or invoice calculation is touched. Safe to run any time
-- after 0080; before 0080 it changes nothing (no row carries the flag).

CREATE OR REPLACE FUNCTION public.admin_dashboard_summary(p_actor_id uuid, p_period_from date, p_period_to date, p_merchant_id uuid DEFAULT NULL::uuid, p_company_id uuid DEFAULT NULL::uuid, p_dinner_start_hour integer DEFAULT NULL::integer)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $$
declare
  v_role text;
  v_actor_merchant_id uuid;
  v_actor_company_id uuid;
  v_current_from timestamptz;
  v_current_to timestamptz;
  v_previous_from timestamptz;
  v_days integer;
  v_unit text;
  v_total_amount bigint;
  v_previous_amount bigint;
  v_total_count bigint;
  v_previous_count bigint;
  v_by_meal_type jsonb;
  v_series jsonb;
  v_top_amount jsonb := '[]'::jsonb;
  v_top_count jsonb := '[]'::jsonb;
begin
  if p_actor_id is null or p_period_from is null or p_period_to is null
     or p_period_from > p_period_to
     or p_period_to - p_period_from + 1 > 366
     or p_dinner_start_hour is null or p_dinner_start_hour < 0 or p_dinner_start_hour > 23 then
    raise exception 'ADMIN_DASHBOARD_INPUT_INVALID' using errcode = 'P0001';
  end if;

  select u.role, u.merchant_id, u.company_id
    into v_role, v_actor_merchant_id, v_actor_company_id
  from public.app_users u
  where u.id = p_actor_id and u.status = 'active'
    and u.role in ('merchant_admin', 'company_admin', 'platform_admin');
  if not found then
    raise exception 'ADMIN_DASHBOARD_ACTOR_FORBIDDEN' using errcode = 'P0001';
  end if;

  -- A non-platform actor must provide its own primary scope. An optional second
  -- scope is visible only through an active merchant/company relationship.
  if v_role = 'merchant_admin' then
    if p_merchant_id is null or p_merchant_id is distinct from v_actor_merchant_id
       or not exists (select 1 from public.merchants m where m.id = p_merchant_id and m.status = 'active')
       or (p_company_id is not null and not exists (
         select 1 from public.companies c
         join public.merchant_companies mc on mc.company_id = c.id
         where c.id = p_company_id and c.status = 'active'
           and mc.merchant_id = p_merchant_id and mc.status = 'active'
       )) then
      raise exception 'ADMIN_DASHBOARD_SCOPE_NOT_FOUND' using errcode = 'P0001';
    end if;
  elsif v_role = 'company_admin' then
    if p_company_id is null or p_company_id is distinct from v_actor_company_id
       or not exists (select 1 from public.companies c where c.id = p_company_id and c.status = 'active')
       or (p_merchant_id is not null and not exists (
         select 1 from public.merchants m
         join public.merchant_companies mc on mc.merchant_id = m.id
         where m.id = p_merchant_id and m.status = 'active'
           and mc.company_id = p_company_id and mc.status = 'active'
       )) then
      raise exception 'ADMIN_DASHBOARD_SCOPE_NOT_FOUND' using errcode = 'P0001';
    end if;
  else
    if (p_merchant_id is not null and not exists (
          select 1 from public.merchants m where m.id = p_merchant_id and m.status = 'active'))
       or (p_company_id is not null and not exists (
          select 1 from public.companies c where c.id = p_company_id and c.status = 'active')) then
      raise exception 'ADMIN_DASHBOARD_SCOPE_NOT_FOUND' using errcode = 'P0001';
    end if;
  end if;

  if p_merchant_id is null and p_company_id is null and v_role <> 'platform_admin' then
    raise exception 'ADMIN_DASHBOARD_ACTOR_FORBIDDEN' using errcode = 'P0001';
  end if;

  v_days := p_period_to - p_period_from + 1;
  v_unit := case
    when v_days <= 31 then 'day'
    when v_days <= 120 then 'week'
    else 'month'
  end;
  v_current_from := p_period_from::timestamp at time zone 'Asia/Seoul';
  v_current_to := (p_period_to + 1)::timestamp at time zone 'Asia/Seoul';
  v_previous_from := (p_period_from - v_days)::timestamp at time zone 'Asia/Seoul';

  -- Classification, immutable settlement snapshot fallback, and signed direction
  -- are each derived once for the current+comparison population and reused below.
  with facts as materialized (
    select
      t.company_id,
      (t.created_at at time zone 'Asia/Seoul')::date as civil_date,
      case when extract(hour from t.created_at at time zone 'Asia/Seoul') < p_dinner_start_hour
           then '중식' else '석식' end as meal_type,
      case when t.kind = 'spend' then 1 else -1 end::bigint as direction,
      -- 0081: a subsidy charged at purchase adds its amount but is not a meal.
      case when coalesce(t.flags, '{}'::jsonb) ? 'subsidy_charge' then 0 else 1 end::bigint as unit,
      coalesce(
        t.settlement_total_amount,
        case when t.pay_type = 'subsidized' then t.company_subsidy_amount else abs(t.amount) end,
        0
      )::bigint as settlement_amount,
      t.created_at
    from public.meal_transactions t
    where t.kind in ('spend', 'refund', 'cancel')
      and t.created_at >= v_previous_from and t.created_at < v_current_to
      and (p_merchant_id is null or t.merchant_id = p_merchant_id)
      and (p_company_id is null or (
        t.company_id = p_company_id and t.pay_type in ('ledger', 'subsidized')
      ))
  ),
  totals as (
    select
      coalesce(sum(direction * settlement_amount) filter (where created_at >= v_current_from), 0)::bigint as amount,
      coalesce(sum(direction * unit) filter (where created_at >= v_current_from), 0)::bigint as count,
      coalesce(sum(direction * settlement_amount) filter (where created_at < v_current_from), 0)::bigint as previous_amount,
      coalesce(sum(direction * unit) filter (where created_at < v_current_from), 0)::bigint as previous_count
    from facts
  ),
  meal_names(meal_type, meal_order) as (values ('중식'::text, 1), ('석식'::text, 2)),
  meals as (
    select n.meal_type, n.meal_order,
      coalesce(sum(f.direction * f.settlement_amount), 0)::bigint as amount,
      coalesce(sum(f.direction * f.unit), 0)::bigint as count,
      count(*) filter (where f.direction = 1 and f.unit = 1)::bigint as spend_count
    from meal_names n
    left join facts f on f.meal_type = n.meal_type and f.created_at >= v_current_from
    group by n.meal_type, n.meal_order
  ),
  meal_ratio_total as (
    select coalesce(sum(spend_count), 0)::bigint as spend_count from meals
  ),
  meal_json as (
    select jsonb_agg(jsonb_build_object(
      'label', m.meal_type,
      'amount', m.amount,
      'count', m.count,
      'ratio', case when rt.spend_count = 0 then 0.0
                    else round(m.spend_count::numeric * 100.0 / rt.spend_count, 1) end
    ) order by m.meal_order) as value
    from meals m cross join meal_ratio_total rt
    group by rt.spend_count
  ),
  buckets as (
    select case v_unit
             when 'day' then f.civil_date
             when 'week' then pg_catalog.date_trunc('week', f.civil_date::timestamp)::date
             else pg_catalog.date_trunc('month', f.civil_date::timestamp)::date
           end as bucket_date,
      sum(f.direction * f.settlement_amount)::bigint as amount,
      sum(f.direction * f.unit)::bigint as count
    from facts f
    where f.created_at >= v_current_from
    group by 1
  ),
  series_json as (
    select coalesce(jsonb_agg(jsonb_build_object(
      'date', bucket_date, 'amount', amount, 'count', count
    ) order by bucket_date), '[]'::jsonb) as value
    from buckets
    where amount <> 0 or count <> 0
  )
  select t.amount, t.previous_amount, t.count, t.previous_count, m.value, s.value
    into v_total_amount, v_previous_amount, v_total_count, v_previous_count, v_by_meal_type, v_series
  from totals t cross join meal_json m cross join series_json s;

  -- A company-scoped dashboard has no useful company ranking. Keeping this work
  -- behind the branch also avoids scanning/grouping the transaction population.
  if p_company_id is null then
    with company_values as (
      select t.company_id, c.name as company_name,
        sum((case when t.kind = 'spend' then 1 else -1 end)::bigint * coalesce(
          t.settlement_total_amount,
          case when t.pay_type = 'subsidized' then t.company_subsidy_amount else abs(t.amount) end,
          0
        )::bigint)::bigint as amount
      from public.meal_transactions t
      join public.companies c on c.id = t.company_id
      where t.kind in ('spend', 'refund', 'cancel')
        and t.pay_type in ('ledger', 'subsidized')
        and t.created_at >= v_current_from and t.created_at < v_current_to
        and (p_merchant_id is null or t.merchant_id = p_merchant_id)
      group by t.company_id, c.name
    ), ranked as (
      select *, row_number() over (order by amount desc, company_name, company_id) as rn from company_values
    ), display_rows as (
      select rn as sort_order, company_name as name, amount from ranked where rn <= 4
      union all
      select 5, '기타', sum(amount)::bigint from ranked where rn > 4 having count(*) > 0
    )
    select coalesce(jsonb_agg(jsonb_build_object(
      'rank', sort_order, 'name', name, 'amount', amount
    ) order by sort_order), '[]'::jsonb) into v_top_amount from display_rows;

    with company_values as (
      select t.company_id, c.name as company_name,
        sum((case when t.kind = 'spend' then 1 else -1 end)::bigint * (case when coalesce(t.flags, '{}'::jsonb) ? 'subsidy_charge' then 0 else 1 end)::bigint)::bigint as count
      from public.meal_transactions t
      join public.companies c on c.id = t.company_id
      where t.kind in ('spend', 'refund', 'cancel')
        and t.pay_type in ('ledger', 'subsidized')
        and t.created_at >= v_current_from and t.created_at < v_current_to
        and (p_merchant_id is null or t.merchant_id = p_merchant_id)
      group by t.company_id, c.name
    ), ranked as (
      select *, row_number() over (order by count desc, company_name, company_id) as rn from company_values
    ), display_rows as (
      select rn as sort_order, company_name as name, count from ranked where rn <= 4
      union all
      select 5, '기타', sum(count)::bigint from ranked where rn > 4 having count(*) > 0
    )
    select coalesce(jsonb_agg(jsonb_build_object(
      'rank', sort_order, 'name', name, 'count', count
    ) order by sort_order), '[]'::jsonb) into v_top_count from display_rows;
  end if;

  return jsonb_build_object(
    'total_amount', v_total_amount,
    'total_amount_delta_pct', case when v_previous_amount = 0 then null
      else round((v_total_amount - v_previous_amount)::numeric * 100.0 / abs(v_previous_amount), 1) end,
    'total_count', v_total_count,
    'total_count_delta_pct', case when v_previous_count = 0 then null
      else round((v_total_count - v_previous_count)::numeric * 100.0 / abs(v_previous_count), 1) end,
    'by_meal_type', coalesce(v_by_meal_type, '[]'::jsonb),
    'top_companies_by_amount', v_top_amount,
    'top_companies_by_count', v_top_count,
    'unit', v_unit,
    'series', coalesce(v_series, '[]'::jsonb)
  );
end $$;
revoke all on function public.admin_dashboard_summary(uuid, date, date, uuid, uuid, integer) from public, anon, authenticated, service_role;
grant execute on function public.admin_dashboard_summary(uuid, date, date, uuid, uuid, integer) to service_role;

CREATE OR REPLACE FUNCTION public.company_monthly_usage(p_actor_id uuid, p_company_id uuid, p_period_ym text)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $$
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
      -- 0081: a subsidy charged at purchase is a billing entry, not a meal: it keeps its
      -- company amount but adds no meal value and no count.
      not (coalesce(t.flags, '{}'::jsonb) ? 'subsidy_charge') as is_meal,
      case when coalesce(t.flags, '{}'::jsonb) ? 'subsidy_charge' then 0 else coalesce(t.total_amount, abs(t.amount), 0) end::bigint as gross_amount,
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
      count(*) filter (where is_meal)::int as transaction_count,
      count(*) filter (where kind = 'spend' and is_meal)::int as spend_count,
      count(*) filter (where kind in ('refund', 'cancel') and is_meal)::int as reversal_count,
      count(distinct user_id) filter (where kind = 'spend' and is_meal)::int as unique_users
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
    from public.normal_settlements s
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
        count(*) filter (where is_meal)::int as transaction_count,
        count(*) filter (where kind = 'spend' and is_meal)::int as spend_count,
        count(*) filter (where kind in ('refund', 'cancel') and is_meal)::int as reversal_count,
        count(distinct user_id) filter (where kind = 'spend' and is_meal)::int as unique_users
      from usage_rows group by usage_date
    ) d
  ),
  employee_usage as (
    select r.user_id,
      sum(r.direction * r.gross_amount)::bigint as gross_spend_amount,
      sum(r.direction * r.company_amount)::bigint as company_charge_amount,
      sum(r.direction * r.employee_amount)::bigint as employee_paid_amount,
      count(*) filter (where r.is_meal)::int as transaction_count,
      count(*) filter (where r.kind = 'spend' and r.is_meal)::int as spend_count,
      count(*) filter (where r.kind in ('refund', 'cancel') and r.is_meal)::int as reversal_count,
      count(distinct r.usage_date) filter (where r.is_meal)::int as usage_days
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

notify pgrst, 'reload schema';
