-- Safely recalculate an ordinary merchant settlement after changing its evidence period.
-- The monthly identity (period_ym) is immutable; only a range within that month can change.

create or replace function public.merchant_update_settlement_period(
  p_actor_id uuid,
  p_merchant_id uuid,
  p_settlement_id uuid,
  p_period_from date,
  p_period_to date,
  p_idempotency_key text
) returns jsonb
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  s public.settlements%rowtype;
  e public.settlement_events%rowtype;
  v_company_id uuid;
  v_period_ym text;
  v_previous_from date;
  v_previous_to date;
  v_count bigint;
  v_classified_count bigint;
  v_tax_type_count int;
  v_tax_type text;
  v_supply numeric;
  v_vat numeric;
  v_total numeric;
begin
  if p_period_from is null or p_period_to is null or p_period_from > p_period_to
     or date_trunc('month', p_period_from::timestamp) <> date_trunc('month', p_period_to::timestamp) then
    raise exception 'INVALID_DATE_RANGE' using errcode = 'P0001';
  end if;
  if p_idempotency_key is null or char_length(btrim(p_idempotency_key)) not between 1 and 128 then
    raise exception 'SETTLEMENT_INPUT_INVALID' using errcode = 'P0001';
  end if;
  if not exists (
    select 1 from public.app_users u
    where u.id = p_actor_id and u.merchant_id = p_merchant_id
      and u.role = 'merchant_admin' and u.status = 'active'
  ) then
    raise exception 'SETTLEMENT_FORBIDDEN' using errcode = 'P0001';
  end if;

  -- Resolve only an ordinary row before taking the same month advisory lock used by
  -- create_merchant_settlement. Re-read and lock it afterward to close the race.
  select company_id, period_ym into v_company_id, v_period_ym
  from public.settlements
  where id = p_settlement_id and merchant_id = p_merchant_id and not is_demo;
  if not found then
    raise exception 'SETTLEMENT_NOT_FOUND' using errcode = 'P0001';
  end if;

  perform pg_advisory_xact_lock(
    pg_catalog.hashtext(p_merchant_id::text),
    pg_catalog.hashtext(v_company_id::text || ':' || v_period_ym)
  );

  select * into s
  from public.settlements
  where id = p_settlement_id and merchant_id = p_merchant_id
    and company_id = v_company_id and period_ym = v_period_ym and not is_demo
  for update;
  if not found then
    raise exception 'SETTLEMENT_NOT_FOUND' using errcode = 'P0001';
  end if;
  if to_char(p_period_from, 'YYYY-MM') <> s.period_ym then
    raise exception 'INVALID_DATE_RANGE' using errcode = 'P0001';
  end if;

  select * into e
  from public.settlement_events
  where settlement_id = s.id
    and event_type = 'merchant_settlement_period_updated'
    and idempotency_key = btrim(p_idempotency_key);
  if found then
    if e.payload->>'period_from' is distinct from p_period_from::text
       or e.payload->>'period_to' is distinct from p_period_to::text then
      raise exception 'IDEMPOTENCY_CONFLICT' using errcode = 'P0001';
    end if;
    return jsonb_build_object(
      'settlement', coalesce(e.payload->'settlement', to_jsonb(s)),
      'idempotent', true
    );
  end if;

  if s.settlement_status not in ('draft', 'revising')
     or s.tax_invoice_status <> 'not_requested' then
    raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode = 'P0001';
  end if;

  -- This is intentionally the same KST population and immutable tax-snapshot
  -- validation used by the ordinary create_merchant_settlement implementation.
  select count(*),
    count(*) filter(where t.settlement_tax_type in ('taxable', 'tax_free')
      and t.settlement_supply_amount is not null
      and t.settlement_vat_amount is not null
      and t.settlement_total_amount is not null
      and t.settlement_supply_amount + t.settlement_vat_amount = t.settlement_total_amount
      and ((t.settlement_tax_type = 'tax_free' and t.settlement_vat_amount = 0
            and t.settlement_supply_amount = t.settlement_total_amount)
        or (t.settlement_tax_type = 'taxable'
            and t.settlement_supply_amount = round(t.settlement_total_amount::numeric / 1.1)::int
            and t.settlement_vat_amount = t.settlement_total_amount - t.settlement_supply_amount))),
    count(distinct t.settlement_tax_type) filter(where t.settlement_tax_type in ('taxable', 'tax_free')),
    min(t.settlement_tax_type) filter(where t.settlement_tax_type in ('taxable', 'tax_free')),
    coalesce(sum(case when t.kind = 'spend' then t.settlement_supply_amount else -t.settlement_supply_amount end), 0),
    coalesce(sum(case when t.kind = 'spend' then t.settlement_vat_amount else -t.settlement_vat_amount end), 0),
    coalesce(sum(case when t.kind = 'spend' then t.settlement_total_amount else -t.settlement_total_amount end), 0)
  into v_count, v_classified_count, v_tax_type_count, v_tax_type, v_supply, v_vat, v_total
  from public.normal_meal_transactions t
  where t.merchant_id = p_merchant_id and t.company_id = s.company_id
    and t.pay_type in ('ledger', 'subsidized') and t.kind in ('spend', 'refund', 'cancel')
    and t.created_at >= (p_period_from::timestamp at time zone 'Asia/Seoul')
    and t.created_at < ((p_period_to + 1)::timestamp at time zone 'Asia/Seoul');

  if v_count <> v_classified_count or v_count = 0 then
    raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode = 'P0001';
  end if;
  if v_tax_type_count <> 1 then
    raise exception 'MIXED_TAX_TYPES_NOT_SUPPORTED' using errcode = 'P0001';
  end if;
  if v_count > 2147483647
     or v_supply < 0 or v_vat < 0 or v_total < 0 or v_supply + v_vat <> v_total
     or v_supply > 2147483647 or v_vat > 2147483647 or v_total > 2147483647 then
    raise exception 'SETTLEMENT_AMOUNTS_INVALID' using errcode = 'P0001';
  end if;

  v_previous_from := s.period_from;
  v_previous_to := s.period_to;
  update public.settlements
  set period_from = p_period_from,
      period_to = p_period_to,
      tx_count = v_count::int,
      supply_amount = v_supply::int,
      vat_amount = v_vat::int,
      total_amount = v_total::int,
      settlement_tax_type = v_tax_type,
      due_date = p_period_to + 30,
      updated_at = pg_catalog.clock_timestamp()
  where id = s.id
  returning * into s;

  insert into public.settlement_events(
    settlement_id, company_id, merchant_id, event_type, payload, idempotency_key, actor_id
  ) values (
    s.id, s.company_id, s.merchant_id, 'merchant_settlement_period_updated',
    jsonb_build_object(
      'previous_period_from', v_previous_from,
      'previous_period_to', v_previous_to,
      'period_from', p_period_from,
      'period_to', p_period_to,
      'tx_count', s.tx_count,
      'supply_amount', s.supply_amount,
      'vat_amount', s.vat_amount,
      'total_amount', s.total_amount,
      'settlement', to_jsonb(s)
    ),
    btrim(p_idempotency_key), p_actor_id
  );

  return jsonb_build_object('settlement', to_jsonb(s), 'idempotent', false);
