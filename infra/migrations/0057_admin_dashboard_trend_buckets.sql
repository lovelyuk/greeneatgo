-- Shared merchant/company/platform admin dashboard aggregate.
-- Dates are inclusive Seoul civil dates; service_role is the sole caller and the
-- token-derived actor and every requested tenant scope are revalidated here.

begin;

create or replace function public.admin_dashboard_summary(
  p_actor_id uuid,
  p_period_from date,
  p_period_to date,
  p_merchant_id uuid default null,
  p_company_id uuid default null,
  p_dinner_start_hour integer default null
) returns jsonb
language plpgsql
stable
security definer
set search_path = pg_catalog, public
as $$
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
      coalesce(sum(direction) filter (where created_at >= v_current_from), 0)::bigint as count,
      coalesce(sum(direction * settlement_amount) filter (where created_at < v_current_from), 0)::bigint as previous_amount,
      coalesce(sum(direction) filter (where created_at < v_current_from), 0)::bigint as previous_count
    from facts
  ),
  meal_names(meal_type, meal_order) as (values ('중식'::text, 1), ('석식'::text, 2)),
  meals as (
    select n.meal_type, n.meal_order,
      coalesce(sum(f.direction * f.settlement_amount), 0)::bigint as amount,
      coalesce(sum(f.direction), 0)::bigint as count,
      count(*) filter (where f.direction = 1)::bigint as spend_count
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
      sum(f.direction)::bigint as count
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
        sum((case when t.kind = 'spend' then 1 else -1 end)::bigint)::bigint as count
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

notify pgrst, 'reload schema';
commit;
