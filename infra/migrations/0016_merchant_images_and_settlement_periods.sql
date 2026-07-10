-- Merchant images, employee numbers, safe arbitrary settlement periods, and merchant realtime.
-- Apply after 0015.
alter table merchant_daily_menus add column if not exists image_url text;
alter table voucher_products add column if not exists image_url text;
alter table app_users add column if not exists employee_no text;

alter table settlements
  add column if not exists period_from date,
  add column if not exists period_to date;

-- Repair both fully missing and partially populated historical period columns when period_ym is usable.
update settlements
set period_from = (period_ym || '-01')::date,
    period_to = ((period_ym || '-01')::date + interval '1 month - 1 day')::date
where (period_from is null or period_to is null)
  and period_ym ~ '^[0-9]{4}-[0-9]{2}$';

alter table settlements drop constraint if exists settlements_period_bounds_check;
alter table settlements add constraint settlements_period_bounds_check check (
  (period_from is null and period_to is null)
  or (period_from is not null and period_to is not null and period_from <= period_to)
);

create unique index if not exists idx_settlements_company_merchant_period
  on settlements(company_id, merchant_id, period_from, period_to)
  where period_from is not null and period_to is not null;
create index if not exists idx_app_users_employee_group on app_users(group_id, employee_no);
create index if not exists idx_meal_transactions_settlement_range
  on meal_transactions(merchant_id, company_id, created_at) where pay_type = 'ledger';

-- Aggregate an arbitrary KST date range in the database, independent of PostgREST row limits.
create or replace function merchant_ledger_summary(
  p_merchant_id uuid, p_company_id uuid, p_period_from date, p_period_to date
) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare v_result jsonb;
begin
  if p_period_from is null or p_period_to is null or p_period_from > p_period_to then
    raise exception 'INVALID_DATE_RANGE' using errcode = 'P0001';
  end if;
  select jsonb_build_object(
    'total_amount', coalesce(sum(case when kind = 'spend' then abs(amount) when kind in ('refund','cancel') then -abs(amount) else amount end), 0),
    'total_count', count(*),
    'cancel_count', count(*) filter (where kind in ('refund','cancel'))
  ) into v_result
  from meal_transactions
  where merchant_id = p_merchant_id and company_id = p_company_id and pay_type = 'ledger'
    and created_at >= (p_period_from::timestamp at time zone 'Asia/Seoul')
    and created_at < ((p_period_to + 1)::timestamp at time zone 'Asia/Seoul');
  return v_result;
end $$;
revoke all on function merchant_ledger_summary(uuid, uuid, date, date) from public, anon, authenticated;
grant execute on function merchant_ledger_summary(uuid, uuid, date, date) to service_role;

create or replace function merchant_transaction_count(p_merchant_id uuid) returns bigint
language sql stable security definer set search_path = public
as $$ select count(*) from meal_transactions where merchant_id = p_merchant_id and pay_type in ('ledger','voucher') $$;
revoke all on function merchant_transaction_count(uuid) from public, anon, authenticated;
grant execute on function merchant_transaction_count(uuid) to service_role;

-- One transaction validates overlap, aggregates ledger-only rows with KST boundaries, and inserts.
create or replace function create_merchant_settlement(
  p_merchant_id uuid, p_company_id uuid, p_period_from date, p_period_to date
) returns jsonb
language plpgsql security definer set search_path = public as $$
declare v_summary jsonb; v_row settlements%rowtype;
begin
  if p_period_from is null or p_period_to is null or p_period_from > p_period_to then
    raise exception 'INVALID_DATE_RANGE' using errcode = 'P0001';
  end if;
  perform pg_advisory_xact_lock(hashtext(p_merchant_id::text), hashtext(p_company_id::text));
  if exists (
    select 1 from settlements
    where merchant_id = p_merchant_id and company_id = p_company_id
      and period_from is not null and period_to is not null
      and daterange(period_from, period_to, '[]') && daterange(p_period_from, p_period_to, '[]')
  ) then raise exception 'SETTLEMENT_PERIOD_OVERLAP' using errcode = 'P0001'; end if;
  v_summary := merchant_ledger_summary(p_merchant_id, p_company_id, p_period_from, p_period_to);
  insert into settlements(company_id, merchant_id, period_ym, period_from, period_to, tx_count, total_amount, status)
  values (p_company_id, p_merchant_id, p_period_from || ':' || p_period_to, p_period_from, p_period_to,
          (v_summary->>'total_count')::int, (v_summary->>'total_amount')::int, 'confirmed')
  returning * into v_row;
  return to_jsonb(v_row);
end $$;
revoke all on function create_merchant_settlement(uuid, uuid, date, date) from public, anon, authenticated;
grant execute on function create_merchant_settlement(uuid, uuid, date, date) to service_role;

-- Merchant admins may receive INSERT events only for their own merchant. The API still enriches payloads.
alter table meal_transactions enable row level security;
drop policy if exists merchant_admin_read_own_transactions on meal_transactions;
create policy merchant_admin_read_own_transactions on meal_transactions for select to authenticated
using (merchant_id in (
  select coalesce(u.merchant_id, ma.merchant_id)
  from app_users u left join merchant_admins ma on ma.user_id = u.id
  where u.id = auth.uid() and u.role = 'merchant_admin' and u.status = 'active'
));
do $$ begin
  alter publication supabase_realtime add table meal_transactions;
exception when duplicate_object then null;
end $$;

-- Only the service-role API writes objects; clients display public URLs.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('merchant-images', 'merchant-images', true, 5242880, array['image/jpeg','image/png','image/webp','image/gif'])
on conflict (id) do update set public=excluded.public, file_size_limit=excluded.file_size_limit,
  allowed_mime_types=excluded.allowed_mime_types;