end $$;

revoke all on function public.merchant_update_settlement_period(uuid,uuid,uuid,date,date,text)
  from public, anon, authenticated;
grant execute on function public.merchant_update_settlement_period(uuid,uuid,uuid,date,date,text)
  to service_role;

-- Refresh an already-existing ordinary draft over its saved evidence range. This
-- deliberately does not take the month advisory lock: callers that found an
-- existing settlement already hold its row lock, while period edits acquire the
-- advisory lock before that row lock. Taking them in the opposite order here
-- would deadlock with merchant_update_settlement_period.
create or replace function public.refresh_ordinary_settlement_saved_period(
  p_settlement_id uuid,
  p_period_from date,
  p_period_to date
) returns void
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  s public.settlements%rowtype;
  v_count bigint;
  v_classified_count bigint;
  v_tax_type_count int;
  v_tax_type text;
  v_supply numeric;
  v_vat numeric;
  v_total numeric;
begin
  select * into s
  from public.settlements
  where id = p_settlement_id and not is_demo
  for update;
  if not found then
    raise exception 'SETTLEMENT_NOT_FOUND' using errcode = 'P0001';
  end if;
  if s.settlement_status not in ('draft', 'calculating', 'revising')
     or s.tax_invoice_status <> 'not_requested' then
    raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode = 'P0001';
  end if;
  if p_period_from is null or p_period_to is null or p_period_from > p_period_to
     or p_period_from <> s.period_from or p_period_to <> s.period_to
     or to_char(p_period_from, 'YYYY-MM') <> s.period_ym
     or date_trunc('month', p_period_from::timestamp) <> date_trunc('month', p_period_to::timestamp) then
    raise exception 'INVALID_DATE_RANGE' using errcode = 'P0001';
  end if;

  select count(*),
    count(*) filter(where t.settlement_tax_type in ('taxable', 'tax_free')
      and t.settlement_supply_amount is not null
      and t.settlement_vat_amount is not null
      and t.settlement_total_amount is not null
      and t.settlement_supply_amount + t.settlement_vat_amount = t.settlement_total_amount
      and ((t.settlement_tax_type = 'tax_free' and t.settlement_vat_amount = 0
            and t.settlement_supply_amount = t.settlement_total_amount)
        or (t.settlement_tax_type = 'taxable'
            and t.settlement_supply_amount = round(t.settlement_total_amount::numeric / 1.1)::int
            and t.settlement_vat_amount = t.settlement_total_amount - t.settlement_supply_amount))),
    count(distinct t.settlement_tax_type) filter(where t.settlement_tax_type in ('taxable', 'tax_free')),
    min(t.settlement_tax_type) filter(where t.settlement_tax_type in ('taxable', 'tax_free')),
    coalesce(sum(case when t.kind = 'spend' then t.settlement_supply_amount else -t.settlement_supply_amount end), 0),
    coalesce(sum(case when t.kind = 'spend' then t.settlement_vat_amount else -t.settlement_vat_amount end), 0),
    coalesce(sum(case when t.kind = 'spend' then t.settlement_total_amount else -t.settlement_total_amount end), 0)
  into v_count, v_classified_count, v_tax_type_count, v_tax_type, v_supply, v_vat, v_total
  from public.normal_meal_transactions t
  where t.merchant_id = s.merchant_id and t.company_id = s.company_id
    and t.pay_type in ('ledger', 'subsidized') and t.kind in ('spend', 'refund', 'cancel')
    and t.created_at >= (p_period_from::timestamp at time zone 'Asia/Seoul')
    and t.created_at < ((p_period_to + 1)::timestamp at time zone 'Asia/Seoul');

  if v_count <> v_classified_count or v_count = 0 then
    raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode = 'P0001';
  end if;
  if v_tax_type_count <> 1 then
    raise exception 'MIXED_TAX_TYPES_NOT_SUPPORTED' using errcode = 'P0001';
  end if;
  if v_count > 2147483647
     or v_supply < 0 or v_vat < 0 or v_total < 0 or v_supply + v_vat <> v_total
     or v_supply > 2147483647 or v_vat > 2147483647 or v_total > 2147483647 then
    raise exception 'SETTLEMENT_AMOUNTS_INVALID' using errcode = 'P0001';
  end if;

  -- Preserve both workflow axes and all payment state. Only evidence-derived
  -- fields (plus the saved range and timestamp) are mutable here.
  update public.settlements
  set period_from = p_period_from,
      period_to = p_period_to,
      tx_count = v_count::int,
      supply_amount = v_supply::int,
      vat_amount = v_vat::int,
      total_amount = v_total::int,
      settlement_tax_type = v_tax_type,
      due_date = p_period_to + 30,
      updated_at = pg_catalog.clock_timestamp()
  where id = s.id;
end $$;

revoke all on function public.refresh_ordinary_settlement_saved_period(uuid,date,date)
  from public, anon, authenticated, service_role;

-- Override 0053 so an eligible insert refreshes an existing custom range rather
-- than routing through create_merchant_settlement, which resets the range and
-- workflow/payment axes to a fresh full-month draft.
create or replace function public.refresh_monthly_draft_after_meal_transaction()
returns trigger
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  v_period_from date;
  v_period_to date;
  s public.settlements%rowtype;
  v_count bigint;
  v_classified_count bigint;
  v_tax_type_count int;
begin
  if new.company_id is null
     or new.merchant_id is null
     or new.pay_type not in ('ledger', 'subsidized')
     or new.kind not in ('spend', 'refund', 'cancel')
     or new.is_demo
     or coalesce(new.flags, '{}'::jsonb) ? 'settlement_demo' then
    return new;
  end if;

  v_period_from := date_trunc('month', new.created_at at time zone 'Asia/Seoul')::date;
  v_period_to := (v_period_from + interval '1 month - 1 day')::date;

  if exists(select 1 from public.settlement_demo_runs r
    where r.merchant_id = new.merchant_id and r.company_id = new.company_id
      and r.period_ym = to_char(v_period_from, 'YYYY-MM') and r.is_current) then
    return new;
  end if;

  if not exists(select 1 from public.merchants m where m.id = new.merchant_id and m.status = 'active')
     or not exists(select 1 from public.companies c where c.id = new.company_id and c.status = 'active')
     or not exists(select 1 from public.merchant_companies mc
       where mc.merchant_id = new.merchant_id and mc.company_id = new.company_id and mc.status = 'active') then
    return new;
  end if;

  select * into s
  from public.settlements
  where merchant_id = new.merchant_id and company_id = new.company_id
    and period_ym = to_char(v_period_from, 'YYYY-MM') and not is_demo
  for update;

  if found then
    if s.settlement_status not in ('draft', 'calculating', 'revising')
       or s.tax_invoice_status <> 'not_requested' then
      return new;
    end if;
    if (new.created_at at time zone 'Asia/Seoul')::date < s.period_from
       or (new.created_at at time zone 'Asia/Seoul')::date > s.period_to then
      return new;
    end if;
    perform public.refresh_ordinary_settlement_saved_period(s.id, s.period_from, s.period_to);
    return new;
  end if;

  -- Preserve 0053's full-month validation/create behavior when this is the first
  -- eligible transaction for the month.
  select count(*),
    count(*) filter(where t.settlement_tax_type in ('taxable', 'tax_free')
      and t.settlement_supply_amount is not null
      and t.settlement_vat_amount is not null
      and t.settlement_total_amount is not null
      and t.settlement_supply_amount + t.settlement_vat_amount = t.settlement_total_amount),
    count(distinct t.settlement_tax_type) filter(where t.settlement_tax_type in ('taxable', 'tax_free'))
  into v_count, v_classified_count, v_tax_type_count
  from public.normal_meal_transactions t
  where t.merchant_id = new.merchant_id and t.company_id = new.company_id
    and t.pay_type in ('ledger', 'subsidized') and t.kind in ('spend', 'refund', 'cancel')
    and t.created_at >= (v_period_from::timestamp at time zone 'Asia/Seoul')
    and t.created_at < ((v_period_to + 1)::timestamp at time zone 'Asia/Seoul');

  if v_count <> v_classified_count or v_count = 0 or v_tax_type_count <> 1 then
    return new;
  end if;

  perform public.create_merchant_settlement(
    new.merchant_id, new.company_id, v_period_from, v_period_to
  );
  return new;
end $$;

revoke all on function public.refresh_monthly_draft_after_meal_transaction()
  from public, anon, authenticated, service_role;

notify pgrst, 'reload schema';

commit;
